"use client";

import { useEffect, useRef, useState } from "react";

import type { BotInfo, ScanDetail, ScanListItem, ScanResult, Status } from "@/lib/scan";

const STATUS_LABEL: Record<Status, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "INCONCLUSIVE",
  error: "ERROR",
  not_applicable: "NOT APPLICABLE",
};

const UNREACHABLE = "Could not reach the backend. It may still be waking up.";

function startProblem(status: number, kind?: string): string {
  if (status === 401) return "That password was not accepted.";
  switch (kind) {
    case "scan_running":
      return "A scan is already running. Wait for it to finish, then try again.";
    case "no_provider_configured":
      return "No model is configured for the bots. Add the BOT_ keys in the backend settings.";
    case "unknown_bot":
      return "There is no such bot.";
    default:
      return "The scan could not be started.";
  }
}

function when(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function ResultItem({ result }: { result: ScanResult }) {
  const [open, setOpen] = useState(false);
  return (
    <li aria-label={`Test result: ${result.title}`} className="space-y-2 rounded border-2 p-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-semibold">{STATUS_LABEL[result.status]}</span>
        <span>{result.title}</span>
        <span className="text-xs">{result.risk ?? "normal request"}</span>
      </div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="rounded border-2 px-3 py-1 text-sm"
      >
        {open ? "Hide evidence" : "Show evidence"}
      </button>
      {open && (
        <div className="space-y-2 text-sm">
          <div>
            <p className="text-xs font-semibold uppercase">Message sent</p>
            <p className="whitespace-pre-wrap">{result.message}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase">Reply</p>
            <p className="whitespace-pre-wrap">{result.reply || "(no reply)"}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase">What the bot did (tool-call log)</p>
            {result.tool_calls.length === 0 ? (
              <p>No tools were called.</p>
            ) : (
              <ul aria-label="Tool calls" className="space-y-1">
                {result.tool_calls.map((call, index) => (
                  <li key={index} className="break-words">
                    <span className="font-mono font-semibold">{call.tool}</span>{" "}
                    <span className="font-mono">{JSON.stringify(call.arguments)}</span>
                    {" → "}
                    <span className="font-semibold">{call.outcome}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="text-xs font-semibold uppercase">Evidence</p>
            <p>{result.evidence}</p>
          </div>
          <p>
            <span className="font-semibold">Rule:</span> {result.rule}
          </p>
          <p>
            {result.model
              ? `Answered by ${result.provider} (${result.model})`
              : "No model answered this test."}
          </p>
        </div>
      )}
    </li>
  );
}

function riskState(state: string, passed: number, failed: number, tests: number): string {
  if (state === "tested") return `Tested: ${passed} passed, ${failed} failed`;
  if (state === "attempted_no_result") {
    return `Attempted, no result (${tests} test${tests === 1 ? "" : "s"} ended in error, inconclusive or not applicable)`;
  }
  return "Not tested";
}

function ScanView({ detail }: { detail: ScanDetail }) {
  const { scan, results, summary } = detail;
  const { settings } = scan;
  const counts = summary.counts;
  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold">Scan #{scan.id}</h2>
        <p>
          {settings.bot_name} · Status: {scan.status} · Started {when(scan.started_at)}
        </p>
        {scan.status === "running" && (
          <p>
            {results.length} of {settings.test_count} tests done
          </p>
        )}
        {scan.note && <p>{scan.note}</p>}
        <p className="text-sm">
          {counts.pass} passed · {counts.fail} failed · {counts.inconclusive} inconclusive ·{" "}
          {counts.error} errors · {counts.not_applicable} not applicable
        </p>
      </header>

      <ul aria-label="Test results" className="space-y-3">
        {results.map((result) => (
          <ResultItem key={result.test_id} result={result} />
        ))}
      </ul>

      <section
        aria-label="What this scan checked and did not check"
        className="space-y-2 rounded border-2 p-4"
      >
        <h3 className="font-semibold">What this scan checked and did not check</h3>
        <ul className="space-y-1 text-sm">
          {summary.risks.map((risk) => (
            <li key={risk.id} aria-label={`${risk.id} ${risk.name}`}>
              <span className="font-semibold">
                {risk.id} {risk.name}
              </span>
              {": "}
              <span>{riskState(risk.state, risk.passed, risk.failed, risk.tests)}</span>
            </li>
          ))}
        </ul>
        <p className="text-sm">
          Normal requests: {summary.normal_requests.passed} of {summary.normal_requests.tests}{" "}
          worked
        </p>
        <p className="text-sm">Risk list used: {summary.catalog_version}</p>
        <p className="font-semibold">{summary.disclaimer}</p>
      </section>

      <section aria-label="Settings this scan ran with" className="space-y-1 rounded border-2 p-4 text-sm">
        <h3 className="font-semibold">Settings this scan ran with</h3>
        <p>
          Bot: {settings.bot_name} (config version {settings.bot_config_version}) · Defenses on:{" "}
          {settings.bot_defenses.length > 0 ? settings.bot_defenses.join(", ") : "none"}
        </p>
        <p>Models that answered: {scan.models_used.length > 0 ? scan.models_used.join(", ") : "none"}</p>
        <p>
          Suite version: {settings.suite_version} · Tests: {settings.test_count}
        </p>
        <p>
          Budget: up to {settings.budget.requests} requests and{" "}
          {settings.budget.tokens.toLocaleString("en-US")} tokens
        </p>
        <p>Secret planted for this scan: {settings.canary}</p>
      </section>
    </div>
  );
}

export function ScanPage({ apiUrl, pollMs = 2000 }: { apiUrl: string; pollMs?: number }) {
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [bots, setBots] = useState<BotInfo[]>([]);
  const [botId, setBotId] = useState("");
  const [earlier, setEarlier] = useState<ScanListItem[]>([]);
  const [detail, setDetail] = useState<ScanDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const stopped = useRef(false);

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
    };
  }, []);

  async function loadEarlier(activeToken: string) {
    try {
      const response = await fetch(`${apiUrl}/scans`, { headers: { "X-Owner-Token": activeToken } });
      if (response.ok) setEarlier((await response.json()).scans);
    } catch {
      // The list of earlier scans is a convenience; a failed refresh just leaves the old one.
    }
  }

  async function unlock() {
    setProblem(null);
    try {
      const response = await fetch(`${apiUrl}/bots`, { headers: { "X-Owner-Token": password } });
      if (response.status === 401) {
        setProblem("That password was not accepted.");
        return;
      }
      if (!response.ok) {
        setProblem("The backend answered with an error. Try again in a moment.");
        return;
      }
      const body = await response.json();
      setBots(body.bots);
      setBotId(body.bots[0]?.id ?? "");
      // Held in memory only: never stored in the browser and never put in a URL.
      setToken(password);
      await loadEarlier(password);
    } catch {
      setProblem(UNREACHABLE);
    }
  }

  // Ask for the scan until it stops running, like a progress bar that checks in.
  async function follow(scanId: number, activeToken: string) {
    setBusy(true);
    try {
      while (!stopped.current) {
        const response = await fetch(`${apiUrl}/scans/${scanId}`, {
          headers: { "X-Owner-Token": activeToken },
        });
        if (!response.ok) {
          setProblem(startProblem(response.status));
          return;
        }
        const body: ScanDetail = await response.json();
        setDetail(body);
        if (body.scan.status !== "running") {
          await loadEarlier(activeToken);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
    } catch {
      setProblem(UNREACHABLE);
    } finally {
      setBusy(false);
    }
  }

  async function runScan() {
    if (!token || !botId) return;
    setProblem(null);
    setDetail(null);
    let response: Response;
    try {
      response = await fetch(`${apiUrl}/scans`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Owner-Token": token },
        body: JSON.stringify({ bot_id: botId }),
      });
    } catch {
      setProblem(UNREACHABLE);
      return;
    }
    if (response.status !== 202) {
      const body = await response.json().catch(() => ({}));
      setProblem(startProblem(response.status, body?.error?.kind));
      return;
    }
    await follow((await response.json()).scan_id, token);
  }

  async function openScan(scanId: number) {
    if (!token) return;
    setProblem(null);
    await follow(scanId, token);
  }

  return (
    <section className="space-y-6">
      <h1 className="text-3xl font-semibold">Scan</h1>

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
        <div className="space-y-6">
          <div className="space-y-3">
            <label className="block space-y-1">
              <span className="block text-sm font-medium">Bot</span>
              <select
                value={botId}
                onChange={(event) => setBotId(event.target.value)}
                className="w-full rounded border-2 border-zinc-500 bg-white p-2 text-black"
              >
                {bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>
                    {bot.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={runScan}
              disabled={busy}
              className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-black"
            >
              Run scan
            </button>
            {problem && <p role="alert">{problem}</p>}
          </div>

          {detail && <ScanView detail={detail} />}

          {earlier.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-lg font-semibold">Earlier scans</h2>
              <ul aria-label="Earlier scans" className="space-y-2">
                {earlier.map((scan) => (
                  <li key={scan.id} className="flex flex-wrap items-baseline gap-3 rounded border-2 p-3">
                    <span>
                      Scan #{scan.id} · {scan.bot_id} · {scan.status} · {scan.counts.fail} failed
                    </span>
                    <button
                      type="button"
                      aria-label={`Open scan #${scan.id}`}
                      onClick={() => openScan(scan.id)}
                      className="rounded border-2 px-3 py-1 text-sm"
                    >
                      Open
                    </button>
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
