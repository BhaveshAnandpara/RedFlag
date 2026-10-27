"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { parseConnection } from "@/lib/connect-parse";
import { hostOf, problemFor, readOpenScan, reportPath } from "@/lib/open-api";
import type { ScanDetail, ScanResult } from "@/lib/scan";
import type { Endpoint } from "@/lib/setup";
import { SetupApi } from "@/lib/setup-api";

import { ConnectWays, usableWay, type Way } from "./connect-ways";
import { CountUp } from "./design/count-up";
import { FlagStrip, RaisedFlag, lookOf } from "./design/flags";
import { Step, type StepState } from "./design/step";
import { McpPage } from "./mcp-page";

type Kind = "chatbot" | "agent";
type Rule = { t: string; on: boolean; own?: boolean };
type Env = "staging" | "production";
/** What the supervisor made of the hello reply: null when it could not say. */
type Logs = { found: boolean; fields: string[]; shape: string } | null;
/** One OWASP test a person can pick from for a live bot. */
type Pick = { id: string; title: string; goal: string; risk: string; risk_name: string; severity: string };
type Hello = { sig: string; ok: boolean; reply: string; error: string; logs: Logs };

const NO_LOGS =
  "We don't see logs in your bot's response. We can test your bot a lot better if it returns logs with each response, but it isn't mandatory.";
const STAGING_TICK_REQUIRED =
  "Tick the box to confirm this is a dev or test copy, not a published bot.";
type Format = { id: "flowise" | "openwebui" | "openai" | "unknown"; label: string };

/** Reads the address to tell which kind of bot it points at, so the person never picks a platform. */
export function detect(address: string): Format | null {
  if (!address) return null;
  if (/\/prediction\/[\w-]+/i.test(address))
    return { id: "flowise", label: "Looks like a Flowise chatflow. We'll send your messages to it." };
  if (/\/api\/?$|openwebui|open-webui/i.test(address))
    return { id: "openwebui", label: "Looks like Open WebUI. We'll use its chat address." };
  if (/\/v1\/?(chat\/completions)?$|openai|groq|ollama|together|openrouter/i.test(address))
    return { id: "openai", label: "Looks like an OpenAI-style address. We'll add /chat/completions." };
  return {
    id: "unknown",
    label:
      'We don\'t recognise this format yet. Say hello to try it, or set it up under "My bot is built differently".',
  };
}

type Fields = {
  addr: string;
  model: string;
  customOpen: boolean;
  customFormat: "chat" | "custom";
  tmpl: string;
  rpath: string;
  headerName: string;
  headerPrefix: string;
};

function buildEndpoint(f: Fields): Endpoint {
  const addr = f.addr.trim().replace(/\/+$/, "");
  const header = {
    header_name: f.headerName.trim() || "Authorization",
    header_prefix: f.headerPrefix,
  };
  if (f.customOpen && f.customFormat === "custom") {
    return {
      url: addr,
      format: "custom",
      model: "default",
      ...header,
      request_template: f.tmpl.trim(),
      reply_path: f.rpath.trim(),
    };
  }
  const kind = detect(addr)?.id;
  if (kind === "flowise") {
    return {
      url: addr,
      format: "custom",
      model: "default",
      ...header,
      request_template: '{"question": "{{prompt}}"}',
      reply_path: "text",
    };
  }
  const url =
    (kind === "openai" || kind === "openwebui") && !/\/chat\/completions$/.test(addr)
      ? `${addr}/chat/completions`
      : addr;
  return {
    url,
    format: "openai",
    model: f.model.trim() || "default",
    ...header,
    request_template: null,
    reply_path: null,
  };
}

const NO_MODEL = "Enter the model name your bot uses, such as llama-3.1-8b-instant.";

function focusFirst(ids: (string | null)[]) {
  const id = ids.find(Boolean);
  if (!id) return;
  const el = document.getElementById(id);
  el?.focus();
  el?.scrollIntoView?.({ block: "center", behavior: "smooth" });
}

