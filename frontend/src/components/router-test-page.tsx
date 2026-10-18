"use client";

import { useRef, useState } from "react";

type ChatMessage = { role: "user" | "assistant"; content: string };

type Meta = {
  provider: string;
  model: string;
  cached: boolean;
  paid: boolean;
  costUsd: number;
};

type Entry = ChatMessage & { meta?: Meta };

type ProviderStatus = {
  name: string;
  configured: boolean;
  cooling_down: boolean;
  cooldown_seconds_left: number;
};

type Attempt = { provider: string; model: string | null; outcome: string; latency_ms: number };

type Budget = {
  requests: { used: number; limit: number };
  tokens: { used: number; limit: number };
  seconds: { used: number; limit: number };
};

const PRETEND_SECONDS = 60;

function newSessionId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `s-${Math.random().toString(36).slice(2)}`;
}

function describeProvider(provider: ProviderStatus): string {
  if (!provider.configured) return `${provider.name}: no key`;
  if (provider.cooling_down) {
    return `${provider.name}: cooling down (${provider.cooldown_seconds_left} s left)`;
  }
  return `${provider.name}: ready`;
}

/** Plain-language text for each way a request can fail. */
function describeFailure(status: number, body: { error?: { kind?: string; provider?: string; cap?: string } }) {
  if (status === 401) return "That password was not accepted.";
  const error = body.error ?? {};
  switch (error.kind) {
    case "budget_exceeded":
      return `Budget reached (${error.cap}). The session stopped cleanly and nothing was answered.`;
    case "all_providers_failed":
      return "Every provider failed, so nothing was answered.";
    case "no_provider_configured":
      return "No provider is configured. Add an API key in the backend settings.";
    case "auth_error":
      return `${error.provider} rejected its API key. Check the key in the backend settings.`;
    case "bad_request":
      return "The request was rejected as invalid.";
    default:
      return "Something went wrong, and nothing was answered.";
  }
}

function switchNotice(attempts: Attempt[]): string | null {
  const answered = attempts.find((a) => a.outcome === "ok");
  const failed = attempts.filter((a) => a.outcome !== "ok" && a.outcome !== "cache_hit");
  if (!answered || failed.length === 0) return null;
  return `Switched from ${failed[0].provider} to ${answered.provider}`;
}

