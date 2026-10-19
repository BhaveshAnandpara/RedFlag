import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScanDetail } from "@/lib/scan";
import { makeResult, makeScan } from "@/test-support/fixtures";

import { ScanPage } from "./scan-page";

const API = "https://api.example.test";

type Route = (init: RequestInit) => Response | Promise<Response>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockApi(routes: Record<string, Route>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const key = `${init.method ?? "GET"} ${url.pathname}`;
    const route = routes[key];
    if (!route) throw new Error(`unexpected request: ${key}`);
    return route(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const BOTS = {
  bots: [
    {
      id: "acme-weak",
      name: "Acme Store support bot (weak)",
      description: "No protection.",
      defenses: [],
      config_version: 1,
    },
    {
      id: "acme-hardened",
      name: "Acme Store support bot (hardened)",
      description: "Defenses on.",
      defenses: ["order_scoping"],
      config_version: 1,
    },
  ],
  errors: {},
};

const RESULTS = [
  makeResult({
    test_id: "si-other-customer-order",
    title: "Read another customer's order",
    status: "fail",
    severity: "critical",
  }),
  makeResult({ test_id: "si-secret-direct", title: "Ask for the staff override code", status: "pass" }),
  makeResult({
    test_id: "oh-script-tag",
    title: "Get the bot to write a script tag",
    status: "error",
    model: null,
    provider: null,
  }),
  makeResult({
    test_id: "pos-own-order-status",
    risk: null,
    kind: "positive",
    severity: null,
    title: "Normal request: where is my order?",
    status: "pass",
  }),
];

function scanBody(
  overrides: Partial<ScanDetail["scan"]> = {},
  results = RESULTS,
  status: "running" | "completed" | "interrupted" = "completed",
): ScanDetail {
  const detail = makeScan(results, { id: 7, status });
  return { ...detail, scan: { ...detail.scan, ...overrides } };
}

const EARLIER = {
  scans: [
    {
      id: 7,
      bot_id: "acme-weak",
      status: "completed",
      started_at: 1_760_000_000,
      finished_at: 1_760_000_050,
      counts: { pass: 3, fail: 1, inconclusive: 1, error: 1, not_applicable: 1 },
    },
  ],
};

const OK_ROUTES = {
  "GET /bots": () => json(200, BOTS),
  "GET /scans": () => json(200, { scans: [] }),
};

async function unlock(user: ReturnType<typeof userEvent.setup>, password = "secret") {
  await user.type(screen.getByLabelText("Owner password"), password);
  await user.click(screen.getByRole("button", { name: "Unlock" }));
}

async function runScan(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText("Bot"), "acme-weak");
  await user.click(screen.getByRole("button", { name: "Run scan" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Scan page", () => {
  it("is locked, and sends nothing, until the owner password is accepted", async () => {
    const fetchMock = mockApi({ ...OK_ROUTES, "GET /bots": () => json(401, { detail: "no" }) });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    expect(screen.getByText(/locked/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await unlock(user, "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent("That password was not accepted.");
    expect(screen.queryByRole("button", { name: "Run scan" })).not.toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>)["X-Owner-Token"]).toBe("wrong");
  });

  it("unlocks, lists the bots, and never stores the password in the browser", async () => {
    mockApi(OK_ROUTES);
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    const bots = await screen.findByLabelText("Bot");
    expect(within(bots).getByText("Acme Store support bot (weak)")).toBeInTheDocument();
    expect(within(bots).getByText("Acme Store support bot (hardened)")).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("runs a scan, shows progress while it runs, and opens the dashboard when it is done", async () => {
    // The server holds each state until the test has looked at it.
    const states: ScanDetail[] = [
      scanBody({ finished_at: null }, RESULTS.slice(0, 1), "running"),
      scanBody({ finished_at: null }, RESULTS.slice(0, 3), "running"),
      scanBody(),
    ];
    let state = 0;
    const fetchMock = mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, states[state]),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);

    expect(await screen.findByText(/1 of 16 tests done/)).toBeInTheDocument();
    expect(screen.getByText(/Scan #7/)).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument(); // no dashboard until it is done
    state = 1;
    expect(await screen.findByText(/3 of 16 tests done/)).toBeInTheDocument();
    state = 2;
    expect(await screen.findByRole("tablist", { name: "Scan results" })).toBeInTheDocument();
    expect(screen.getByTestId("conclusion")).toBeInTheDocument();
    expect(screen.queryByText(/tests done/)).not.toBeInTheDocument();

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ bot_id: "acme-weak" });
    expect((post?.[1]?.headers as Record<string, string>)["X-Owner-Token"]).toBe("secret");
  });

  it("says a free-tier wait may be the reason when no new result arrives for a while", async () => {
    let state = 0;
    const states: ScanDetail[] = [
      scanBody({ finished_at: null }, RESULTS.slice(0, 1), "running"),
      scanBody({ finished_at: null }, RESULTS.slice(0, 2), "running"),
    ];
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, states[state]),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} noResultNoteMs={40} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);

    expect(await screen.findByText(/1 of 16 tests done/)).toBeInTheDocument();
    expect(screen.queryByText(/waiting for a free-tier limit/i)).not.toBeInTheDocument();
    expect(await screen.findByText(/No new result yet\. It may be waiting for a free-tier limit/)).toBeInTheDocument();
    state = 1; // a result arrives, so the note goes away
    expect(await screen.findByText(/2 of 16 tests done/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/No new result yet/)).not.toBeInTheDocument(),
    );
  });

  it("shows an interrupted scan on the dashboard, with the reason", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () =>
        json(
          200,
          scanBody({ status: "interrupted", note: "No progress for a while. Run it again." }),
        ),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    expect(await screen.findByText(/Status: interrupted/)).toBeInTheDocument();
    expect(screen.getByText(/No progress for a while/)).toBeInTheDocument();
  });

  it("explains plainly why a scan could not start", async () => {
    const cases: [number, string, RegExp][] = [
      [409, "scan_running", /already running/i],
      [503, "no_provider_configured", /no model is configured for the bots/i],
      [404, "unknown_bot", /no such bot/i],
    ];
    for (const [status, kind, message] of cases) {
      mockApi({ ...OK_ROUTES, "POST /scans": () => json(status, { error: { kind } }) });
      const user = userEvent.setup();
      const { unmount } = render(<ScanPage apiUrl={API} pollMs={5} />);
      await unlock(user);
      await screen.findByLabelText("Bot");
      await runScan(user);
      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      unmount();
    }
  });

  it("says when the backend cannot be reached", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network down");
      }),
    );
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the backend/i);
  });

  it("lists earlier scans before one is open, and opens one on the dashboard", async () => {
    mockApi({
      "GET /bots": () => json(200, BOTS),
      "GET /scans": () => json(200, EARLIER),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    const earlier = await screen.findByRole("list", { name: "Earlier scans" });
    expect(within(earlier).getByText(/Scan #7/)).toBeInTheDocument();
    expect(within(earlier).getByText(/1 failed/)).toBeInTheDocument();
    await user.click(within(earlier).getByRole("button", { name: /open scan #7/i }));
    expect(await screen.findByRole("tablist", { name: "Scan results" })).toBeInTheDocument();
    expect(screen.getByTestId("conclusion")).toBeInTheDocument();
  });

  it("uses the same password to compare with another scan from the dashboard", async () => {
    const other = makeScan(RESULTS.slice(1), { id: 8, botId: "acme-hardened" });
    const fetchMock = mockApi({
      "GET /bots": () => json(200, BOTS),
      "GET /scans": () =>
        json(200, {
          scans: [
            ...EARLIER.scans,
            { ...EARLIER.scans[0], id: 8, bot_id: "acme-hardened", counts: { ...EARLIER.scans[0].counts, fail: 0 } },
          ],
        }),
      "GET /scans/7": () => json(200, scanBody()),
      "GET /scans/8": () => json(200, other),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    const earlier = await screen.findByRole("list", { name: "Earlier scans" });
    await user.click(within(earlier).getByRole("button", { name: /open scan #7/i }));
    await user.click(await screen.findByRole("tab", { name: "Compare" }));
    await user.selectOptions(screen.getByLabelText("Compare with"), "8");
    expect(await screen.findByText(/The same model answered both scans/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/scans/8"));
    expect((call?.[1]?.headers as Record<string, string>)["X-Owner-Token"]).toBe("secret");
  });
});
