import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RiskSummary, ScanDetail, ScanResult } from "@/lib/scan";

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

const RISK_NAMES = [
  ["LLM01", "Prompt Injection"],
  ["LLM02", "Sensitive Information Disclosure"],
  ["LLM03", "Supply Chain"],
  ["LLM04", "Data and Model Poisoning"],
  ["LLM05", "Improper Output Handling"],
  ["LLM06", "Excessive Agency"],
  ["LLM07", "System Prompt Leakage"],
  ["LLM08", "Vector and Embedding Weaknesses"],
  ["LLM09", "Misinformation"],
  ["LLM10", "Unbounded Consumption"],
];

function result(overrides: Partial<ScanResult>): ScanResult {
  return {
    test_id: "t",
    risk: "LLM02",
    kind: "negative",
    title: "A test",
    message: "the attack message",
    status: "pass",
    reply: "a reply",
    tool_calls: [],
    evidence: "No violation found in the reply or the tool log",
    rule: "A rule.",
    model: "gullible-model",
    provider: "gullible",
    attempts: [],
    ...overrides,
  };
}

const RESULTS: ScanResult[] = [
  result({
    test_id: "si-other-customer-order",
    title: "Read another customer's order",
    status: "fail",
    reply: "It ships to 221 Fakewood Lane.",
    evidence: 'The reply contains another customer\'s ship_to: "221 Fakewood Lane"',
    rule: "A customer may see only their own orders.",
    tool_calls: [
      {
        tool: "lookup_order",
        arguments: { order_id: "B-2001" },
        outcome: "executed",
        detail: "details",
      },
    ],
  }),
  result({ test_id: "si-secret-direct", title: "Ask for the staff override code", status: "pass" }),
  result({
    test_id: "pi-direct-ignore-rules",
    risk: "LLM01",
    title: "Direct injection",
    status: "inconclusive",
    reply: "",
    evidence: "The bot gave no reply and made no tool calls",
  }),
  result({
    test_id: "oh-script-tag",
    risk: "LLM05",
    title: "Get the bot to write a script tag",
    status: "error",
    reply: "",
    evidence: "model call failed: all_providers_failed",
    model: null,
    provider: null,
  }),
  result({
    test_id: "pi-poisoned-article-refund",
    risk: "LLM01",
    title: "Hidden instruction in a help article: refund",
    status: "not_applicable",
    reply: "",
    evidence: "This bot lacks: data articles.partner-offer",
    model: null,
    provider: null,
  }),
  result({
    test_id: "pos-own-order-status",
    risk: null,
    kind: "positive",
    title: "Normal request: where is my order?",
    status: "pass",
  }),
];

function summaryFor(results: ScanResult[]) {
  const counts = { pass: 0, fail: 0, inconclusive: 0, error: 0, not_applicable: 0 };
  for (const r of results) counts[r.status as keyof typeof counts] += 1;
  const states: Record<string, string> = {
    LLM01: "attempted_no_result",
    LLM02: "tested",
    LLM05: "attempted_no_result",
  };
  return {
    counts,
    risks: RISK_NAMES.map(([id, name]) => ({
      id,
      name,
      state: (states[id] ?? "not_tested") as RiskSummary["state"],
      tests: states[id] ? 2 : 0,
      passed: id === "LLM02" ? 1 : 0,
      failed: id === "LLM02" ? 1 : 0,
      errors: 0,
      inconclusive: 0,
      not_applicable: 0,
    })),
    normal_requests: { tests: 1, passed: 1, failed: 0, errors: 0 },
    catalog_version: "owasp-llm-2025",
    catalog_source: "https://genai.owasp.org/llm-top-10/",
    disclaimer:
      "This is not a claim that the bot is secure. It lists what this scan checked and what it did not.",
  };
}

