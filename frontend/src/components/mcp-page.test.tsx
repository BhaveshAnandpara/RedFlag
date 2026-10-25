import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { McpPage, urlProblem } from "./mcp-page";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

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
    { name: "workspace_stats", description: "", params: [], effect_hint: "unknown" },
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
          if (viewKey !== VIEW_KEY || this.scans.length === 0) return json(404, {});
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

beforeEach(() => push.mockReset());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const address = () => screen.getByLabelText(/Server address/);

async function opened(backend: FakeBackend) {
  backend.install();
  const user = userEvent.setup();
  render(<McpPage apiUrl={API} pollMs={5} />);
  await screen.findByRole("heading", { name: "Check an MCP server" });
  return user;
}

async function looked(backend: FakeBackend) {
  const user = await opened(backend);
  await user.type(address(), "https://mcp.example.com/mcp");
  await user.type(screen.getByLabelText(/Access key/), KEY);
  await user.click(screen.getByRole("button", { name: "Look at the tools" }));
  await screen.findByRole("list", { name: "Tools on this server" });
  return user;
}

const tick = (name: string) => screen.getByRole("checkbox", { name: `Call this tool: ${name}` });
const effect = (name: string) => screen.getByLabelText(`What does ${name} do?`);

describe("the address", () => {
  it.each([
    ["", "Enter the server address."],
    ["mcp.example.com", "Enter the full address, starting with https://."],
    ["http://mcp.example.com/mcp", "Use a public https address."],
    ["https://127.0.0.1/mcp", "That address is not allowed: it points to a private or internal address."],
    ["https://192.168.1.4/mcp", "That address is not allowed: it points to a private or internal address."],
    ["https://mcp.example.com/mcp", ""],
  ])("%s", (value, problem) => {
    expect(urlProblem(value)).toBe(problem);
  });
});

describe("connecting", () => {
  it("opens straight on the form: no password, no owner header, three steps", async () => {
    const backend = new FakeBackend();
    await opened(backend);
    expect(screen.queryByLabelText("Owner password")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connect" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose what to call" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Results" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Look at the tools" })).toBeDisabled();
    expect(screen.queryByRole("list", { name: "Tools on this server" })).not.toBeInTheDocument();
  });

  it("keeps the key in a password field and sends it, with the header it goes in, only to look and to run", async () => {
    const backend = new FakeBackend();
    const user = await looked(backend);
    expect(backend.bodies("/mcp-scans/check")).toEqual([
      { url: "https://mcp.example.com/mcp", key: KEY, header_name: "Authorization", header_prefix: "Bearer " },
    ]);
    expect(document.body.textContent).not.toContain(KEY);
    await user.click(screen.getByRole("checkbox", { name: /test or sandbox, not production/ }));
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await waitFor(() => expect(backend.calls.some((c) => c.path === "/mcp-scans")).toBe(true));
    const withKey = backend.calls.filter((c) => JSON.stringify(c.body ?? "").includes(KEY)).map((c) => c.path);
    expect(withKey.sort()).toEqual(["/mcp-scans", "/mcp-scans/check"]);
  });

  it("sends the header name and prefix the person set", async () => {
    const backend = new FakeBackend();
    const user = await opened(backend);
    await user.type(address(), "https://mcp.example.com/mcp");
    await user.click(screen.getByText("How the key is sent"));
    const name = screen.getByLabelText(/Key header name/);
    await user.clear(name);
    await user.type(name, "X-Api-Key");
    await user.clear(screen.getByLabelText(/Key header prefix/));
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    await screen.findByRole("list", { name: "Tools on this server" });
    expect(backend.bodies("/mcp-scans/check")).toEqual([
      { url: "https://mcp.example.com/mcp", key: null, header_name: "X-Api-Key", header_prefix: "" },
    ]);
  });

  it("catches a bad address before sending anything, and clears the message when it is fixed", async () => {
    const backend = new FakeBackend();
    const user = await opened(backend);
    await user.type(address(), "http://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    expect(screen.getByText("Use a public https address.")).toBeInTheDocument();
    expect(address()).toHaveAttribute("aria-invalid", "true");
    expect(backend.bodies("/mcp-scans/check")).toEqual([]);
    await user.clear(address());
    await user.type(address(), "https://mcp.example.com/mcp");
    expect(screen.queryByText("Use a public https address.")).not.toBeInTheDocument();
  });

  it("explains why the server could not be reached in plain words", async () => {
    const backend = new FakeBackend();
    backend.overrides["POST /mcp-scans/check"] = () =>
      json(422, { error: { kind: "connection_failed", message: "The server answered with status 401." } });
    const user = await opened(backend);
    await user.type(address(), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "We could not reach your bot: The server answered with status 401.",
    );
    expect(screen.queryByRole("list", { name: "Tools on this server" })).not.toBeInTheDocument();
  });

  it("says plainly when the backend has not opened the tool yet", async () => {
    const backend = new FakeBackend();
    backend.install();
    const user = userEvent.setup();
    render(<McpPage apiUrl={API} />);
    backend.locked = true;
    await user.type(address(), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    expect(await screen.findByRole("status")).toHaveTextContent("This tool is not open yet.");
  });
});

