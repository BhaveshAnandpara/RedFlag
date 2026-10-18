import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RouterTestPage } from "./router-test-page";

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

const PROVIDERS = {
  providers: [
    { name: "groq", configured: true, cooling_down: false, cooldown_seconds_left: 0 },
    { name: "gemini", configured: true, cooling_down: false, cooldown_seconds_left: 0 },
  ],
};

const BUDGET = {
  requests: { used: 1, limit: 50 },
  tokens: { used: 15, limit: 100000 },
  seconds: { used: 2, limit: 600 },
  concurrency: { limit: 2 },
};

function answer(overrides: Record<string, unknown> = {}) {
  return {
    answer: "Hi there!",
    provider: "groq",
    model: "llama-x",
    cached: false,
    paid: false,
    estimated_cost_usd: 0,
    usage: { input_tokens: 10, output_tokens: 5 },
    attempts: [{ provider: "groq", model: "llama-x", outcome: "ok", latency_ms: 120 }],
    budget: BUDGET,
    ...overrides,
  };
}

function headerOf(init: RequestInit, name: string): string | null {
  return new Headers(init.headers).get(name);
}

async function unlock(user: ReturnType<typeof userEvent.setup>, password = "secret-pw") {
  await user.type(screen.getByLabelText("Owner password"), password);
  await user.click(screen.getByRole("button", { name: "Unlock" }));
}

async function send(user: ReturnType<typeof userEvent.setup>, text = "hello") {
  await user.type(screen.getByLabelText("Message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  try {
    window.sessionStorage.clear();
  } catch {
    // storage can be unavailable; the page must work without it
  }
});