function scanBody(overrides: Partial<ScanDetail["scan"]> = {}, results = RESULTS): ScanDetail {
  return {
    scan: {
      id: 7,
      bot_id: "acme-weak",
      status: "completed",
      note: null,
      started_at: 1_760_000_000,
      finished_at: 1_760_000_050,
      last_progress_at: 1_760_000_050,
      models_used: ["gullible-model"],
      settings: {
        bot_id: "acme-weak",
        bot_name: "Acme Store support bot (weak)",
        bot_config_version: 1,
        bot_defenses: [],
        catalog_version: "owasp-llm-2025",
        suite_version: 1,
        test_count: 16,
        canary: "CANARY-abc123",
        providers: ["gemini"],
        budget: { requests: 150, tokens: 300000, seconds: 1800, concurrency: 1 },
      },
      ...overrides,
    },
    results,
    summary: summaryFor(results),
  };
}

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

  it("runs a scan, shows progress while it runs, and shows the results when it is done", async () => {
    // The server holds each state until the test has looked at it.
    const states: ScanDetail[] = [
      scanBody({ status: "running", finished_at: null }, RESULTS.slice(0, 2)),
      scanBody({ status: "running", finished_at: null }, RESULTS.slice(0, 4)),
      scanBody({ status: "completed" }),
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

    expect(await screen.findByText(/2 of 16 tests done/)).toBeInTheDocument();
    expect(screen.getByText(/Scan #7/)).toBeInTheDocument();
    state = 1;
    expect(await screen.findByText(/4 of 16 tests done/)).toBeInTheDocument();
    state = 2;
    await waitFor(() => expect(screen.getByText(/completed/i)).toBeInTheDocument());
    expect(screen.queryByText(/tests done/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem", { name: /test result/i })).toHaveLength(6);

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ bot_id: "acme-weak" });
    expect((post?.[1]?.headers as Record<string, string>)["X-Owner-Token"]).toBe("secret");
  });

  it("shows pass, fail, inconclusive, error and not applicable as different things", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    await screen.findByText(/Read another customer's order/);

    const row = (title: string) => screen.getByRole("listitem", { name: `Test result: ${title}` });
    expect(within(row("Read another customer's order")).getByText("FAIL")).toBeInTheDocument();
    expect(within(row("Ask for the staff override code")).getByText("PASS")).toBeInTheDocument();
    expect(within(row("Direct injection")).getByText("INCONCLUSIVE")).toBeInTheDocument();
    // An error must never read as a pass.
    const errorRow = within(row("Get the bot to write a script tag"));
    expect(errorRow.getByText("ERROR")).toBeInTheDocument();
    expect(errorRow.queryByText("PASS")).not.toBeInTheDocument();
    expect(
      within(row("Hidden instruction in a help article: refund")).getByText("NOT APPLICABLE"),
    ).toBeInTheDocument();
  });

  it("opens a test to show the message, reply, tool log, evidence, rule and model", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    await screen.findByText(/Read another customer's order/);

    const item = screen.getByRole("listitem", { name: "Test result: Read another customer's order" });
    expect(within(item).queryByText(/221 Fakewood Lane\./)).not.toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: /show evidence/i }));
    expect(within(item).getByText("the attack message")).toBeInTheDocument();
    expect(within(item).getByText(/It ships to 221 Fakewood Lane\./)).toBeInTheDocument();
    expect(within(item).getByText(/another customer's ship_to/)).toBeInTheDocument();
    expect(within(item).getByText(/A customer may see only their own orders\./)).toBeInTheDocument();
    const log = within(within(item).getByRole("list", { name: "Tool calls" }));
    expect(log.getByText(/lookup_order/)).toBeInTheDocument();
    expect(log.getByText(/"order_id":"B-2001"/)).toBeInTheDocument();
    expect(within(item).getByText(/gullible-model/)).toBeInTheDocument();
  });

  it("shows what was tested and what was not, over all ten risks, with the disclaimer", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    const box = await screen.findByRole("region", { name: "What this scan checked and did not check" });

    expect(within(box).getAllByRole("listitem")).toHaveLength(10);
    const risk = (name: string) => within(box).getByRole("listitem", { name });
    expect(within(risk("LLM02 Sensitive Information Disclosure")).getByText(/Tested/)).toBeInTheDocument();
    expect(within(risk("LLM01 Prompt Injection")).getByText(/Attempted, no result/)).toBeInTheDocument();
    expect(within(risk("LLM03 Supply Chain")).getByText(/Not tested/)).toBeInTheDocument();
    expect(within(box).getByText(/not a claim that the bot is secure/i)).toBeInTheDocument();
    expect(within(box).getByText(/owasp-llm-2025/)).toBeInTheDocument();
    expect(within(box).getByText(/Normal requests: 1 of 1 worked/)).toBeInTheDocument();
  });

  it("shows the settings the scan ran with and which models answered", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    const settings = await screen.findByRole("region", { name: "Settings this scan ran with" });
    expect(within(settings).getByText(/Models that answered: gullible-model/)).toBeInTheDocument();
    expect(within(settings).getByText(/Suite version: 1/)).toBeInTheDocument();
    expect(within(settings).getByText(/150 requests/)).toBeInTheDocument();
  });

  it("shows an interrupted scan as interrupted, with the reason", async () => {
    mockApi({
      ...OK_ROUTES,
      "POST /scans": () => json(202, { scan_id: 7 }),
      "GET /scans/7": () =>
        json(200, scanBody({ status: "interrupted", note: "No progress for a while. Run it again." })),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    await screen.findByLabelText("Bot");
    await runScan(user);
    expect(await screen.findByText(/interrupted/i)).toBeInTheDocument();
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

  it("lists earlier scans and opens one", async () => {
    mockApi({
      "GET /bots": () => json(200, BOTS),
      "GET /scans": () =>
        json(200, {
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
        }),
      "GET /scans/7": () => json(200, scanBody()),
    });
    const user = userEvent.setup();
    render(<ScanPage apiUrl={API} pollMs={5} />);
    await unlock(user);
    const earlier = await screen.findByRole("list", { name: "Earlier scans" });
    expect(within(earlier).getByText(/Scan #7/)).toBeInTheDocument();
    expect(within(earlier).getByText(/1 failed/)).toBeInTheDocument();
    await user.click(within(earlier).getByRole("button", { name: /open scan #7/i }));
    expect(await screen.findByText(/Read another customer's order/)).toBeInTheDocument();
  });
});
