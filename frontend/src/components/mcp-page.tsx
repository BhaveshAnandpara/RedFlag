"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { hostOf, problemFor, readOpenScan, reportPath } from "@/lib/open-api";
import { mcpGroup } from "@/lib/report-model";
import type { ScanDetail } from "@/lib/scan";
import { SetupApi } from "@/lib/setup-api";

import { CountUp } from "./design/count-up";
import { FlagStrip, lookOf } from "./design/flags";
import { Step, type StepState } from "./design/step";

type Effect = "reads" | "changes";
type Tool = {
  name: string;
  description: string;
  params: string[];
  on: boolean;
  effect: Effect;
};
type Listing = {
  server: { name: string; version: string };
  tools: { name: string; description: string; params: string[]; effect_hint: "reads" | "unknown" }[];
};
type Filter = "all" | "ticked" | "reads" | "changes";

const PRIVATE = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|0\.0\.0\.0|\[?::1\]?)/i;
const SANDBOX_REQUIRED =
  "A tool that changes things can only be called on a test or sandbox server. Tick the box to confirm that this is one.";

/** The same refusals the backend gives for a bad address, caught before anything is sent. */
export function urlProblem(value: string): string {
  if (!value) return "Enter the server address.";
  let host: string;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:") return "Use a public https address.";
    host = parsed.hostname;
  } catch {
    return "Enter the full address, starting with https://.";
  }
  if (PRIVATE.test(host)) return "That address is not allowed: it points to a private or internal address.";
  return "";
}

const BADGE: Record<string, [string, string]> = {
  pass: ["pass", "PASS"],
  fail: ["fail", "FAIL"],
  inconclusive: ["unclear", "UNCLEAR"],
  not_applicable: ["na", "N/A"],
  error: ["na", "ERROR"],
};

/** Refusals the MCP page words its own way, then the plain words every open page shares. */
function refusal(status: number, body: unknown): string {
  const kind = (body as { error?: { kind?: string } } | null)?.error?.kind;
  if (kind === "sandbox_required") return SANDBOX_REQUIRED;
  if (kind === "unknown_tool") return "One of those tools is not on the server any more. Look at the tools again.";
  return problemFor(status, body);
}

