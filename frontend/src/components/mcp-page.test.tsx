import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { McpPage } from "./mcp-page";

const API = "https://api.example.test";
const KEY = "mcp-key-value-123";
const VIEW_KEY = "view-key-from-start";

type Call = { method: string; path: string; body: unknown; headers: Record<string, string>; key: string | null };

const json = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const TOOLS = {
  server: { name: "files", version: "2" },
  tools: [
    { name: "read_file", description: "Reads a file.", params: ["path"], effect_hint: "reads" },
    { name: "write_file", description: "Writes a file.", params: ["path", "text"], effect_hint: "unknown" },
  ],
};

class FakeBackend {
  calls: Call[] = [];
  overrides: Record<string, (body: unknown) => Response> = {};
  scans: unknown[] = [];
  locked = false;

  install() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const url = new URL(String(input));
        const method = init.method ?? "GET";
        const body = init.body ? JSON.parse(String(init.body)) : undefined;
        const viewKey = url.searchParams.get("key");
        this.calls.push({ method, path: url.pathname, body, headers: (init.headers ?? {}) as Record<string, string>, key: viewKey });
        if (this.locked) return json(401, {});
        const key = `${method} ${url.pathname}`;
        const override = this.overrides[key];
        if (override) return override(body);
        if (key === "POST /mcp-scans/check") return json(200, TOOLS);
        if (key === "POST /mcp-scans") return json(202, { scan_id: 41, view_key: VIEW_KEY });
        if (key === "GET /open-scans/41") {
          if (viewKey !== VIEW_KEY) return json(404, {});
          return json(200, this.scans.length > 1 ? this.scans.shift() : this.scans[0]);
        }
        return json(404, { error: { kind: "unexpected", message: key } });
      }),
    );
    return this;
  }

  bodies(path: string): unknown[] {
    return this.calls.filter((c) => c.path === path).map((c) => c.body);
  }
}

afterEach(() => vi.unstubAllGlobals());

async function opened(backend: FakeBackend, pollMs = 5) {
  backend.install();
  const user = userEvent.setup();
  render(<McpPage apiUrl={API} pollMs={pollMs} />);
  await screen.findByRole("heading", { name: "Check an MCP server" });
  return user;
}

async function listed(backend: FakeBackend) {
  const user = await opened(backend);
  await user.type(screen.getByLabelText("Server address"), "https://mcp.example.com/mcp");
  await user.type(screen.getByLabelText("Access key"), KEY);
  await user.click(screen.getByRole("button", { name: "Look at the tools" }));
  await screen.findByRole("list", { name: "Tools on this server" });
  return user;
}