export function QuickScanPage({
  apiUrl,
  pollMs = 2000,
  initialWay = "http",
}: {
  apiUrl: string;
  pollMs?: number;
  initialWay?: Way;
}) {
  // No password: the backend answers these calls openly. A scan is read back with the secret view
  // key that starting it returned, kept only here in memory.
  const api = useMemo(() => new SetupApi(apiUrl, ""), [apiUrl]);
  const [stage, setStage] = useState<1 | 2 | 3>(1);
  const [way, setWay] = useState<Way>(usableWay(initialWay));
  // Staging is the safer starting point: it asks for the "dev or test copy" tick before going on.
  const [env, setEnv] = useState<Env>("staging");
  const [stagingTick, setStagingTick] = useState(false);

  // step 1
  const [addr, setAddr] = useState("");
  const [model, setModel] = useState("");
  // The key lives only here, in memory: sent with the hello check and the run, never stored.
  const [key, setKey] = useState("");
  const [pasteOpen, setPasteOpen] = useState(usableWay(initialWay) === "curl");
  const [pasted, setPasted] = useState("");
  const [pasteNote, setPasteNote] = useState<{ text: string; bad: boolean } | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customFormat, setCustomFormat] = useState<"chat" | "custom">("chat");
  const [tmpl, setTmpl] = useState("");
  const [rpath, setRpath] = useState("");
  const [headerName, setHeaderName] = useState("Authorization");
  const [headerPrefix, setHeaderPrefix] = useState("Bearer ");
  const [attemptedHello, setAttemptedHello] = useState(false);
  const [busy, setBusy] = useState(false);
  const [hello, setHello] = useState<Hello | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [helloProblem, setHelloProblem] = useState<string | null>(null);

  // step 2
  const [ruleLists, setRuleLists] = useState<Record<Kind, string[]>>({ chatbot: [], agent: [] });
  const [rulesProblem, setRulesProblem] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind | null>(null);
  const [purpose, setPurpose] = useState("");
  const [rules, setRules] = useState<Rule[]>([]);
  const [newRule, setNewRule] = useState("");
  const [attemptedRun, setAttemptedRun] = useState(false);
  // Production only: the tests offered, and which of them are ticked. null until they are shown.
  const [picks, setPicks] = useState<Pick[] | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set());
  const [listing, setListing] = useState(false);
  const [runProblem, setRunProblem] = useState<string | null>(null);

  // step 3
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [scanId, setScanId] = useState<number | null>(null);
  const [testCount, setTestCount] = useState(0);
  const [scanProblem, setScanProblem] = useState<string | null>(null);
  const viewKey = useRef("");
  const [viewKeyShown, setViewKeyShown] = useState("");
  const stopped = useRef(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    api.call<{ rules: Record<Kind, string[]> }>("GET", "/quick-scans/rules").then((listed) => {
      if (!alive) return;
      if (listed.ok) setRuleLists(listed.data.rules);
      else setRulesProblem(problemFor(listed.status, listed.data));
    });
    return () => {
      alive = false;
    };
  }, [api]);

  // ---------- step 1: connect ----------
  const fields: Fields = { addr, model, customOpen, customFormat, tmpl, rpath, headerName, headerPrefix };
  const address = addr.trim();
  const format = detect(address);
  const needsModel =
    (format?.id === "openai" || format?.id === "openwebui") &&
    !(customOpen && customFormat === "custom");
  const asCustom = customOpen && customFormat === "custom";
  const helloErrors = {
    addr: !address
      ? "Enter your bot's address."
      : !/^https?:\/\//i.test(address)
        ? "Enter the full address, starting with https://."
        : "",
    model: needsModel && !model.trim() ? NO_MODEL : "",
    tmpl: asCustom
      ? !tmpl.trim()
        ? "Enter the request template."
        : !tmpl.includes("{{prompt}}")
          ? "The template must contain {{prompt}} where the message goes."
          : ""
      : "",
    rpath: asCustom && !rpath.trim() ? "Enter where the reply is found, such as output.text." : "",
  };
  const showHello = attemptedHello ? helloErrors : { addr: "", model: "", tmpl: "", rpath: "" };
  const signature = JSON.stringify([buildEndpoint(fields), key]);
  const shownHello = hello && hello.sig === signature ? hello : null;

  function readPasted() {
    const parsed = parseConnection(pasted);
    setPasted(""); // a pasted key never stays on screen
    if (parsed.found.length === 0) {
      setPasteNote({
        text: "We could not find a bot address in that. Paste a link or a curl command, or fill the details in below.",
        bad: true,
      });
      return;
    }
    if (parsed.url) setAddr(parsed.url.replace(/\/chat\/completions\/?$/, ""));
    if (parsed.key) setKey(parsed.key);
    if (parsed.model) setModel(parsed.model);
    if (parsed.format === "custom") {
      setCustomOpen(true);
      setCustomFormat("custom");
    }
    if (parsed.requestTemplate) setTmpl(parsed.requestTemplate);
    if (parsed.replyPath) setRpath(parsed.replyPath);
    if (parsed.headerName) setHeaderName(parsed.headerName);
    if (parsed.headerPrefix !== undefined) setHeaderPrefix(parsed.headerPrefix);
    const missing = parsed.missing.length ? ` Still needed: ${parsed.missing.join(", ")}.` : "";
    setPasteNote({ text: `We found: ${parsed.found.join(", ")}.${missing}`, bad: false });
  }

  async function sayHello() {
    setAttemptedHello(true);
    const bad = Object.entries(helloErrors).filter(([, m]) => m);
    if (bad.length) {
      focusFirst(bad.map(([id]) => (id === "addr" ? "addr" : id)));
      return;
    }
    setBusy(true);
    setHelloProblem(null);
    const sig = signature;
    const result = await api.call<{
      status: "ok" | "error";
      parsed_reply: string;
      error: string;
      logs?: Logs;
    }>(
      "POST",
      "/quick-scans/check",
      { endpoint: buildEndpoint(fields), key: key || null },
    );
    setBusy(false);
    if (!result.ok) {
      setHelloProblem(problemFor(result.status, result.data));
      return;
    }
    setHello({
      sig,
      ok: result.data.status === "ok",
      reply: result.data.parsed_reply,
      error: result.data.error,
      logs: result.data.logs ?? null,
    });
  }

  // ---------- step 2: describe ----------
  function chooseKind(next: Kind) {
    setKind(next);
    setPicks(null);
    const own = rules.filter((r) => r.own);
    setRules([...ruleLists[next].map((t) => ({ t, on: true })), ...own]);
  }
  const onCount = rules.filter((r) => r.on).length;
  const runErrors = {
    kind: !kind ? "Choose whether your bot is a chatbot or an agent." : "",
    purpose: !purpose.trim() ? "Say what your bot is for, in one sentence." : "",
    rules:
      kind && onCount === 0 ? "Pick at least one thing it must never do, or add your own." : "",
  };
  const showRun = attemptedRun ? runErrors : { kind: "", purpose: "", rules: "" };
  const ticked = (picks ?? []).filter((p) => !off.has(p.id));
  const live = env === "production";

  function changeRules(next: Rule[]) {
    setRules(next);
    setPicks(null); // the tests offered depend on the rules, so the list is shown again
  }

  function addRule() {
    const t = newRule.trim();
    if (!t) return;
    changeRules([...rules, { t, on: true, own: true }]);
    setNewRule("");
  }

  function checkRun(): boolean {
    setAttemptedRun(true);
    const bad = Object.entries(runErrors).filter(([, m]) => m);
    if (bad.length) {
      focusFirst(bad.map(([id]) => (id === "kind" ? "kind-chatbot" : id === "rules" ? "rule-0" : id)));
      return false;
    }
    return true;
  }

  async function showTests() {
    if (!checkRun()) return;
    setRunProblem(null);
    setListing(true);
    const listed = await api.call<{ tests: Pick[] }>("POST", "/quick-scans/production-tests", {
      bot_type: kind,
      must_never: rules.filter((r) => r.on).map((r) => r.t),
    });
    setListing(false);
    if (!listed.ok) {
      setRunProblem(problemFor(listed.status, listed.data));
      return;
    }
    setOff(new Set());
    setPicks(listed.data.tests);
  }

  const togglePick = (id: string) =>
    setOff((was) => {
      const next = new Set(was);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  async function runScan() {
    if (!checkRun()) return;
    setRunProblem(null);
    const started = await api.call<{ scan_id: number; view_key: string; test_count: number }>(
      "POST",
      "/quick-scans",
      {
        endpoint: buildEndpoint(fields),
        key: key || null,
        bot_type: kind,
        purpose: purpose.trim(),
        must_never: rules.filter((r) => r.on).map((r) => r.t),
        environment: env,
        ...(live ? { test_ids: ticked.map((p) => p.id) } : {}),
        // Staging's tick is the one confirmation that this is a test copy.
        sandbox_confirmed: kind === "agent" && !live && stagingTick,
      },
    );
    if (!started.ok) {
      setRunProblem(problemFor(started.status, started.data));
      return;
    }
    viewKey.current = started.data.view_key;
    setViewKeyShown(started.data.view_key);
    setScanId(started.data.scan_id);
    setTestCount(started.data.test_count);
    setScan(null);
    setStage(3);
    void follow(started.data.scan_id);
  }

  // ---------- step 3: the live scan ----------
  async function follow(id: number) {
    try {
      while (!stopped.current) {
        const body = await readOpenScan(api, id, viewKey.current);
        setScan(body);
        if (body.scan.status !== "running") return;
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
    } catch {
      setScanProblem("Could not reach the backend. It may still be waking up.");
    }
  }

  const results = scan?.results ?? [];
  const finished = scan !== null && scan.scan.status !== "running";
  const fails = results.filter((r) => r.status === "fail").length;

  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [results.length]);

  // a soft red pulse through the window each time a test fails
  useEffect(() => {
    const box = boxRef.current;
    if (!box || fails === 0) return;
    box.classList.remove("rf-pulse");
    void box.offsetWidth;
    box.classList.add("rf-pulse");
  }, [fails]);

  const attacks = results.filter((r) => r.kind === "negative");
  const attackFails = attacks.filter((r) => r.status === "fail").length;
  const total = testCount || scan?.scan.settings.test_count || 0;

  const state = (n: number): StepState => (n < stage ? "done" : n === stage ? "active" : "locked");
  const running = stage === 3 && !finished && !scanProblem;

  function chooseWay(next: Way) {
    setWay(next);
    if (next === "curl") setPasteOpen(true);
  }
  const ways = <ConnectWays value={way} onChange={chooseWay} />;

  // Choosing an MCP server runs the MCP check's own steps, unchanged, in place of the bot steps.
  if (way === "mcp") return <McpPage apiUrl={apiUrl} pollMs={pollMs} ways={ways} />;

  return (
    <main className="d-quick">
      <div className="intro">
        <h1>Quick scan</h1>
        <p>
          A starter pack of tests, run on your bot in one go. It is a first check, not proof that
          your bot is secure.
        </p>
      </div>

      {rulesProblem && (
        <div className="alert" role="alert" style={{ marginTop: 24 }}>
          {rulesProblem}
        </div>
      )}

      <div className="steps">
        <Step
          n={1}
          id="s1"
          title="Connect your bot"
          state={state(1)}
          summary={`${hostOf(address)} · answered hello`}
          onChange={running ? undefined : () => setStage(1)}
        >
          <div className="f">
            <div className="ways" role="radiogroup" aria-label="Where is your bot?">
              {(
                [
                  ["staging", "Staging"],
                  ["production", "Production"],
                ] as [Env, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className="way"
                  role="radio"
                  aria-checked={env === id}
                  onClick={() => setEnv(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="hint">
              {env === "staging"
                ? "In development, not published. The full scan runs."
                : "Live. Only the OWASP top 10 tests, which you choose from."}
            </span>
          </div>
          {env === "staging" && (
            <div
              id="staging-tick"
              className={`sandbox ${stagingTick ? "on" : ""}`}
              role="checkbox"
              aria-checked={stagingTick}
              aria-label="This is a dev or test copy, not published"
              tabIndex={0}
              onClick={() => setStagingTick(!stagingTick)}
              onKeyDown={(e) => {
                if (e.key === " " || e.key === "Enter") {
                  e.preventDefault();
                  setStagingTick(!stagingTick);
                }
              }}
            >
              <span className="box" />
              <div>
                <b>This is a dev or test copy, not published.</b>
                <span>
                  Redflag takes your word for it. Tests may make your bot do real things, so only
                  use a copy you can reset.
                </span>
              </div>
            </div>
          )}
          {ways}
          <p className="legend">
            Fields marked <span className="req">*</span> are required.
          </p>
          <label className="f">
            <span className="lab">
              <span>
                Your bot&apos;s address<span className="req" aria-hidden="true">*</span>
              </span>
            </span>
            <input
              className="in"
              id="addr"
              type="url"
              required
              placeholder="https://api.example.com/v1"
              autoComplete="off"
              spellCheck={false}
              value={addr}
              aria-invalid={showHello.addr ? "true" : "false"}
              aria-describedby="e-addr"
              onChange={(e) => setAddr(e.target.value)}
            />
            {format && (
              <span className={`detect ${format.id === "unknown" ? "unknown" : ""}`}>
                <i />
                <span>{format.label}</span>
              </span>
            )}
            {showHello.addr && (
              <span className="err" id="e-addr">
                {showHello.addr}
              </span>
            )}
          </label>

          {needsModel && (
            <div className="row2">
              <label className="f">
                <span className="lab">
                  <span>
                    Model name<span className="req" aria-hidden="true">*</span>
                  </span>
                </span>
                <input
                  className="in"
                  id="model"
                  placeholder="llama-3.1-8b-instant"
                  spellCheck={false}
                  value={model}
                  aria-invalid={showHello.model ? "true" : "false"}
                  aria-describedby="e-model"
                  onChange={(e) => setModel(e.target.value)}
                />
                {showHello.model && (
                  <span className="err" id="e-model">
                    {showHello.model}
                  </span>
                )}
              </label>
              <span />
            </div>
          )}

          <label className="f">
            <span className="lab">
              <span>
                Its key <small>optional</small>
              </span>
              <small>used for this scan only, never stored</small>
            </span>
            <input
              className="in"
              id="key"
              type="password"
              placeholder="sk-…"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </label>

          <div className="links">
            <button type="button" onClick={() => setPasteOpen(!pasteOpen)}>
              I have a code snippet instead
            </button>
            <button type="button" onClick={() => setCustomOpen(!customOpen)}>
              My bot is built differently
            </button>
          </div>

          {pasteOpen && (
            <div className="panel">
              <label className="f">
                <span className="lab">Paste a link, a key, a code sample or a curl command</span>
                <textarea
                  className="in"
                  spellCheck={false}
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                />
              </label>
              <div className="actions">
                <button
                  type="button"
                  className="btn ghost small"
                  disabled={!pasted.trim()}
                  onClick={readPasted}
                >
                  Read it
                </button>
                {pasteNote && (
                  <span className={`status ${pasteNote.bad ? "bad" : "ok"}`} role="status">
                    {pasteNote.text}
                  </span>
                )}
              </div>
            </div>
          )}

          {customOpen && (
            <div className="panel">
              <label className="f">
                <span className="lab">Message format</span>
                <select
                  className="in"
                  value={customFormat}
                  onChange={(e) => setCustomFormat(e.target.value as "chat" | "custom")}
                >
                  <option value="chat">Chat completions style</option>
                  <option value="custom">Custom body</option>
                </select>
              </label>
              {customFormat === "custom" && (
                <div className="row2">
                  <label className="f">
                    <span className="lab">
                      <span>
                        Request template<span className="req" aria-hidden="true">*</span>
                      </span>
                      <small>must contain {"{{prompt}}"}</small>
                    </span>
                    <input
                      className="in"
                      id="tmpl"
                      placeholder='{"input": "{{prompt}}"}'
                      spellCheck={false}
                      value={tmpl}
                      aria-invalid={showHello.tmpl ? "true" : "false"}
                      aria-describedby="e-tmpl"
                      onChange={(e) => setTmpl(e.target.value)}
                    />
                    {showHello.tmpl && (
                      <span className="err" id="e-tmpl">
                        {showHello.tmpl}
                      </span>
                    )}
                  </label>
                  <label className="f">
                    <span className="lab">
                      <span>
                        Reply path<span className="req" aria-hidden="true">*</span>
                      </span>
                    </span>
                    <input
                      className="in"
                      id="rpath"
                      placeholder="output.text"
                      spellCheck={false}
                      value={rpath}
                      aria-invalid={showHello.rpath ? "true" : "false"}
                      aria-describedby="e-rpath"
                      onChange={(e) => setRpath(e.target.value)}
                    />
                    {showHello.rpath && (
                      <span className="err" id="e-rpath">
                        {showHello.rpath}
                      </span>
                    )}
                  </label>
                </div>
              )}
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
            </div>
          )}

          <div className="actions">
            <button type="button" className="btn solid" disabled={busy} onClick={sayHello}>
              {busy ? (
                <>
                  <span className="spin" />
                  Saying hello…
                </>
              ) : shownHello ? (
                "Say hello again"
              ) : (
                "Say hello"
              )}
            </button>
            {helloProblem && (
              <span className="status bad" role="status">
                {helloProblem}
              </span>
            )}
            {shownHello && !shownHello.ok && (
              <span className="status bad" role="status">
                {shownHello.error}
              </span>
            )}
            {shownHello?.ok && denied === signature && (
              <span className="status" role="status">
                Then check the address, the key and the model name, and say hello again.
              </span>
            )}
          </div>

          {shownHello?.ok && denied !== signature && (
            <div className="hello">
              <span className="who r">Redflag</span>
              <div className="bubble me">Hello</div>
              <span className="who">your bot</span>
              <div className="bubble bot">{shownHello.reply}</div>
              {env === "staging" && (
                <span className="hint" role="status">
                  {shownHello.logs?.found
                    ? `We found logs in your bot's response (${shownHello.logs.fields.join(", ") || "in the reply"}). Findings can be confirmed from them.`
                    : NO_LOGS}
                </span>
              )}
              <div className="confirm">
                <b>Is this your bot&apos;s answer?</b>
                <div className="actions">
                  <button
                    type="button"
                    className="btn solid small"
                    disabled={env === "staging" && !stagingTick}
                    onClick={() => setStage(2)}
                  >
                    Yes, that&apos;s my bot&apos;s answer
                  </button>
                  <button type="button" className="btn ghost small" onClick={() => setDenied(signature)}>
                    No, that&apos;s not right
                  </button>
                </div>
                {env === "staging" && !stagingTick && (
                  <span className="err">{STAGING_TICK_REQUIRED}</span>
                )}
              </div>
            </div>
          )}
        </Step>

        <Step
          n={2}
          id="s2"
          title="Tell us about it"
          state={state(2)}
          summary={`${kind === "agent" ? "Agent" : "Chatbot"} · ${onCount} rule${onCount === 1 ? "" : "s"}`}
          onChange={running ? undefined : () => setStage(2)}
        >
          <div role="radiogroup" aria-label="What does your bot do?" className="f" style={{ display: "grid", gap: 10 }}>
            <span className="lab">
              <span>
                What does your bot do?<span className="req" aria-hidden="true">*</span>
              </span>
            </span>
            <div className={`kinds ${showRun.kind ? "invalid" : ""}`}>
              <button
                type="button"
                id="kind-chatbot"
                className="kind"
                role="radio"
                aria-checked={kind === "chatbot"}
                onClick={() => chooseKind("chatbot")}
              >
                <b>Answers questions</b>
                <span>A chatbot. It talks, but it can&apos;t do anything on its own.</span>
              </button>
              <button
                type="button"
                className="kind"
                role="radio"
                aria-checked={kind === "agent"}
                onClick={() => chooseKind("agent")}
              >
                <b>Takes actions too</b>
                <span>An agent. It can book, refund, send emails or change things.</span>
              </button>
            </div>
            {showRun.kind && <span className="err">{showRun.kind}</span>}
          </div>

          <label className="f">
            <span className="lab">
              <span>
                What is it for?<span className="req" aria-hidden="true">*</span>
              </span>
              <small>one sentence</small>
            </span>
            <input
              className="in"
              id="purpose"
              required
              placeholder="A customer support assistant for Acme Bank that answers questions about accounts, cards and fees."
              value={purpose}
              aria-invalid={showRun.purpose ? "true" : "false"}
              aria-describedby="e-purpose"
              onChange={(e) => setPurpose(e.target.value)}
            />
            {showRun.purpose && (
              <span className="err" id="e-purpose">
                {showRun.purpose}
              </span>
            )}
          </label>

          {kind && (
            <div>
              <div className="lab" style={{ marginBottom: 6 }}>
                <span>
                  What must it never do?<span className="req" aria-hidden="true">*</span>
                </span>
                <small>
                  {onCount} of {rules.length} on
                </small>
              </div>
              <div className="rules">
                {rules.map((rule, i) => (
                  <div key={`${i}-${rule.t}`} className={`rule ${rule.on ? "" : "off"}`}>
                    <span>
                      {rule.t}
                      {rule.own && <span className="mine">your rule</span>}
                    </span>
                    <button
                      type="button"
                      id={`rule-${i}`}
                      className="sw"
                      role="switch"
                      aria-checked={rule.on}
                      aria-label={rule.t}
                      onClick={() =>
                        changeRules(rules.map((r, k) => (k === i ? { ...r, on: !r.on } : r)))
                      }
                    />
                  </div>
                ))}
              </div>
              {showRun.rules && <span className="err">{showRun.rules}</span>}
              <div className="addrule">
                <input
                  className="in"
                  aria-label="Add your own rule"
                  placeholder="Add your own, e.g. It must never promise a refund."
                  value={newRule}
                  onChange={(e) => setNewRule(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addRule();
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn ghost small"
                  disabled={!newRule.trim()}
                  onClick={addRule}
                >
                  Add rule
                </button>
              </div>
            </div>
          )}

          {runProblem && (
            <div className="alert" role="alert">
              {runProblem}
            </div>
          )}
          {live && picks && (
            <div>
              <div className="lab" style={{ marginBottom: 6 }}>
                <span>Which OWASP tests should run?</span>
                <small>
                  {ticked.length} of {picks.length} on
                </small>
              </div>
              <div className="rules">
                {picks.map((p) => (
                  <div key={p.id} className={`rule ${off.has(p.id) ? "off" : ""}`}>
                    <span>
                      {p.title}
                      <span className="mine">
                        {p.risk} {p.risk_name}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="sw"
                      role="switch"
                      aria-checked={!off.has(p.id)}
                      aria-label={p.title}
                      onClick={() => togglePick(p.id)}
                    />
                  </div>
                ))}
              </div>
              <div className="actions" style={{ marginTop: 8 }}>
                <button
                  type="button"
                  className="btn ghost small"
                  onClick={() => setOff(ticked.length ? new Set(picks.map((p) => p.id)) : new Set())}
                >
                  {ticked.length ? "Untick all" : "Tick all"}
                </button>
              </div>
            </div>
          )}
          <div className="actions">
            {live && !picks ? (
              <button type="button" className="btn solid" disabled={listing} onClick={showTests}>
                {listing ? (
                  <>
                    <span className="spin" />
                    Finding the tests…
                  </>
                ) : (
                  "Show the tests"
                )}
              </button>
            ) : (
              <button
                type="button"
                className="btn solid"
                disabled={live && ticked.length === 0}
                onClick={runScan}
              >
                {live ? `Run ${ticked.length} ${ticked.length === 1 ? "test" : "tests"}` : "Run my scan"}
              </button>
            )}
          </div>
        </Step>

        <Step n={3} id="s3" title="Watch the scan" state={state(3)}>
          <div className="scanbox rf-wrap" ref={boxRef}>
            <div className="scanhead">
              <b style={{ fontWeight: 500 }}>Scan #{scanId}</b>
              <span style={{ color: "var(--muted)" }}>{hostOf(address)}</span>
              <span className={`state ${finished ? "done" : ""}`}>
                <i />
                <span>{finished ? "finished" : "running"}</span>
              </span>
            </div>
            <div className="bar">
              <i style={{ width: total ? `${Math.min(100, (results.length / total) * 100)}%` : "0%" }} />
            </div>
            <FlagStrip
              className="qstrip"
              looks={results.map((r) => lookOf(r.status))}
              total={total}
              running={running}
            />
            <div className="thread" ref={threadRef} aria-live="polite">
              {results.map((r, i) => (
                <TestBubbles key={r.test_id} result={r} index={i} total={total || results.length} />
              ))}
              {running && (
                <div className="test">
                  <div className="dots" aria-label="Next test running">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
              )}
            </div>
            <div className="scanfoot">
              <span>
                {results.length} of {total || results.length} tests done
              </span>
              <span>
                <span className="f" key={fails}>
                  {fails}
                </span>{" "}
                got through
              </span>
            </div>
          </div>
          {scanProblem && (
            <div className="alert" role="alert">
              {scanProblem}
            </div>
          )}
          {finished && scan && scanId !== null && (
            <div className="donecard">
              <h3>
                <span className="bad">
                  <CountUp to={attackFails} /> of {attacks.length}
                </span>{" "}
                attacks got through.
              </h3>
              <FlagStrip className="qstrip" looks={results.map((r) => lookOf(r.status))} />
              {scan.scan.status !== "completed" && (
                <p>{scan.scan.note ?? "The scan stopped before it finished."}</p>
              )}
              <p>
                Every result was decided by the AI judge, which has not been checked for accuracy.
                This is not a guarantee of security. It only reports what these tests checked.
              </p>
              <div className="actions">
                <Link
                  className="btn solid small"
                  href={reportPath(scanId, viewKeyShown)}
                  style={{ textDecoration: "none" }}
                >
                  Open the report
                </Link>
              </div>
            </div>
          )}
        </Step>
      </div>
    </main>
  );
}

function TestBubbles({ result, index, total }: { result: ScanResult; index: number; total: number }) {
  const fail = result.status === "fail";
  const turns = result.turns && result.turns.length > 0 ? result.turns : null;
  const reason = (result.judge_reason ?? result.evidence).replace(" or the tool log", "");
  return (
    <div className="test">
      <div className="tmeta">
        test {index + 1} of {total} ·{" "}
        {result.kind === "positive" ? (
          "normal request"
        ) : (
          <>
            <em>attack</em> · {result.risk}
          </>
        )}{" "}
        · {result.title}
      </div>
      {turns ? (
        turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} className="bubble me">
              {t.content}
            </div>
          ) : (
            <Reply key={i} fail={fail && i === turns.length - 1} text={t.content} />
          ),
        )
      ) : (
        <>
          <div className="bubble me">{result.message}</div>
          <Reply fail={fail} text={result.reply || "(no reply)"} />
        </>
      )}
      <div className="verdict">
        <span className={`badge ${lookOf(result.status)}`}>{badgeWord(result.status)}</span>
        <span className="judgeby">AI judge</span>
        <span className="why">{reason}</span>
      </div>
    </div>
  );
}

function Reply({ fail, text }: { fail: boolean; text: string }) {
  return (
    <div className={`bubble bot ${fail ? "fouled" : "held"}`}>
      {fail && <RaisedFlag />}
      {text}
    </div>
  );
}

const badgeWord = (status: ScanResult["status"]): string =>
  ({ pass: "PASS", fail: "FAIL", inconclusive: "UNCLEAR", error: "ERROR", not_applicable: "N/A" })[status];