describe("RouterTestPage", () => {
  it("starts locked: only the password box is offered, nothing can be sent", () => {
    render(<RouterTestPage apiUrl={API} />);

    expect(screen.getByRole("heading", { name: /model router/i })).toBeInTheDocument();
    expect(screen.getByText(/locked/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Owner password")).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  });

  it("rejects a wrong password with a plain message and stays locked", async () => {
    mockApi({ "GET /llm/providers": () => json(401, { detail: "owner token required" }) });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user, "wrong");

    expect(await screen.findByText(/That password was not accepted/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();
  });

  it("unlocks with the right password and sends it with every request", async () => {
    const fetchMock = mockApi({
      "GET /llm/providers": () => json(200, PROVIDERS),
      "POST /llm/chat": () => json(200, answer()),
      "GET /llm/calls": () => json(200, { calls: [] }),
    });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user);
    await send(user, "hello");

    expect(await screen.findByText("Hi there!")).toBeInTheDocument();
    const chat = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/llm/chat"));
    expect(chat).toBeDefined();
    const init = chat![1] as RequestInit;
    expect(headerOf(init, "x-owner-token")).toBe("secret-pw");
    const body = JSON.parse(String(init.body));
    expect(body.messages).toEqual([{ role: "user", content: "hello" }]);
    expect(typeof body.session_id).toBe("string");
    expect(body.temperature).toBe(0);
  });

  it("shows which provider and model answered and that it was not from memory", async () => {
    mockApi({
      "GET /llm/providers": () => json(200, PROVIDERS),
      "POST /llm/chat": () => json(200, answer()),
      "GET /llm/calls": () => json(200, { calls: [] }),
    });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user);
    await send(user);

    const reply = (await screen.findByText("Hi there!")).closest("[data-role='assistant']");
    expect(reply).not.toBeNull();
    expect(within(reply as HTMLElement).getByText(/Answered by groq/)).toBeInTheDocument();
    expect(within(reply as HTMLElement).getByText(/llama-x/)).toBeInTheDocument();
    expect(within(reply as HTMLElement).getByText(/From memory: no/)).toBeInTheDocument();
  });
});

async function unlockAndSend(routes: Record<string, Route>) {
  mockApi({
    "GET /llm/providers": () => json(200, PROVIDERS),
    "GET /llm/calls": () => json(200, { calls: [] }),
    ...routes,
  });
  const user = userEvent.setup();
  render(<RouterTestPage apiUrl={API} />);
  await unlock(user);
  await send(user);
  return user;
}

describe("RouterTestPage results", () => {
  it("says when an answer came from memory", async () => {
    await unlockAndSend({ "POST /llm/chat": () => json(200, answer({ cached: true })) });

    expect(await screen.findByText(/From memory: yes/)).toBeInTheDocument();
  });

  it("labels an answer from a paid model with its estimated cost, and free ones not at all", async () => {
    await unlockAndSend({
      "POST /llm/chat": () => json(200, answer({ paid: true, estimated_cost_usd: 0.0123 })),
    });

    expect(await screen.findByText(/PAID/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.0123/)).toBeInTheDocument();
  });

  it("does not mention paid when the answer was free", async () => {
    await unlockAndSend({ "POST /llm/chat": () => json(200, answer()) });

    await screen.findByText("Hi there!");
    expect(screen.queryByText(/PAID/)).not.toBeInTheDocument();
  });

  it("shows the budget used so far", async () => {
    await unlockAndSend({ "POST /llm/chat": () => json(200, answer()) });

    expect(await screen.findByText(/Requests: 1 of 50/)).toBeInTheDocument();
    expect(screen.getByText(/Text used: 15 of 100,000 tokens/)).toBeInTheDocument();
    expect(screen.getByText(/Time: 2 of 600 seconds/)).toBeInTheDocument();
  });

  it("shows every attempt, so a switch between providers is visible", async () => {
    await unlockAndSend({
      "POST /llm/chat": () =>
        json(
          200,
          answer({
            provider: "gemini",
            attempts: [
              { provider: "groq", model: null, outcome: "rate_limited", latency_ms: 40 },
              { provider: "gemini", model: "gemini-x", outcome: "ok", latency_ms: 300 },
            ],
          }),
        ),
    });

    const log = await screen.findByRole("list", { name: "Attempts for the last request" });
    expect(within(log).getByText(/groq: rate_limited/)).toBeInTheDocument();
    expect(within(log).getByText(/gemini: ok/)).toBeInTheDocument();
    expect(screen.getByText(/Switched from groq to gemini/)).toBeInTheDocument();
  });

  it("explains a spent budget plainly and shows no answer", async () => {
    await unlockAndSend({
      "POST /llm/chat": () =>
        json(429, {
          error: { kind: "budget_exceeded", provider: null, cap: "tokens" },
          attempts: [],
          budget: BUDGET,
        }),
    });

    expect(await screen.findByText(/Budget reached \(tokens\)/)).toBeInTheDocument();
    expect(screen.queryByText("Hi there!")).not.toBeInTheDocument();
    expect(screen.queryByText(/Answered by/)).not.toBeInTheDocument();
  });

  it("says plainly that nothing was answered when every provider failed", async () => {
    await unlockAndSend({
      "POST /llm/chat": () =>
        json(503, {
          error: { kind: "all_providers_failed", provider: null },
          attempts: [
            { provider: "groq", model: null, outcome: "rate_limited", latency_ms: 10 },
            { provider: "gemini", model: null, outcome: "server_error", latency_ms: 12 },
          ],
          budget: BUDGET,
        }),
    });

    expect(await screen.findByText(/Every provider failed/)).toBeInTheDocument();
    expect(screen.getByText(/groq: rate_limited/)).toBeInTheDocument();
    expect(screen.getByText(/gemini: server_error/)).toBeInTheDocument();
  });

  it("points at the key when a provider rejects it", async () => {
    await unlockAndSend({
      "POST /llm/chat": () =>
        json(502, {
          error: { kind: "auth_error", provider: "groq" },
          attempts: [{ provider: "groq", model: null, outcome: "auth_error", latency_ms: 5 }],
          budget: BUDGET,
        }),
    });

    expect(await screen.findByText(/groq rejected its API key/)).toBeInTheDocument();
  });

  it("explains a network failure instead of hanging", async () => {
    await unlockAndSend({
      "POST /llm/chat": () => {
        throw new TypeError("Failed to fetch");
      },
    });

    expect(await screen.findByText(/Could not reach the backend/)).toBeInTheDocument();
  });
});

const MIXED_PROVIDERS = {
  providers: [
    { name: "groq", configured: true, cooling_down: false, cooldown_seconds_left: 0 },
    { name: "gemini", configured: true, cooling_down: true, cooldown_seconds_left: 20 },
    { name: "openrouter", configured: false, cooling_down: false, cooldown_seconds_left: 0 },
  ],
};

describe("RouterTestPage owner tools", () => {
  it("shows who is ready, cooling down, or has no key", async () => {
    mockApi({ "GET /llm/providers": () => json(200, MIXED_PROVIDERS) });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user);

    expect(await screen.findByText(/groq: ready/)).toBeInTheDocument();
    expect(screen.getByText(/gemini: cooling down \(20 s left\)/)).toBeInTheDocument();
    expect(screen.getByText(/openrouter: no key/)).toBeInTheDocument();
  });

  it("offers a pretend-out-of-quota button only for providers that have a key", async () => {
    mockApi({ "GET /llm/providers": () => json(200, MIXED_PROVIDERS) });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user);

    expect(await screen.findByRole("button", { name: "Pretend groq is out of quota" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pretend gemini is out of quota" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pretend openrouter/ })).not.toBeInTheDocument();
  });

  it("pretends a provider is out of quota for a minute, says so, and refreshes the status", async () => {
    let calls = 0;
    const fetchMock = mockApi({
      "GET /llm/providers": () => {
        calls += 1;
        return json(200, MIXED_PROVIDERS);
      },
      "POST /llm/test/fail": () => json(200, { provider: "groq", seconds: 60 }),
    });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);
    await unlock(user);

    await user.click(await screen.findByRole("button", { name: "Pretend groq is out of quota" }));

    expect(await screen.findByText(/Pretending groq is out of quota for 60 seconds/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/llm/test/fail"));
    const init = call![1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ provider: "groq", seconds: 60 });
    expect(headerOf(init, "x-owner-token")).toBe("secret-pw");
    expect(calls).toBeGreaterThanOrEqual(2); // unlocked once, then refreshed
  });

  it("clears the saved answers on request", async () => {
    const fetchMock = mockApi({
      "GET /llm/providers": () => json(200, PROVIDERS),
      "POST /llm/test/clear-cache": () => json(200, { cleared: true }),
    });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);
    await unlock(user);

    await user.click(await screen.findByRole("button", { name: "Clear memory" }));

    expect(await screen.findByText(/Memory cleared/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/llm/test/clear-cache"))).toBe(true);
  });

  it("never writes the password anywhere in the browser", async () => {
    mockApi({ "GET /llm/providers": () => json(200, PROVIDERS) });
    const user = userEvent.setup();
    render(<RouterTestPage apiUrl={API} />);

    await unlock(user, "very-secret-password");
    await screen.findByLabelText("Message");

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("very-secret-password");
  });
});
