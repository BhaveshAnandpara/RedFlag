"use client";

import { useEffect, useRef, useState } from "react";

import type { ScanDetail, ScanListItem } from "@/lib/scan";
import {
  REQUIRED_LABELS,
  describeError,
  type ConnectionResult,
  type Contexts,
  type Endpoint,
  type GeneratedTest,
  type Rule,
  type SetupListItem,
  type SetupView,
  type Strategy,
} from "@/lib/setup";
import { SetupApi } from "@/lib/setup-api";

import { FinishedScan } from "./finished-scan";
import { StatusBadge, TONE_CLASS } from "./status";

type Stage = "describe" | "rules" | "tests" | "run";

const FIELD = "w-full rounded border-2 border-zinc-500 bg-white p-2 text-black";
const BUTTON = "rounded border-2 px-3 py-1 text-sm disabled:opacity-50";
const PRIMARY =
  "rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-black";
const ALLOWED_FILE = /\.(txt|md|markdown|json)$/i;
const FILE_PROBLEM = "Only text, markdown and JSON files are accepted.";

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

const SOURCE_WORDS = { user: "you said it", model: "from the chat AI", edited: "edited by you" };

export function SetupPage({ apiUrl, pollMs = 2000 }: { apiUrl: string; pollMs?: number }) {
  const [password, setPassword] = useState("");
  const [api, setApi] = useState<SetupApi | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [list, setList] = useState<SetupListItem[]>([]);
  const [view, setView] = useState<SetupView | null>(null);
  const [stage, setStage] = useState<Stage>("describe");
  const [endpoint, setEndpoint] = useState<Endpoint | null>(null);
  // The key lives only here, in memory. It is sent to the connection test and to the run, never
  // to the chat, and it is gone when the page is reloaded.
  const [key, setKey] = useState("");
  const [tests, setTests] = useState<GeneratedTest[]>([]);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [history, setHistory] = useState<ScanListItem[]>([]);
  // The scan before the one on screen, to show what changed since the last run.
  const [previous, setPrevious] = useState<ScanDetail | null>(null);
  const stopped = useRef(false);
  // The confirmed version the tests belong to.
  const [version, setVersion] = useState(1);

  useEffect(() => {
    stopped.current = false;
    return () => {
      stopped.current = true;
    };
  }, []);

  async function unlock() {
    setProblem(null);
    const probe = new SetupApi(apiUrl, password);
    const result = await probe.call("GET", "/bots");
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    // Held in memory only: never stored in the browser and never put in a URL.
    setApi(probe);
    const listed = await probe.call<{ setups: SetupListItem[] }>("GET", "/setups");
    if (listed.ok) setList(listed.data.setups);
  }

  async function open(setupId: number, active: SetupApi) {
    const result = await active.call<SetupView>("GET", `/setups/${setupId}`);
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setView(result.data);
    setEndpoint(result.data.endpoint);
    setStage("describe");
  }

  async function startNew() {
    if (!api) return;
    setProblem(null);
    const created = await api.call<{ setup_id: number }>("POST", "/setups");
    if (!created.ok) {
      setProblem(describeError(created.status, created.data as never));
      return;
    }
    await open(created.data.setup_id, api);
  }

  async function refresh() {
    if (!api || !view) return;
    const result = await api.call<SetupView>("GET", `/setups/${view.setup_id}`);
    if (result.ok) setView(result.data);
  }

  return (
    <section className="space-y-6">
      <h1 className="text-3xl font-semibold">Test your own bot</h1>

      {api === null ? (
        <div className="space-y-3">
          <p>Locked: enter the owner password to use this page.</p>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">Owner password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={FIELD}
            />
          </label>
          <button type="button" onClick={unlock} className={PRIMARY}>
            Unlock
          </button>
          {problem && <p role="alert">{problem}</p>}
        </div>
      ) : view === null ? (
        <div className="space-y-4">
          <button type="button" onClick={startNew} className={PRIMARY}>
            Start a new setup
          </button>
          {problem && <p role="alert">{problem}</p>}
          {list.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-lg font-semibold">Earlier setups</h2>
              <ul aria-label="Your setups" className="space-y-2">
                {list.map((item) => (
                  <li key={item.setup_id} className="flex flex-wrap items-baseline gap-3 rounded border-2 p-3">
                    <span>
                      Setup #{item.setup_id} · {item.purpose || "no purpose yet"} · {item.versions}{" "}
                      {item.versions === 1 ? "version" : "versions"}
                    </span>
                    <button
                      type="button"
                      aria-label={`Resume setup #${item.setup_id}`}
                      onClick={() => open(item.setup_id, api)}
                      className={BUTTON}
                    >
                      Resume
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          {problem && <p role="alert">{problem}</p>}
          {stage === "describe" && endpoint && (
            <Describe
              api={api}
              view={view}
              endpoint={endpoint}
              setEndpoint={setEndpoint}
              keyValue={key}
              setKey={setKey}
              refresh={refresh}
              setProblem={setProblem}
              onReview={() => {
                setProblem(null);
                setStage("rules");
              }}
            />
          )}
          {stage === "rules" && (
            <RulesStage
              api={api}
              view={view}
              refresh={refresh}
              setProblem={setProblem}
              onVersion={(generated) => {
                setTests(generated);
                setTicked(new Set(generated.filter((t) => t.selected).map((t) => t.id)));
                setStage("tests");
              }}
              versionHolder={setVersion}
              onBack={() => setStage("describe")}
            />
          )}
          {stage === "tests" && (
            <TestsStage
              api={api}
              setupId={view.setup_id}
              version={version}
              onTestsChange={setTests}
              tests={tests}
              ticked={ticked}
              setTicked={setTicked}
              keyValue={key}
              setKey={setKey}
              setProblem={setProblem}
              onRun={async () => {
                setProblem(null);
                const result = await api.call<{ scan_id: number }>(
                  "POST",
                  `/setups/${view.setup_id}/versions/${version}/runs`,
                  { test_ids: tests.filter((t) => ticked.has(t.id)).map((t) => t.id), key: key || null },
                );
                if (!result.ok) {
                  setProblem(describeError(result.status, result.data as never));
                  return;
                }
                setStage("run");
                await follow(result.data.scan_id);
              }}
            />
          )}
          {stage === "run" && scan && (scan.scan.status === "running" ? (
            <RunningView detail={scan} />
          ) : (
            <FinishedScan
              api={api}
              scan={scan}
              history={history}
              previous={previous}
              keyValue={key}
              setKey={setKey}
              onRunAgain={(id) => void runAgain(id)}
              onOpen={(id) => void openScan(id)}
              loadScan={(id) => fetchScan(id)}
              setProblem={setProblem}
            />
          ))}
        </div>
      )}
    </section>
  );

  // --- the run ---------------------------------------------------------------------------

  async function fetchScan(scanId: number): Promise<ScanDetail> {
    const result = await api!.call<ScanDetail>("GET", `/scans/${scanId}`);
    if (!result.ok) throw new Error(`scan request failed with ${result.status}`);
    return result.data;
  }

  async function loadPrevious(detail: ScanDetail) {
    const id = detail.scan.previous_scan_id;
    if (!id) {
      setPrevious(null);
      return;
    }
    try {
      setPrevious(await fetchScan(id));
    } catch {
      setPrevious(null); // the comparison is a convenience; the scan itself is still shown
    }
  }

  async function runAgain(scanId: number) {
    setProblem(null);
    const result = await api!.call<{ scan_id: number }>("POST", `/scans/${scanId}/rerun`, {
      key: key || null,
    });
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setPrevious(null);
    await follow(result.data.scan_id);
  }

  async function openScan(scanId: number) {
    try {
      const opened = await fetchScan(scanId);
      setScan(opened);
      await loadPrevious(opened);
    } catch {
      setProblem(describeError(0, null));
    }
  }

  async function follow(scanId: number) {
    try {
      while (!stopped.current) {
        const body = await fetchScan(scanId);
        setScan(body);
        if (body.scan.status !== "running") {
          const listed = await api!.call<{ scans: ScanListItem[] }>(
            "GET",
            `/scans?bot_id=${view?.project_slug ?? ""}`,
          );
          if (listed.ok) setHistory(listed.data.scans);
          await loadPrevious(body);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, pollMs));
      }
    } catch {
      setProblem(describeError(0, null));
    }
  }

}

export function RunningView({ detail }: { detail: ScanDetail }) {
  const { scan, results } = detail;
  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">Scan #{scan.id}</h2>
      <p>{scan.settings.bot_name} · Status: running</p>
      <p>
        {results.length} of {scan.settings.test_count} tests done
      </p>
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

// --- describe: connect, chat and the side panel -----------------------------------------------

function Describe({
  api,
  view,
  endpoint,
  setEndpoint,
  keyValue,
  setKey,
  refresh,
  setProblem,
  onReview,
}: {
  api: SetupApi;
  view: SetupView;
  endpoint: Endpoint;
  setEndpoint: (value: Endpoint) => void;
  keyValue: string;
  setKey: (value: string) => void;
  refresh: () => Promise<void>;
  setProblem: (value: string | null) => void;
  onReview: () => void;
}) {
  const [connection, setConnection] = useState<ConnectionResult | null>(null);
  const [message, setMessage] = useState("");
  const [asking, setAsking] = useState<string | null>(null);
  const [limitReached, setLimitReached] = useState(false);
  const [limitNotice, setLimitNotice] = useState<string | null>(null);
  const [editingPurpose, setEditingPurpose] = useState(false);
  const [purposeDraft, setPurposeDraft] = useState("");
  const [example, setExample] = useState("");
  const [exampleLabel, setExampleLabel] = useState("conversation");
  const [contexts, setContexts] = useState<Contexts | null>(view.contexts);
  const id = view.setup_id;

  async function testConnection() {
    setProblem(null);
    const saved = await api.call("PUT", `/setups/${id}/endpoint`, endpoint);
    if (!saved.ok) {
      setProblem(describeError(saved.status, saved.data as never));
      return;
    }
    const result = await api.call<ConnectionResult>("POST", `/setups/${id}/connection-test`, {
      key: keyValue || null,
    });
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setConnection(result.data);
    await refresh();
  }

  async function send() {
    if (!message.trim()) return;
    setProblem(null);
    const result = await api.call<{ reply: string; asking: string | null; limit_reached: boolean }>(
      "POST",
      `/setups/${id}/chat`,
      { message },
    );
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setMessage("");
    setAsking(result.data.asking);
    setLimitReached(result.data.limit_reached);
    setLimitNotice(result.data.limit_reached ? result.data.reply : null);
    await refresh();
  }

  async function skip() {
    if (!asking) return;
    await api.call("POST", `/setups/${id}/skip`, { topic: asking });
    setAsking(null);
    await refresh();
  }

  async function savePurpose() {
    await api.call("PUT", `/setups/${id}/purpose`, { value: purposeDraft });
    setEditingPurpose(false);
    await refresh();
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    if (!ALLOWED_FILE.test(file.name)) {
      setProblem(FILE_PROBLEM);
      return;
    }
    setProblem(null);
    const result = await api.call("POST", `/setups/${id}/files`, {
      name: file.name,
      content: await readFile(file),
    });
    if (!result.ok) setProblem(describeError(result.status, result.data as never));
    await refresh();
  }

  async function addExample() {
    if (!example.trim()) return;
    await api.call("POST", `/setups/${id}/examples`, { text: example, label: exampleLabel });
    setExample("");
    await refresh();
  }

  async function buildContexts() {
    setProblem(null);
    const result = await api.call<{ contexts: Contexts }>("POST", `/setups/${id}/contexts`);
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setContexts(result.data.contexts);
  }

  const fields = view.fields;
  const required = view.required;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-6">
        <section aria-label="Connect your bot" role="region" className="space-y-3 rounded border-2 p-4">
          <h2 className="text-lg font-semibold">Connect your bot</h2>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">Endpoint URL</span>
            <input
              value={endpoint.url}
              onChange={(event) => setEndpoint({ ...endpoint, url: event.target.value })}
              className={FIELD}
            />
          </label>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">Format</span>
            <select
              value={endpoint.format}
              onChange={(event) =>
                setEndpoint({ ...endpoint, format: event.target.value as Endpoint["format"] })
              }
              className={FIELD}
            >
              <option value="openai">OpenAI-compatible</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          {endpoint.format === "openai" ? (
            <label className="block space-y-1">
              <span className="block text-sm font-medium">Model name</span>
              <input
                value={endpoint.model}
                onChange={(event) => setEndpoint({ ...endpoint, model: event.target.value })}
                className={FIELD}
              />
            </label>
          ) : (
            <>
              <label className="block space-y-1">
                <span className="block text-sm font-medium">Request template</span>
                <textarea
                  value={endpoint.request_template ?? ""}
                  onChange={(event) => setEndpoint({ ...endpoint, request_template: event.target.value })}
                  placeholder='{"question": "{{prompt}}"}'
                  className={FIELD}
                />
              </label>
              <label className="block space-y-1">
                <span className="block text-sm font-medium">Reply path</span>
                <input
                  value={endpoint.reply_path ?? ""}
                  onChange={(event) => setEndpoint({ ...endpoint, reply_path: event.target.value })}
                  placeholder="data.answer"
                  className={FIELD}
                />
              </label>
            </>
          )}
          <label className="block space-y-1">
            <span className="block text-sm font-medium">
              API key (kept in this browser only, never sent to the chat AI)
            </span>
            <input
              type="password"
              autoComplete="off"
              value={keyValue}
              onChange={(event) => setKey(event.target.value)}
              className={FIELD}
            />
          </label>
          <button type="button" onClick={testConnection} className={BUTTON}>
            Test connection
          </button>
          {connection && (
            <p
              role="status"
              className={`rounded border-2 p-2 text-sm ${TONE_CLASS[connection.status === "ok" ? "green" : "red"]}`}
            >
              {connection.status === "ok"
                ? `Connected. The bot answered: "${connection.parsed_reply}"`
                : `Could not connect: ${connection.error}${connection.raw_reply ? ` It said: "${connection.raw_reply}"` : ""}`}{" "}
              {connection.attempts_left} connection tests left.
            </p>
          )}
        </section>

        <section className="space-y-3 rounded border-2 p-4">
          <h2 className="text-lg font-semibold">Tell us about your bot</h2>
          <div role="log" aria-label="Conversation" className="space-y-2 text-sm">
            {view.chat.length === 0 && (
              <p>
                Describe your bot in your own words: what it is for, what it must never do. You can
                also paste examples or upload files.
              </p>
            )}
            {view.chat.map((turn, index) => (
              <p key={index}>
                <span className="font-semibold">{turn.role === "user" ? "You" : "Redflag"}:</span>{" "}
                {turn.content}
              </p>
            ))}
          </div>
          <label className="block space-y-1">
            <span className="block text-sm font-medium">Your message</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              className={FIELD}
            />
          </label>
          {limitNotice && <p role="status">{limitNotice}</p>}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={send}
              disabled={limitReached}
              className={PRIMARY}
            >
              Send
            </button>
            {asking && (
              <button type="button" onClick={skip} className={BUTTON}>
                Skip this question
              </button>
            )}
          </div>
        </section>
      </div>

      <div className="space-y-6">
        <section aria-label="Required before you can review the rules" className="space-y-2 rounded border-2 p-4">
          <h2 className="text-lg font-semibold">Required</h2>
          <ul aria-label="Required before you can review the rules" className="space-y-1 text-sm">
            {(Object.keys(REQUIRED_LABELS) as (keyof typeof REQUIRED_LABELS)[]).map((name) => (
              <li key={name}>
                {REQUIRED_LABELS[name]}:{" "}
                <span className="font-semibold">{required[name] ? "Done" : "Missing"}</span>
              </li>
            ))}
          </ul>
          <button type="button" onClick={onReview} disabled={!required.ready} className={PRIMARY}>
            Review the rules
          </button>
        </section>

        <section
          aria-label="What Redflag understood"
          role="region"
          className="space-y-3 rounded border-2 p-4 text-sm"
        >
          <h2 className="text-lg font-semibold">What Redflag understood</h2>
          <div className="space-y-1">
            {editingPurpose ? (
              <>
                <label className="block space-y-1">
                  <span className="block font-medium">Purpose</span>
                  <textarea
                    value={purposeDraft}
                    onChange={(event) => setPurposeDraft(event.target.value)}
                    className={FIELD}
                  />
                </label>
                <button type="button" onClick={savePurpose} className={BUTTON}>
                  Save purpose
                </button>
              </>
            ) : (
              <>
                <p>
                  Purpose: {fields.purpose.value || "not said yet"}{" "}
                  {fields.purpose.value && (
                    <span className="text-xs">({SOURCE_WORDS[fields.purpose.source]})</span>
                  )}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setPurposeDraft(fields.purpose.value);
                    setEditingPurpose(true);
                  }}
                  className={BUTTON}
                >
                  Edit purpose
                </button>
              </>
            )}
          </div>
          <PanelList title="Rules so far" empty="No rules yet.">
            {fields.rules.map((rule) => (
              <li key={rule.id}>
                {rule.text}{" "}
                <span className="text-xs">
                  ({rule.kind}, {rule.status}, {SOURCE_WORDS[rule.source]})
                </span>
              </li>
            ))}
          </PanelList>
          <PanelList title="Limits" empty="None yet.">
            {fields.limits.map((item) => (
              <li key={item.id}>{item.text}</li>
            ))}
          </PanelList>
          <PanelList title="Data that must never appear" empty="None yet.">
            {fields.protected_data.map((item) => (
              <li key={item.id}>{item.text}</li>
            ))}
          </PanelList>
          <PanelList title="Tools" empty="None yet.">
            {fields.tools.map((tool) => (
              <li key={tool.name}>
                {tool.name} ({tool.effect}): {tool.description}
              </li>
            ))}
          </PanelList>
          {fields.unclear.length > 0 && (
            <PanelList title="Unclear topics" empty="">
              {fields.unclear.map((topic) => (
                <li key={topic}>{topic}</li>
              ))}
            </PanelList>
          )}
          <PanelList title="Examples you gave" empty="None yet.">
            {fields.examples.map((item) => (
              <li key={item.id}>
                [{item.label.replace("_", " ")}] {item.text}
              </li>
            ))}
          </PanelList>
          <PanelList title="Uploaded files" empty="None yet.">
            {view.files.map((file) => (
              <li key={file.name}>
                {file.name}{" "}
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={async () => {
                    await api.call("DELETE", `/setups/${id}/files/${encodeURIComponent(file.name)}`);
                    await refresh();
                  }}
                  className={BUTTON}
                >
                  Remove
                </button>
              </li>
            ))}
          </PanelList>

          <label className="block space-y-1">
            <span className="block font-medium">
              Upload a context or skills file (text, markdown or JSON)
            </span>
            <input
              type="file"
              accept=".txt,.md,.markdown,.json"
              onChange={(event) => void upload(event.target.files?.[0])}
            />
          </label>
          <div className="space-y-1">
            <label className="block space-y-1">
              <span className="block font-medium">Paste an example</span>
              <textarea
                value={example}
                onChange={(event) => setExample(event.target.value)}
                className={FIELD}
              />
            </label>
            <label className="block space-y-1">
              <span className="block font-medium">This example is</span>
              <select
                value={exampleLabel}
                onChange={(event) => setExampleLabel(event.target.value)}
                className={FIELD}
              >
                <option value="conversation">a conversation to learn from</option>
                <option value="bad_reply">a reply that went wrong</option>
                <option value="good_reply">a reply that was right</option>
              </select>
            </label>
            <button type="button" onClick={addExample} className={BUTTON}>
              Add example
            </button>
          </div>
        </section>

        <section className="space-y-3 rounded border-2 p-4 text-sm">
          <h2 className="text-lg font-semibold">The two contexts</h2>
          <p>
            One tells the AI that writes the tests how to attack. The other tells the AI judge what
            counts as a violation.
          </p>
          <button type="button" onClick={buildContexts} className={BUTTON}>
            {contexts ? "Regenerate contexts" : "Build the two contexts"}
          </button>
          {contexts && (
            <>
              <section aria-label="Tester context" role="region" className="space-y-1 rounded border-2 p-3">
                <h3 className="font-semibold">Tester context</h3>
                <p>Purpose: {contexts.tester.purpose || "—"}</p>
                <TaggedList title="Likely weak spots" items={contexts.tester.weak_spots} />
                <TaggedList title="What to try" items={contexts.tester.what_to_try} />
              </section>
              <section aria-label="Judge context" role="region" className="space-y-1 rounded border-2 p-3">
                <h3 className="font-semibold">Judge context</h3>
                <p>Purpose: {contexts.judge.purpose || "—"}</p>
                <TaggedList title="Rules" items={contexts.judge.rules} />
                <TaggedList title="Limits" items={contexts.judge.limits} />
                <TaggedList title="Data that must never appear" items={contexts.judge.protected_data} />
              </section>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function PanelList({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: React.ReactNode[];
}) {
  return (
    <div className="space-y-1">
      <h3 className="font-medium">{title}</h3>
      {children.length === 0 ? (
        empty && <p className="text-xs">{empty}</p>
      ) : (
        <ul aria-label={title} className="list-disc space-y-1 pl-5">
          {children}
        </ul>
      )}
    </div>
  );
}

function TaggedList({ title, items }: { title: string; items: { text: string; source: string }[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="font-medium">{title}</p>
      <ul className="list-disc pl-5">
        {items.map((item, index) => (
          <li key={index}>
            {item.text} <span className="text-xs">({item.source === "user" ? "you said it" : "worked out by AI"})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --- the rules screen -------------------------------------------------------------------------

function RulesStage({
  api,
  view,
  refresh,
  setProblem,
  onVersion,
  versionHolder,
  onBack,
}: {
  api: SetupApi;
  view: SetupView;
  refresh: () => Promise<void>;
  setProblem: (value: string | null) => void;
  onVersion: (tests: GeneratedTest[]) => void;
  versionHolder: (number: number) => void;
  onBack: () => void;
}) {
  const [newRule, setNewRule] = useState("");
  const [newKind, setNewKind] = useState("forbidden");
  const [newSeverity, setNewSeverity] = useState("high");
  const id = view.setup_id;

  async function addRule() {
    if (!newRule.trim()) return;
    const result = await api.call("POST", `/setups/${id}/rules`, {
      text: newRule,
      kind: newKind,
      severity: newSeverity,
      status: "stated",
    });
    if (!result.ok) setProblem(describeError(result.status, result.data as never));
    setNewRule("");
    await refresh();
  }

  async function confirmAll() {
    setProblem(null);
    const saved = await api.call<{ version: number }>("POST", `/setups/${id}/confirm`);
    if (!saved.ok) {
      setProblem(describeError(saved.status, saved.data as never));
      return;
    }
    versionHolder(saved.data.version);
    const made = await api.call<{ tests: GeneratedTest[] }>(
      "POST",
      `/setups/${id}/versions/${saved.data.version}/tests`,
    );
    if (!made.ok) {
      setProblem(describeError(made.status, made.data as never));
      return;
    }
    onVersion(made.data.tests);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Review the rules</h2>
      <p className="text-sm">
        These are the rules we understood. The AI judge uses them to decide whether your bot broke
        one. Edit, delete or confirm any of them, and fix the unclear ones, before any test is
        written.
      </p>
      <ul aria-label="Rules" className="space-y-3">
        {view.fields.rules.map((rule) => (
          <RuleCard key={rule.id} rule={rule} api={api} setupId={id} refresh={refresh} setProblem={setProblem} />
        ))}
      </ul>
      <div className="space-y-2 rounded border-2 p-3">
        <label className="block space-y-1">
          <span className="block text-sm font-medium">New rule</span>
          <input value={newRule} onChange={(event) => setNewRule(event.target.value)} className={FIELD} />
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-medium">Type</span>
          <select value={newKind} onChange={(event) => setNewKind(event.target.value)} className={FIELD}>
            <option value="forbidden">Forbidden</option>
            <option value="allowed">Allowed</option>
          </select>
        </label>
        <label className="block space-y-1">
          <span className="block text-sm font-medium">Severity</span>
          <select value={newSeverity} onChange={(event) => setNewSeverity(event.target.value)} className={FIELD}>
            <option value="critical">critical</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
          </select>
        </label>
        <button type="button" onClick={addRule} className={BUTTON}>
          Add rule
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={confirmAll} className={PRIMARY}>
          Confirm the rules and save a version
        </button>
        <button type="button" onClick={onBack} className={BUTTON}>
          Back to the setup
        </button>
      </div>
    </div>
  );
}

function RuleCard({
  rule,
  api,
  setupId,
  refresh,
  setProblem,
}: {
  rule: Rule;
  api: SetupApi;
  setupId: number;
  refresh: () => Promise<void>;
  setProblem: (value: string | null) => void;
}) {
  const [text, setText] = useState(rule.text);
  const tone = rule.status === "stated" ? "green" : "yellow";
  async function act(method: string, path: string, body?: unknown) {
    const result = await api.call(method, `/setups/${setupId}/rules/${rule.id}${path}`, body);
    if (!result.ok) setProblem(describeError(result.status, result.data as never));
    await refresh();
  }
  return (
    <li
      aria-label={`Rule: ${rule.text}`}
      data-tone={tone}
      className={`space-y-2 rounded border-2 p-3 text-sm ${TONE_CLASS[tone]}`}
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-semibold">{rule.kind === "forbidden" ? "Forbidden" : "Allowed"}</span>
        <span className="rounded border-2 px-2 py-0.5 text-xs font-semibold">
          {rule.status.toUpperCase()}
        </span>
        <span className="text-xs">severity {rule.severity}</span>
      </div>
      {rule.question && <p>Question that would settle it: {rule.question}</p>}
      <label className="block space-y-1">
        <span className="sr-only">Rule text</span>
        <input aria-label="Rule text" value={text} onChange={(event) => setText(event.target.value)} className={FIELD} />
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => act("PUT", "", { text })} className={BUTTON}>
          Save rule
        </button>
        {rule.status !== "stated" && (
          <button
            type="button"
            aria-label={`Confirm rule: ${rule.text}`}
            onClick={() => act("POST", "/confirm")}
            className={BUTTON}
          >
            Confirm
          </button>
        )}
        <button
          type="button"
          aria-label={`Delete rule: ${rule.text}`}
          onClick={() => act("DELETE", "")}
          className={BUTTON}
        >
          Delete
        </button>
      </div>
    </li>
  );
}

// --- the select page ---------------------------------------------------------------------------

function TestsStage({
  api,
  setupId,
  version,
  onTestsChange,
  tests,
  ticked,
  setTicked,
  keyValue,
  setKey,
  onRun,
  setProblem,
}: {
  api: SetupApi;
  setupId: number;
  version: number;
  onTestsChange: (tests: GeneratedTest[]) => void;
  tests: GeneratedTest[];
  ticked: Set<string>;
  setTicked: (value: Set<string>) => void;
  keyValue: string;
  setKey: (value: string) => void;
  onRun: () => Promise<void>;
  setProblem: (value: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    api.call<{ strategies: Strategy[] }>("GET", "/strategies").then((result) => {
      if (!cancelled && result.ok) setStrategies(result.data.strategies);
    });
    return () => {
      cancelled = true;
    };
  }, [api]);

  // Only ticked attack tests are varied, and a variation is never varied again.
  const variable = tests.filter((t) => t.kind === "negative" && !t.strategy && ticked.has(t.id));

  async function addVariations() {
    setProblem(null);
    const result = await api.call<{ added: GeneratedTest[]; tests: GeneratedTest[] }>(
      "POST",
      `/setups/${setupId}/versions/${version}/tests/variations`,
      { strategies: [...chosen], base_ids: variable.map((t) => t.id) },
    );
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    onTestsChange(result.data.tests);
    setTicked(new Set([...ticked, ...result.data.added.map((t) => t.id)]));
    setChosen(new Set());
  }

  function toggleStrategy(id: string) {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  }

  function toggle(id: string) {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTicked(next);
  }
  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Choose the tests to run</h2>
      <p className="text-sm">
        Nothing runs until you confirm. Each test sends one message to your bot, and an AI judge
        reads the reply. The judge has not been checked for accuracy, and for a real bot it decides
        from the reply alone.
      </p>
      <ul aria-label="Generated tests" className="space-y-3">
        {tests.map((test) => (
          <li key={test.id} aria-label={`Test: ${test.title}`} className="space-y-2 rounded border-2 p-3 text-sm">
            <label className="flex items-center gap-2 font-semibold">
              <input
                type="checkbox"
                checked={ticked.has(test.id)}
                onChange={() => toggle(test.id)}
              />
              <span>Run {test.title}</span>
            </label>
            <p className="text-xs">
              {test.kind === "positive" ? "Normal request" : `${test.risk} · severity ${test.severity}`}
            </p>
            {test.multi_turn && <p className="text-xs font-semibold">Several turns</p>}
            {test.variation_of && (
              <p className="text-xs">
                Variation of: {tests.find((t) => t.id === test.variation_of)?.title ?? test.variation_of}
              </p>
            )}
            <p>
              <span className="font-semibold">The message we will send:</span> {test.prompt}
            </p>
            <p>
              <span className="font-semibold">What we are trying to find out:</span> {test.goal}
            </p>
            <p>
              <span className="font-semibold">What a correct reply looks like:</span> {test.expected}
            </p>
            <div className="flex flex-wrap gap-2">
              {test.rule_unconfirmed && (
                <span className={`rounded border-2 px-2 py-0.5 text-xs font-semibold ${TONE_CLASS.yellow}`}>
                  Rule not confirmed
                </span>
              )}
              {test.real_action && (
                <span className={`rounded border-2 px-2 py-0.5 text-xs font-semibold ${TONE_CLASS.red}`}>
                  Could trigger a real action
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
      <section aria-label="Add attack variations" role="region" className="space-y-2 rounded border-2 p-3 text-sm">
        <h3 className="font-semibold">Add attack variations</h3>
        <p>
          A real attacker rewrites the same request to get past a refusal. Pick ways to disguise
          your ticked attack tests. Each pick adds a rewritten copy of every ticked attack test.
        </p>
        <ul className="space-y-1">
          {strategies.map((strategy) => (
            <li key={strategy.id}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={chosen.has(strategy.id)}
                  onChange={() => toggleStrategy(strategy.id)}
                />
                <span>
                  <span className="font-medium">{strategy.name}</span>
                  <span className="block text-xs">{strategy.description}</span>
                  {strategy.multi_turn && (
                    <span className="block text-xs font-semibold">
                      Uses several turns and more requests, so it takes longer and uses more quota.
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={addVariations}
          disabled={chosen.size === 0 || variable.length === 0}
          className={BUTTON}
        >
          Add variations
        </button>
      </section>
      <p>
        {ticked.size} of {tests.length} tests ticked
      </p>
      <label className="block space-y-1">
        <span className="block text-sm font-medium">API key for the run</span>
        <input
          type="password"
          autoComplete="off"
          value={keyValue}
          onChange={(event) => setKey(event.target.value)}
          className={FIELD}
        />
      </label>
      <button
        type="button"
        disabled={ticked.size === 0 || busy}
        onClick={async () => {
          setBusy(true);
          setProblem(null);
          try {
            await onRun();
          } finally {
            setBusy(false);
          }
        }}
        className={PRIMARY}
      >
        Confirm and run {ticked.size} {ticked.size === 1 ? "test" : "tests"}
      </button>
    </div>
  );
}