export function McpPage({ apiUrl, pollMs = 2000 }: { apiUrl: string; pollMs?: number }) {
  // No password: the backend answers these calls openly. A scan is read back with the secret view
  // key that starting it returned, kept only here in memory.
  const api = useMemo(() => new SetupApi(apiUrl, ""), [apiUrl]);
  const router = useRouter();
  const [stage, setStage] = useState<1 | 2 | 3>(1);

  const [url, setUrl] = useState("");
  // The key lives only here, in memory: sent with the look and the run, never stored.
  const [key, setKey] = useState("");
  const [headerName, setHeaderName] = useState("Authorization");
  const [headerPrefix, setHeaderPrefix] = useState("Bearer ");
  const [attemptedLook, setAttemptedLook] = useState(false);
  const [looking, setLooking] = useState(false);
  const [lookProblem, setLookProblem] = useState<string | null>(null);
  const [serverName, setServerName] = useState("");
  const [tools, setTools] = useState<Tool[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [attemptedRun, setAttemptedRun] = useState(false);
  const [runProblem, setRunProblem] = useState<string | null>(null);

  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [scanProblem, setScanProblem] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const viewKey = useRef("");
  const [viewKeyShown, setViewKeyShown] = useState("");
  const stopped = useRef(false);
  const streamRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
    };
  }, []);

  // ---------- step 1 ----------
  const address = url.trim();
  const showUrlError = attemptedLook ? urlProblem(address) : "";
  const server = () => ({
    url: address,
    key: key || null,
    header_name: headerName.trim() || "Authorization",
    header_prefix: headerPrefix,
  });

  async function look() {
    setAttemptedLook(true);
    if (urlProblem(address)) {
      document.getElementById("url")?.focus();
      return;
    }
    setLooking(true);
    setLookProblem(null);
    const result = await api.call<Listing>("POST", "/mcp-scans/check", server());
    setLooking(false);
    if (!result.ok) {
      setLookProblem(problemFor(result.status, result.data));
      return;
    }
    setServerName(result.data.server.name);
    setTools(
      result.data.tools.map((t) => ({
        name: t.name,
        description: t.description,
        params: t.params,
        on: true,
        // Only a tool the server itself calls read-only starts as "only reads".
        effect: t.effect_hint === "reads" ? "reads" : "changes",
      })),
    );
    setSandbox(false);
    setAttemptedRun(false);
    setStage(2);
  }

  // ---------- step 2 ----------
  const ticked = tools.filter((t) => t.on);
  const risky = ticked.some((t) => t.effect === "changes");
  const sandboxError = attemptedRun && risky && !sandbox ? SANDBOX_REQUIRED : "";
  const needle = query.toLowerCase();
  const shown = tools.filter(
    (t) =>
      (filter === "all" || (filter === "ticked" ? t.on : t.effect === filter)) &&
      (!needle || t.name.toLowerCase().includes(needle) || t.description.toLowerCase().includes(needle)),
  );
  const count = {
    all: tools.length,
    ticked: ticked.length,
    reads: tools.filter((t) => t.effect === "reads").length,
    changes: tools.filter((t) => t.effect === "changes").length,
  };
  const allOn = tools.length > 0 && tools.every((t) => t.on);
  const update = (name: string, change: Partial<Tool>) =>
    setTools(tools.map((t) => (t.name === name ? { ...t, ...change } : t)));

  async function run() {
    setAttemptedRun(true);
    if (risky && !sandbox) {
      document.getElementById("sandbox")?.focus();
      return;
    }
    setRunProblem(null);
    const started = await api.call<{ scan_id: number; view_key: string }>("POST", "/mcp-scans", {
      ...server(),
      exercise: ticked.map((t) => ({ name: t.name, effect: t.effect === "reads" ? "reads" : "acts" })),
      sandbox_confirmed: risky && sandbox,
    });
    if (!started.ok) {
      setRunProblem(refusal(started.status, started.data));
      return;
    }
    viewKey.current = started.data.view_key;
    setViewKeyShown(started.data.view_key);
    setScanId(started.data.scan_id);
    setScan(null);
    setCountdown(null);
    setStage(3);
    void follow(started.data.scan_id);
  }

  // ---------- step 3 ----------
  async function follow(id: number) {
    try {
      while (!stopped.current) {
        const body = await readOpenScan(api, id, viewKey.current);
        setScan(body);
        if (body.scan.status !== "running") {
          setCountdown(6);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
    } catch {
      setScanProblem("Could not reach the backend. It may still be waking up.");
    }
  }

  const results = scan?.results ?? [];
  const finished = scan !== null && scan.scan.status !== "running";
  const running = stage === 3 && !finished && !scanProblem;
  const fails = results.filter((r) => r.status === "fail").length;
  const counted = results.filter((r) => r.status === "pass" || r.status === "fail").length;
  const critical = results.filter((r) => r.status === "fail" && r.severity === "critical").length;

  useEffect(() => {
    const stream = streamRef.current;
    if (stream) stream.scrollTop = stream.scrollHeight;
  }, [results.length]);

  useEffect(() => {
    const box = boxRef.current;
    if (!box || fails === 0) return;
    box.classList.remove("rf-pulse");
    void box.offsetWidth;
    box.classList.add("rf-pulse");
  }, [fails]);

  // when the run ends the report opens by itself, unless the person stays here
  useEffect(() => {
    if (countdown === null) return;
    if (countdown <= 0) {
      if (scanId !== null) router.push(reportPath(scanId, viewKeyShown));
      return;
    }
    const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown, scanId, router, viewKeyShown]);

  const state = (n: number): StepState => (n < stage ? "done" : n === stage ? "active" : "locked");
  const plan = ticked.length ? (
    <>
      <b>{ticked.length}</b> {ticked.length === 1 ? "tool" : "tools"} called, <b>{tools.length}</b>{" "}
      described
    </>
  ) : (
    <>
      No tool ticked: only the <b>{tools.length}</b> descriptions are checked.
    </>
  );

  return (
    <main className="d-mcp">
      <div className="intro">
        <h1>Check an MCP server</h1>
        <p>
          Tool descriptions are always checked for hidden instructions, invisible characters and
          open-ended inputs. Tools are only called if you tick them. A clean result is not proof
          that a server is safe.
        </p>
      </div>

      <div className="steps">
        <Step
          n={1}
          id="s1"
          title="Connect"
          state={state(1)}
          summary={`${hostOf(address)} · ${tools.length} tools`}
          onChange={running ? undefined : () => setStage(1)}
        >
          <p className="legend">
            Fields marked <span className="req">*</span> are required.
          </p>
          <label className="f">
            <span className="lab">
              <span>
                Server address<span className="req" aria-hidden="true">*</span>
              </span>
              <small>streamable HTTP, usually ending /mcp</small>
            </span>
            <input
              className="in"
              id="url"
              type="url"
              placeholder="https://tools.example.com/mcp"
              autoComplete="off"
              spellCheck={false}
              required
              value={url}
              aria-invalid={showUrlError ? "true" : "false"}
              aria-describedby="e-url"
              onChange={(e) => setUrl(e.target.value)}
            />
            {showUrlError && (
              <span className="err" id="e-url">
                {showUrlError}
              </span>
            )}
            <span className="hint">
              Must be a public https address. Private and internal addresses are refused.
            </span>
          </label>
          <label className="f">
            <span className="lab">
              <span>
                Access key <small>optional</small>
              </span>
              <small>used for this check only, never stored</small>
            </span>
            <input
              className="in"
              id="key"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </label>
          <details className="keyhow">
            <summary>How the key is sent</summary>
            <div className="inner">
              <div className="row2">
                <label className="f">
                  <span className="lab">
                    <span>
                      Key header name <small>optional</small>
                    </span>
                  </span>
                  <input
                    className="in"
                    spellCheck={false}
                    value={headerName}
                    onChange={(e) => setHeaderName(e.target.value)}
                  />
                </label>
                <label className="f">
                  <span className="lab">
                    <span>
                      Key header prefix <small>optional</small>
                    </span>
                  </span>
                  <input
                    className="in"
                    spellCheck={false}
                    value={headerPrefix}
                    onChange={(e) => setHeaderPrefix(e.target.value)}
                  />
                </label>
              </div>
              <span className="hint">
                For a server that uses <code>X-Api-Key</code>, set the name to that and clear the
                prefix.
              </span>
            </div>
          </details>
          <div className="actions">
            <button type="button" className="btn solid" disabled={!address || looking} onClick={look}>
              {looking ? (
                <>
                  <span className="spin" />
                  Looking…
                </>
              ) : tools.length ? (
                "Look again"
              ) : (
                "Look at the tools"
              )}
            </button>
            {lookProblem && (
              <span className="status bad" role="status">
                {lookProblem}
              </span>
            )}
          </div>
          <span className="hint">This lists the tools only. It calls no tool.</span>
        </Step>

        <Step
          n={2}
          id="s2"
          title="Choose what to call"
          state={state(2)}
          summary={ticked.length ? `${ticked.length} called · ${tools.length} described` : "descriptions only"}
          onChange={running ? undefined : () => setStage(2)}
        >
          <div className="toolhead">
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <h3>
                {tools.length} {tools.length === 1 ? "tool" : "tools"}
                {serverName && <span> on {serverName}</span>}
              </h3>
              <button
                type="button"
                className="allbtn"
                onClick={() => setTools(tools.map((t) => ({ ...t, on: !allOn })))}
              >
                {allOn ? "Untick all" : "Tick all"}
              </button>
            </div>
            <p>
              Tick a tool to have Redflag call it with manipulated text. Say whether it only reads
              or changes things: a tool that changes things is only called on a test or sandbox
              server.
            </p>
          </div>
          <div className="toolbar">
            <input
              className="in search"
              type="search"
              placeholder="Search tools"
              aria-label="Search tools"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="chips">
              {(
                [
                  ["all", "All"],
                  ["ticked", "Ticked"],
                  ["reads", "Only reads"],
                  ["changes", "Changes things"],
                ] as [Filter, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className="chip"
                  aria-pressed={filter === id}
                  onClick={() => setFilter(id)}
                >
                  {label}
                  <b>{count[id]}</b>
                </button>
              ))}
            </div>
          </div>
          <div className="tools" role="list" aria-label="Tools on this server">
            {shown.length === 0 && <div className="nomatch">No tools match.</div>}
            {shown.map((t) => (
              <div key={t.name} className={`tool ${t.on ? "on" : ""}`} role="listitem">
                <span
                  className="tick"
                  role="checkbox"
                  tabIndex={0}
                  aria-checked={t.on}
                  aria-label={`Call this tool: ${t.name}`}
                  onClick={() => update(t.name, { on: !t.on })}
                  onKeyDown={(e) => {
                    if (e.key === " " || e.key === "Enter") {
                      e.preventDefault();
                      update(t.name, { on: !t.on });
                    }
                  }}
                />
                <span className="tname">
                  {t.name}
                  <small>{t.params.length ? t.params.join(", ") : "no inputs"}</small>
                </span>
                <select
                  className={`effect ${t.effect}`}
                  aria-label={`What does ${t.name} do?`}
                  value={t.effect}
                  onChange={(e) => update(t.name, { effect: e.target.value as Effect })}
                >
                  <option value="reads">Only reads</option>
                  <option value="changes">Changes things</option>
                </select>
                <span className={`tdesc ${t.description ? "" : "none"}`}>
                  {t.description.slice(0, 500) || "No description."}
                </span>
              </div>
            ))}
          </div>
          {risky && (
            <>
              <div
                id="sandbox"
                className={`sandbox ${sandbox ? "on" : ""} ${sandboxError ? "invalid" : ""}`}
                role="checkbox"
                aria-checked={sandbox}
                tabIndex={0}
                onClick={() => setSandbox(!sandbox)}
                onKeyDown={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    setSandbox(!sandbox);
                  }
                }}
              >
                <span className="box" />
                <div>
                  <b>
                    This server is a test or sandbox, not production.
                    <span className="req" aria-hidden="true">*</span>
                  </b>
                  <span>
                    You ticked a tool that changes things. Redflag only calls those on a test or
                    sandbox server.
                  </span>
                </div>
              </div>
              {sandboxError && <span className="err">{sandboxError}</span>}
            </>
          )}
          {runProblem && (
            <div className="alert" role="alert">
              {runProblem}
            </div>
          )}
          <div className="actions">
            <button type="button" className="btn solid" onClick={run}>
              Run checks
            </button>
            <span className="plan">{plan}</span>
          </div>
        </Step>

        <Step n={3} id="s3" title="Results" state={state(3)}>
          <div className="runbox rf-wrap" ref={boxRef}>
            <div className="runhead">
              <b style={{ fontWeight: 500 }}>MCP check #{scanId}</b>
              <span style={{ color: "var(--muted)" }}>{serverName || hostOf(address)}</span>
              <span className={`state ${finished ? "done" : ""}`}>
                <i />
                <span>{finished ? "finished" : "running"}</span>
              </span>
            </div>
            <FlagStrip
              className="mstrip"
              looks={results.map((r) => lookOf(r.status))}
              running={running}
            />
            <div className="stream" ref={streamRef} aria-live="polite">
              {results.map((r) => {
                const [cls, word] = BADGE[r.status];
                return (
                  <div key={r.test_id} className={`rrow ${r.status === "fail" ? "fail" : ""}`}>
                    <span className={`badge ${cls}`}>{word}</span>
                    <span className="t">{r.title}</span>
                    <span className="k">{mcpGroup(r.test_id) === "static" ? "read" : "called"}</span>
                  </div>
                );
              })}
            </div>
            <div className="runfoot">
              <span>{results.length} tests done so far</span>
              <span>
                <span className="f" key={fails}>
                  {fails}
                </span>{" "}
                problems found
              </span>
            </div>
          </div>
          {scanProblem && (
            <div className="alert" role="alert">
              {scanProblem}
            </div>
          )}
          {finished && scan && scanId !== null && (
            <div className="mdone">
              <h3>
                {fails ? (
                  <>
                    <span className="bad">
                      <CountUp to={fails} /> of {counted}
                    </span>{" "}
                    checks failed.
                  </>
                ) : (
                  <>0 of {counted} checks failed.</>
                )}
              </h3>
              <FlagStrip looks={results.map((r) => lookOf(r.status))} />
              {scan.scan.status !== "completed" && (
                <p>{scan.scan.note ?? "The check stopped before it finished."}</p>
              )}
              <p>
                {fails ? `${critical} ${critical === 1 ? "was" : "were"} critical. ` : ""}The report
                shows what was found, what each tool sent back and how to fix it.
              </p>
              <div className="actions">
                <a className="btn solid" href={reportPath(scanId, viewKeyShown)}>
                  Open the report
                </a>
                {countdown !== null && (
                  <span className="cd">
                    {countdown > 0 ? (
                      <>
                        Opening in <b>{countdown}</b> s ·{" "}
                        <button type="button" onClick={() => setCountdown(null)}>
                          Stay here
                        </button>
                      </>
                    ) : (
                      "Opening…"
                    )}
                  </span>
                )}
                {countdown === null && <span className="cd">The report stays one click away.</span>}
              </div>
            </div>
          )}
        </Step>
      </div>
    </main>
  );
}
