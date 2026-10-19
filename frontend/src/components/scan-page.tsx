"use client";

import { useEffect, useRef, useState } from "react";

import type { BotInfo, ScanDetail, ScanListItem } from "@/lib/scan";

import { Dashboard } from "./dashboard";
import { StatusBadge } from "./status";

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

function RunningView({ detail, waiting }: { detail: ScanDetail; waiting: boolean }) {
  const { scan, results } = detail;
  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">Scan #{scan.id}</h2>
      <p>{scan.settings.bot_name} · Status: running</p>
      <p>
        {results.length} of {scan.settings.test_count} tests done
      </p>
      {waiting && (
        <p role="status">
          No new result yet. It may be waiting for a free-tier limit to clear, so it can take a
          little longer.
        </p>
      )}
      {results.length > 0 && (
        <ul aria-label="Results so far" className="space-y-2 text-sm">
          {results.map((result) => (
            <li key={result.test_id} className="flex flex-wrap items-baseline gap-3">
              <StatusBadge status={result.status} />
              <span>{result.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ScanPage({
  apiUrl,
  pollMs = 2000,
  noResultNoteMs = 30_000,
}: {
  apiUrl: string;
  pollMs?: number;
  noResultNoteMs?: number;
}) {
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [bots, setBots] = useState<BotInfo[]>([]);
  const [botId, setBotId] = useState("");
  const [earlier, setEarlier] = useState<ScanListItem[]>([]);
  const [detail, setDetail] = useState<ScanDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
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

  async function fetchScan(scanId: number, activeToken: string): Promise<ScanDetail> {
    const response = await fetch(`${apiUrl}/scans/${scanId}`, {
      headers: { "X-Owner-Token": activeToken },
    });
    if (!response.ok) throw new Error(`scan request failed with ${response.status}`);
    return response.json();
  }

  // Ask for the scan until it stops running, like a progress bar that checks in.
  async function follow(scanId: number, activeToken: string) {
    setBusy(true);
    setWaiting(false);
    let lastCount = -1;
    let lastChange = Date.now();
    try {
      while (!stopped.current) {
        const body = await fetchScan(scanId, activeToken);
        setDetail(body);
        if (body.scan.status !== "running") {
          setWaiting(false);
          await loadEarlier(activeToken);
          return;
        }
        if (body.results.length !== lastCount) {
          lastCount = body.results.length;
          lastChange = Date.now();
          setWaiting(false);
        } else if (Date.now() - lastChange >= noResultNoteMs) {
          setWaiting(true);
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

          {detail &&
            (detail.scan.status === "running" ? (
              <RunningView detail={detail} waiting={waiting} />
            ) : (
              <Dashboard
                detail={detail}
                history={earlier}
                onOpen={openScan}
                loadScan={(scanId) => fetchScan(scanId, token)}
              />
            ))}

          {!detail && earlier.length > 0 && (
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