describe("looking at the server", () => {
  it("has no password step and sends no owner header", async () => {
    const backend = new FakeBackend();
    await listed(backend);
    expect(screen.queryByLabelText("Owner password")).not.toBeInTheDocument();
    expect(backend.calls.every((c) => !("X-Owner-Token" in c.headers))).toBe(true);
  });

  it("says plainly when the backend has not opened the tool yet", async () => {
    const backend = new FakeBackend();
    backend.install();
    const user = userEvent.setup();
    render(<McpPage apiUrl={API} />);
    backend.locked = true;
    await user.type(screen.getByLabelText("Server address"), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This tool is not open yet.");
  });

  it("keeps the key in a password field and sends it only with the look and the run", async () => {
    const backend = new FakeBackend();
    const user = await listed(backend);
    expect(screen.getByLabelText("Access key")).toHaveAttribute("type", "password");
    expect(backend.bodies("/mcp-scans/check")).toEqual([
      { url: "https://mcp.example.com/mcp", key: KEY, header_name: "Authorization", header_prefix: "Bearer " },
    ]);
    expect(document.body.textContent).not.toContain(KEY);
    expect(user).toBeDefined();
  });

  it("lists the tools with what they do, and says only the ticked ones are called", async () => {
    await listed(new FakeBackend());
    const tools = screen.getByRole("list", { name: "Tools on this server" });
    expect(within(tools).getAllByRole("listitem")).toHaveLength(2);
    expect(within(tools).getByText("Reads a file.")).toBeInTheDocument();
    expect(screen.getByText(/Tool descriptions are always checked/)).toBeInTheDocument();
    expect(screen.getByText(/only called if you tick them/)).toBeInTheDocument();
    for (const box of within(tools).getAllByRole("checkbox", { name: /Call this tool/ })) {
      expect(box).not.toBeChecked();
    }
  });

  it("explains why the server could not be reached in plain words", async () => {
    const backend = new FakeBackend();
    backend.overrides["POST /mcp-scans/check"] = () =>
      json(422, { error: { kind: "connection_failed", message: "The server answered with status 401." } });
    const user = await opened(backend);
    await user.type(screen.getByLabelText("Server address"), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not reach your bot: The server answered with status 401.",
    );
  });
});

describe("choosing what to call", () => {
  it("starts a tool the server calls read-only as 'only reads' and any other as 'changes things'", async () => {
    await listed(new FakeBackend());
    expect(screen.getByLabelText("What does read_file do?")).toHaveValue("reads");
    expect(screen.getByLabelText("What does write_file do?")).toHaveValue("acts");
  });

  it("asks for the sandbox box only when a ticked tool changes things, and holds Run until then", async () => {
    const user = await listed(new FakeBackend());
    const run = screen.getByRole("button", { name: "Run checks" });
    expect(screen.queryByLabelText(/test or sandbox/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Call this tool: read_file" }));
    expect(run).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: "Call this tool: write_file" }));
    expect(run).toBeDisabled();
    await user.click(screen.getByLabelText(/test or sandbox/));
    expect(run).toBeEnabled();
  });

  it("runs with nothing ticked as description checks only", async () => {
    const backend = new FakeBackend();
    backend.scans = [makeScan([], { id: 41, status: "running" })];
    const user = await listed(backend);
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await screen.findByRole("heading", { name: "Scan #41" });
    expect(backend.bodies("/mcp-scans")).toEqual([
      {
        url: "https://mcp.example.com/mcp",
        key: KEY,
        header_name: "Authorization",
        header_prefix: "Bearer ",
        exercise: [],
        sandbox_confirmed: false,
      },
    ]);
  });
});

describe("running", () => {
  it("sends the ticked tools with what each does, then shows progress and the results", async () => {
    const backend = new FakeBackend();
    const running = makeScan([], { id: 41, status: "running" });
    const done = makeScan([makeResult({ test_id: "mcp-static-broad_parameters", title: "Tool inputs", status: "pass" })], { id: 41 });
    backend.scans = [running, running, done];
    const user = await listed(backend);
    await user.click(screen.getByRole("checkbox", { name: "Call this tool: read_file" }));
    await user.click(screen.getByRole("checkbox", { name: "Call this tool: write_file" }));
    await user.selectOptions(screen.getByLabelText("What does write_file do?"), "reads");
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    expect((backend.bodies("/mcp-scans")[0] as { exercise: unknown }).exercise).toEqual([
      { name: "read_file", effect: "reads" },
      { name: "write_file", effect: "reads" },
    ]);
    expect(await screen.findByText(/of 16 tests done/)).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Overview" })).toBeInTheDocument();
    const withKey = backend.calls.filter((c) => JSON.stringify(c.body ?? "").includes(KEY)).map((c) => c.path);
    expect(withKey.sort()).toEqual(["/mcp-scans", "/mcp-scans/check"]);
  });

  it.each([
    ["sandbox_required", /test or sandbox/i, 422],
    ["unknown_tool", /not on the server/i, 422],
    ["scan_running", /already running/i, 409],
  ])("explains a refusal: %s", async (kind, words, status) => {
    const backend = new FakeBackend();
    backend.overrides["POST /mcp-scans"] = () => json(status, { error: { kind } });
    const user = await listed(backend);
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(words));
  }, 20000);
});