describe("choosing what to call", () => {
  it("lists every tool, all ticked, with what it takes, and a summary on the closed first step", async () => {
    await looked(new FakeBackend());
    const list = screen.getByRole("list", { name: "Tools on this server" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: /3 tools/ })).toHaveTextContent("3 tools on files");
    for (const name of ["read_file", "write_file", "workspace_stats"]) expect(tick(name)).toBeChecked();
    expect(screen.getByText("path, text")).toBeInTheDocument();
    expect(screen.getByText("no inputs")).toBeInTheDocument();
    expect(screen.getByText("No description.")).toBeInTheDocument();
    expect(screen.getByText("mcp.example.com · 3 tools")).toBeInTheDocument();
  });

  it("starts a tool the server calls read-only as 'only reads' and every other tool as 'changes things'", async () => {
    await looked(new FakeBackend());
    expect(effect("read_file")).toHaveValue("reads");
    expect(effect("write_file")).toHaveValue("changes");
    expect(effect("workspace_stats")).toHaveValue("changes");
  });

  it("filters by search and by chip, with the counts on the chips", async () => {
    const user = await looked(new FakeBackend());
    expect(screen.getByRole("button", { name: /^Only reads/ })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: /^Changes things/ })).toHaveTextContent("2");
    await user.click(screen.getByRole("button", { name: /^Only reads/ }));
    expect(within(screen.getByRole("list", { name: "Tools on this server" })).getAllByRole("listitem")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /^All/ }));
    await user.type(screen.getByRole("searchbox", { name: "Search tools" }), "write");
    expect(within(screen.getByRole("list", { name: "Tools on this server" })).getAllByRole("listitem")).toHaveLength(1);
    await user.clear(screen.getByRole("searchbox", { name: "Search tools" }));
    await user.type(screen.getByRole("searchbox", { name: "Search tools" }), "nothing like this");
    expect(screen.getByText("No tools match.")).toBeInTheDocument();
  });

  it("unticks and ticks every tool at once, and says how many will be called", async () => {
    const user = await looked(new FakeBackend());
    expect(document.querySelector(".plan")).toHaveTextContent("3 tools called, 3 described");
    await user.click(screen.getByRole("button", { name: "Untick all" }));
    for (const name of ["read_file", "write_file", "workspace_stats"]) expect(tick(name)).not.toBeChecked();
    expect(document.querySelector(".plan")).toHaveTextContent("No tool ticked: only the 3 descriptions are checked.");
    await user.click(screen.getByRole("button", { name: "Tick all" }));
    expect(tick("read_file")).toBeChecked();
  });

  it("unticks and ticks only the filtered tools, leaving the rest alone", async () => {
    const user = await looked(new FakeBackend());
    await user.click(screen.getByRole("button", { name: /^Changes things/ }));
    await user.click(screen.getByRole("button", { name: "Untick all (2)" }));
    expect(tick("write_file")).not.toBeChecked();
    expect(tick("workspace_stats")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: /^All/ }));
    expect(tick("read_file")).toBeChecked(); // untouched: it was never in the "changes" filter
    await user.click(screen.getByRole("button", { name: /^Changes things/ }));
    await user.click(screen.getByRole("button", { name: "Tick all (2)" }));
    expect(tick("write_file")).toBeChecked();
  });

  it("asks for the sandbox box only while a ticked tool changes things, and refuses to run without it", async () => {
    const backend = new FakeBackend();
    const user = await looked(backend);
    expect(screen.getByRole("checkbox", { name: /test or sandbox, not production/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    expect(screen.getByText(/can only be called on a test or sandbox server/)).toBeInTheDocument();
    expect(backend.bodies("/mcp-scans")).toEqual([]);
    await user.click(screen.getByRole("checkbox", { name: /test or sandbox, not production/ }));
    expect(screen.queryByText(/can only be called on a test or sandbox server/)).not.toBeInTheDocument();
    await user.click(tick("write_file"));
    await user.click(tick("workspace_stats"));
    expect(screen.queryByRole("checkbox", { name: /test or sandbox, not production/ })).not.toBeInTheDocument();
  });

  it("runs with nothing ticked as description checks only, and needs no sandbox box", async () => {
    const backend = new FakeBackend();
    backend.scans = [makeScan([], { id: 41, status: "running" })];
    const user = await looked(backend);
    await user.click(screen.getByRole("button", { name: "Untick all" }));
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await screen.findByText("MCP check #41");
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

  it("sends the ticked tools with what each does, and the sandbox confirmation", async () => {
    const backend = new FakeBackend();
    backend.scans = [makeScan([], { id: 41, status: "running" })];
    const user = await looked(backend);
    await user.click(tick("workspace_stats"));
    await user.selectOptions(effect("write_file"), "reads");
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await screen.findByText("MCP check #41");
    expect((backend.bodies("/mcp-scans")[0] as { exercise: unknown; sandbox_confirmed: boolean })).toMatchObject({
      exercise: [
        { name: "read_file", effect: "reads" },
        { name: "write_file", effect: "reads" },
      ],
      sandbox_confirmed: false,
    });
  });

  it("lets the person go back to a closed step with Change", async () => {
    const user = await looked(new FakeBackend());
    await user.click(screen.getByRole("button", { name: "Change" }));
    expect(address()).toHaveValue("https://mcp.example.com/mcp");
    expect(screen.queryByRole("list", { name: "Tools on this server" })).not.toBeInTheDocument();
  });
});

describe("the results", () => {
  const staticPass = makeResult({
    test_id: "mcp-static-hidden_instructions",
    title: "Tool descriptions: hidden instructions",
    status: "pass",
    severity: "critical",
  });
  const staticFail = makeResult({
    test_id: "mcp-static-broad_parameters-write_file",
    title: "Tool inputs: open-ended parameters: write_file",
    status: "fail",
    severity: "medium",
  });
  const callFail = makeResult({
    test_id: "mcp-dyn-read_file-traversal-path-1",
    title: "read_file: path traversal in “path”",
    status: "fail",
    severity: "critical",
  });
  const callUnclear = makeResult({
    test_id: "mcp-dyn-read_file-oversized-path-5",
    title: "read_file: a very large value in “path”",
    status: "inconclusive",
    severity: "medium",
  });
  const scanOf = (results: ReturnType<typeof makeResult>[], status: "running" | "completed" = "completed") =>
    makeScan(results, { id: 41, status });

  async function started(backend: FakeBackend) {
    const user = await looked(backend);
    await user.click(screen.getByRole("checkbox", { name: /test or sandbox, not production/ }));
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    return user;
  }

  it("streams each check as a row, marking whether it read a description or called a tool", async () => {
    const backend = new FakeBackend();
    backend.scans = [scanOf([staticPass, staticFail, callFail, callUnclear], "running")];
    await started(backend);
    expect(await screen.findByText("Tool descriptions: hidden instructions")).toBeInTheDocument();
    const rows = document.querySelectorAll(".rrow");
    expect(rows).toHaveLength(4);
    expect(within(rows[0] as HTMLElement).getByText("PASS")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("read")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("FAIL")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("called")).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText("UNCLEAR")).toBeInTheDocument();
    expect(screen.getByText(/4 tests done so far/)).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open the report" })).not.toBeInTheDocument();
  });

  it("ends with how many checks failed and a link to the report that carries the view key", async () => {
    const backend = new FakeBackend();
    backend.scans = [scanOf([staticPass, staticFail, callFail, callUnclear])];
    await started(backend);
    const link = await screen.findByRole("link", { name: "Open the report" });
    expect(link).toHaveAttribute("href", `/report/41?key=${VIEW_KEY}`);
    await waitFor(() => expect(screen.getByText(/checks failed\./)).toHaveTextContent("2 of 3 checks failed."));
    expect(screen.getByText(/1 was critical\./)).toBeInTheDocument();
    expect(screen.getByText("finished")).toBeInTheDocument();
    const reads = backend.calls.filter((c) => c.path === "/open-scans/41");
    expect(reads.every((c) => c.key === VIEW_KEY && !("X-Owner-Token" in c.headers))).toBe(true);
  });

  it("opens the report by itself after six seconds, unless the person stays", async () => {
    const backend = new FakeBackend();
    backend.scans = [scanOf([staticPass])];
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    backend.install();
    render(<McpPage apiUrl={API} pollMs={5} />);
    await user.type(address(), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    await screen.findByRole("list", { name: "Tools on this server" });
    await user.click(screen.getByRole("button", { name: "Untick all" }));
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await screen.findByText(/Opening in/);
    expect(push).not.toHaveBeenCalled();
    for (let second = 0; second < 7; second += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    expect(push).toHaveBeenCalledWith(`/report/41?key=${VIEW_KEY}`);
  });

  it("stays on the page when the person says so", async () => {
    const backend = new FakeBackend();
    backend.scans = [scanOf([staticPass])];
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    backend.install();
    render(<McpPage apiUrl={API} pollMs={5} />);
    await user.type(address(), "https://mcp.example.com/mcp");
    await user.click(screen.getByRole("button", { name: "Look at the tools" }));
    await screen.findByRole("list", { name: "Tools on this server" });
    await user.click(screen.getByRole("button", { name: "Untick all" }));
    await user.click(screen.getByRole("button", { name: "Run checks" }));
    await user.click(await screen.findByRole("button", { name: "Stay here" }));
    expect(screen.getByText("The report stays one click away.")).toBeInTheDocument();
    for (let second = 0; second < 8; second += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    expect(push).not.toHaveBeenCalled();
  });

  it.each([
    ["sandbox_required", /test or sandbox server/i, 422],
    ["unknown_tool", /not on the server/i, 422],
    ["scan_running", /already running/i, 409],
  ])("explains a refusal: %s", async (kind, words, status) => {
    const backend = new FakeBackend();
    backend.overrides["POST /mcp-scans"] = () => json(status, { error: { kind } });
    await started(backend);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(words));
  }, 20000);
});