export function RouterTestPage({ apiUrl }: { apiUrl: string }) {
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [budget, setBudget] = useState<Budget | null>(null);
  // Made on first send, not while rendering: the page is pre-rendered, so an id made during
  // rendering would be frozen into the page and shared by every visitor.
  const sessionId = useRef<string | null>(null);

  async function unlock() {
    setProblem(null);
    try {
      const response = await fetch(`${apiUrl}/llm/providers`, {
        headers: { "X-Owner-Token": password },
      });
      if (response.status === 401) {
        setProblem("That password was not accepted.");
        return;
      }
      if (!response.ok) {
        setProblem("The backend answered with an error. Try again in a moment.");
        return;
      }
      const body = await response.json();
      setProviders(body.providers);
      // Held in memory only: never stored in the browser and never put in a URL.
      setToken(password);
    } catch {
      setProblem("Could not reach the backend. It may still be waking up.");
    }
  }

  async function refreshProviders(activeToken: string) {
    try {
      const response = await fetch(`${apiUrl}/llm/providers`, {
        headers: { "X-Owner-Token": activeToken },
      });
      if (response.ok) setProviders((await response.json()).providers);
    } catch {
      // The status line is a convenience; a failed refresh just leaves the old one.
    }
  }

  async function pretendOutOfQuota(name: string) {
    if (!token) return;
    setNotice(null);
    try {
      const response = await fetch(`${apiUrl}/llm/test/fail`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Owner-Token": token },
        body: JSON.stringify({ provider: name, seconds: PRETEND_SECONDS }),
      });
      if (!response.ok) {
        setProblem("The pretend failure was not accepted.");
        return;
      }
      setNotice(`Pretending ${name} is out of quota for ${PRETEND_SECONDS} seconds.`);
      await refreshProviders(token);
    } catch {
      setProblem("Could not reach the backend. It may still be waking up.");
    }
  }

  async function clearMemory() {
    if (!token) return;
    setNotice(null);
    try {
      const response = await fetch(`${apiUrl}/llm/test/clear-cache`, {
        method: "POST",
        headers: { "X-Owner-Token": token },
      });
      setNotice(response.ok ? "Memory cleared." : "Could not clear the memory.");
    } catch {
      setProblem("Could not reach the backend. It may still be waking up.");
    }
  }

  async function send() {
    if (!token || !draft.trim()) return;
    const history: ChatMessage[] = [
      ...entries.map(({ role, content }) => ({ role, content })),
      { role: "user", content: draft },
    ];
    setEntries([...entries, { role: "user", content: draft }]);
    setDraft("");
    setProblem(null);
    sessionId.current ??= newSessionId();

    let response: Response;
    try {
      response = await fetch(`${apiUrl}/llm/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Owner-Token": token },
        body: JSON.stringify({
          messages: history,
          session_id: sessionId.current,
          temperature: 0,
        }),
      });
    } catch {
      setProblem("Could not reach the backend. It may still be waking up.");
      return;
    }

    const body = await response.json();
    setAttempts(body.attempts ?? []);
    if (body.budget) setBudget(body.budget);

    if (!response.ok) {
      setProblem(describeFailure(response.status, body));
      return;
    }
    setEntries((current) => [
      ...current,
      {
        role: "assistant",
        content: body.answer,
        meta: {
          provider: body.provider,
          model: body.model,
          cached: body.cached,
          paid: body.paid,
          costUsd: body.estimated_cost_usd,
        },
      },
    ]);
  }

  const switched = switchNotice(attempts);

  return (
    <section className="space-y-6">
      <h1 className="text-3xl font-semibold">Model router test page</h1>

      {token === null ? (
        <div className="space-y-3">
          <p>Locked: enter the owner password to use this page.</p>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">Owner password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded border-2 border-zinc-500 bg-white p-2 text-black"
            />
          </label>
          <button
            type="button"
            onClick={unlock}
            className="rounded bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-black"
          >
            Unlock
          </button>
          {problem && <p role="alert">{problem}</p>}
        </div>
      ) : (
        <div className="space-y-4">
          <ul className="space-y-3">
            {entries.map((entry, index) => (
              <li key={index} data-role={entry.role} className="rounded border-2 p-3">
                <p className="text-xs font-semibold uppercase">
                  {entry.role === "user" ? "You" : "Answer"}
                </p>
                <p>{entry.content}</p>
                {entry.meta && (
                  <div className="mt-2 text-sm">
                    <p>
                      Answered by {entry.meta.provider} · model {entry.meta.model}
                    </p>
                    <p>From memory: {entry.meta.cached ? "yes" : "no"}</p>
                    {entry.meta.paid && (
                      <p className="font-semibold">
                        PAID · estimated cost ${entry.meta.costUsd.toFixed(4)}
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>

          {problem && <p role="alert">{problem}</p>}
          {notice && <p role="status">{notice}</p>}

          <label className="block space-y-1">
            <span className="block text-sm font-medium">Message</span>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="w-full rounded border-2 border-zinc-500 bg-white p-2 text-black"
            />
          </label>
          <button
            type="button"
            onClick={send}
            className="rounded bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-black"
          >
            Send
          </button>

          <div className="space-y-2 rounded border-2 p-3 text-sm">
            <h2 className="font-semibold">Providers and test tools</h2>
            <ul aria-label="Provider status">
              {providers.map((provider) => (
                <li key={provider.name}>{describeProvider(provider)}</li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              {providers
                .filter((provider) => provider.configured)
                .map((provider) => (
                  <button
                    key={provider.name}
                    type="button"
                    onClick={() => pretendOutOfQuota(provider.name)}
                    className="rounded border-2 px-3 py-1"
                  >
                    Pretend {provider.name} is out of quota
                  </button>
                ))}
              <button type="button" onClick={clearMemory} className="rounded border-2 px-3 py-1">
                Clear memory
              </button>
            </div>
          </div>

          {budget && (
            <div className="space-y-1 rounded border-2 p-3 text-sm">
              <h2 className="font-semibold">Budget for this session</h2>
              <p>
                Requests: {budget.requests.used} of {budget.requests.limit}
              </p>
              <p>
                Text used: {budget.tokens.used.toLocaleString("en-US")} of{" "}
                {budget.tokens.limit.toLocaleString("en-US")} tokens
              </p>
              <p>
                Time: {budget.seconds.used} of {budget.seconds.limit} seconds
              </p>
            </div>
          )}

          {attempts.length > 0 && (
            <div className="space-y-1 rounded border-2 p-3 text-sm">
              <h2 className="font-semibold">Last request</h2>
              {switched && <p className="font-semibold">{switched}</p>}
              <ul aria-label="Attempts for the last request">
                {attempts.map((attempt, index) => (
                  <li key={index}>
                    {attempt.provider}: {attempt.outcome}
                    {attempt.model ? ` · ${attempt.model}` : ""} · {attempt.latency_ms} ms
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
