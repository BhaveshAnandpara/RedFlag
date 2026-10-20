"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { parseConnection } from "@/lib/connect-parse";
import type { ScanDetail, ScanListItem } from "@/lib/scan";
import { describeError, type Endpoint } from "@/lib/setup";
import { SetupApi } from "@/lib/setup-api";

import { FinishedScan } from "./finished-scan";
import { RunningView } from "./setup-page";

type Platform = "openai" | "flowise" | "paste" | "other";
type BotType = "chatbot" | "agent";
type Hello = { sig: string; status: "ok" | "error"; reply: string; error: string };

const FIELD = "w-full rounded border-2 border-zinc-500 bg-white p-2 text-black";
const BUTTON = "rounded border-2 px-3 py-1 text-sm disabled:opacity-50";
const PRIMARY =
  "rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-black";

const PLATFORMS: { id: Platform; label: string; hint: string }[] = [
  { id: "openai", label: "OpenAI-compatible", hint: "OpenAI, Groq, Open WebUI, Ollama and similar" },
  { id: "flowise", label: "Flowise", hint: "A chatflow with a prediction address" },
  { id: "paste", label: "Paste anything", hint: "A link, a key, a code sample or a curl command" },
  { id: "other", label: "Other (custom)", hint: "Fill in the details yourself" },
];

const TYPES: { id: BotType; label: string }[] = [
  { id: "chatbot", label: "A chatbot that answers questions" },
  { id: "agent", label: "An agent that can also take actions" },
];

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="block space-y-1">
      <span className="block text-sm font-medium">{label}</span>
      <input
        type={type}
        value={value}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
        className={FIELD}
      />
    </label>
  );
}

export function QuickScanPage({ apiUrl, pollMs = 2000 }: { apiUrl: string; pollMs?: number }) {
  const [password, setPassword] = useState("");
  const [api, setApi] = useState<SetupApi | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [rules, setRules] = useState<Record<BotType, string[]>>({ chatbot: [], agent: [] });

  const [platform, setPlatform] = useState<Platform | null>(null);
  const [address, setAddress] = useState("");
  const [model, setModel] = useState("");
  const [chatflow, setChatflow] = useState("");
  // The key lives only here, in memory: sent with the hello check and the run, never stored.
  const [key, setKey] = useState("");
  const [format, setFormat] = useState<"openai" | "custom">("openai");
  const [headerName, setHeaderName] = useState("Authorization");
  const [headerPrefix, setHeaderPrefix] = useState("Bearer ");
  const [template, setTemplate] = useState("");
  const [replyPath, setReplyPath] = useState("");
  const [pasted, setPasted] = useState("");
  const [readNote, setReadNote] = useState<string | null>(null);

  const [hello, setHello] = useState<Hello | null>(null);
  const [confirmedSig, setConfirmedSig] = useState<string | null>(null);
  const [deniedSig, setDeniedSig] = useState<string | null>(null);

  const [botType, setBotType] = useState<BotType | null>(null);
  const [purpose, setPurpose] = useState("");
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const [custom, setCustom] = useState<string[]>([]);
  const [draftRule, setDraftRule] = useState("");
  const [sandbox, setSandbox] = useState(false);

  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [history, setHistory] = useState<ScanListItem[]>([]);
  const [previous, setPrevious] = useState<ScanDetail | null>(null);
  const [setupId, setSetupId] = useState<number | null>(null);
  const stopped = useRef(false);

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
    setApi(probe);
    const listed = await probe.call<{ rules: Record<BotType, string[]> }>("GET", "/quick-scans/rules");
    if (listed.ok) setRules(listed.data.rules);
  }

  // --- the connection ----------------------------------------------------------------------

  function endpoint(): Endpoint {
    const base = address.trim().replace(/\/+$/, "");
    if (platform === "flowise") {
      return {
        url: `${base}/api/v1/prediction/${chatflow.trim()}`,
        format: "custom",
        model: "default",
        header_name: "Authorization",
        header_prefix: "Bearer ",
        request_template: '{"question": "{{prompt}}"}',
        reply_path: "text",
      };
    }
    const isOpenAI = platform === "openai" || format === "openai";
    const url = isOpenAI && !/\/chat\/completions$/.test(base) ? `${base}/chat/completions` : base;
    return {
      url,
      format: isOpenAI ? "openai" : "custom",
      model: model.trim() || "default",
      header_name: platform === "openai" ? "Authorization" : headerName.trim() || "Authorization",
      header_prefix: platform === "openai" ? "Bearer " : headerPrefix,
      request_template: isOpenAI ? null : template.trim() || null,
      reply_path: isOpenAI ? null : replyPath.trim() || null,
    };
  }

  const signature = JSON.stringify([endpoint(), key]);
  const canSayHello = address.trim() !== "" && (platform !== "flowise" || chatflow.trim() !== "");
  const confirmed = confirmedSig === signature;
  const shownHello = hello && hello.sig === signature ? hello : null;

  function readPasted() {
    const parsed = parseConnection(pasted);
    setPasted("");
    if (parsed.found.length === 0) {
      setReadNote("We could not find a bot address in that. Paste a link or a curl command, or fill the details in below.");
      return;
    }
    if (parsed.url) setAddress(parsed.url);
    if (parsed.key) setKey(parsed.key);
    if (parsed.model) setModel(parsed.model);
    if (parsed.format) setFormat(parsed.format);
    if (parsed.headerName) setHeaderName(parsed.headerName);
    if (parsed.headerPrefix !== undefined) setHeaderPrefix(parsed.headerPrefix);
    if (parsed.requestTemplate) setTemplate(parsed.requestTemplate);
    if (parsed.replyPath) setReplyPath(parsed.replyPath);
    const missing = parsed.missing.length ? ` Still needed: ${parsed.missing.join(", ")}.` : "";
    setReadNote(`We found: ${parsed.found.join(", ")}.${missing}`);
  }

  async function sayHello() {
    if (!api) return;
    setProblem(null);
    const sig = signature;
    const result = await api.call<{ status: "ok" | "error"; parsed_reply: string; error: string }>(
      "POST",
      "/quick-scans/check",
      { endpoint: endpoint(), key: key || null },
    );
    if (!result.ok) {
      setProblem(describeError(result.status, result.data as never));
      return;
    }
    setHello({
      sig,
      status: result.data.status,
      reply: result.data.parsed_reply,
      error: result.data.error,
    });
  }

  // --- the rules ----------------------------------------------------------------------------

  const baseRules = botType ? rules[botType] : [];
  const allRules = [...baseRules, ...custom];
  const chosen = allRules.filter((rule) => !unticked.has(rule));
  const ready =
    botType !== null &&
    purpose.trim() !== "" &&
    chosen.length > 0 &&
    (botType === "chatbot" || sandbox);

  function toggle(rule: string) {
    setUnticked((current) => {
      const next = new Set(current);
      if (next.has(rule)) next.delete(rule);
      else next.add(rule);
      return next;
    });
  }

  function addRule() {
    const text = draftRule.trim();
    if (!text || allRules.includes(text)) return;
    setCustom([...custom, text]);
    setDraftRule("");
  }

  // --- the run --------------------------------------------------------------------------------

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
      setPrevious(null);
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
            `/scans?bot_id=${body.scan.bot_id}`,
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

  async function run() {
    if (!api || !botType) return;
    setProblem(null);
    const started = await api.call<{ setup_id: number; scan_id: number }>("POST", "/quick-scans", {
      endpoint: endpoint(),
      key: key || null,
      bot_type: botType,
      purpose: purpose.trim(),
      must_never: chosen,
      sandbox_confirmed: botType === "agent" && sandbox,
    });
    if (!started.ok) {
      setProblem(describeError(started.status, started.data as never));
      return;
    }
    setSetupId(started.data.setup_id);
    await follow(started.data.scan_id);
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

  // --- the page -------------------------------------------------------------------------------

  return (
    <section className="space-y-6">
      <h1 className="text-3xl font-semibold">Quick scan</h1>

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
      ) : scan ? (
        <div className="space-y-4">
          {problem && <p role="alert">{problem}</p>}
          {scan.scan.status === "running" ? (
            <RunningView detail={scan} />
          ) : (
            <>
              <FinishedScan
                api={api}
                scan={scan}
                history={history}
                previous={previous}
                keyValue={key}
                setKey={setKey}
                onRunAgain={(id) => void runAgain(id)}
                onOpen={(id) => void openScan(id)}
                loadScan={fetchScan}
                setProblem={setProblem}
              />
              <p className="text-sm">
                {setupId !== null && <>Saved as setup #{setupId}. </>}
                <Link href="/setup" className="underline">
                  Tailor these tests
                </Link>{" "}
                to your bot by describing it in a chat.
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-8">
          <p>
            A starter pack of tests, run on your bot in one go. It is a first check, not proof that
            your bot is secure.
          </p>
          {problem && <p role="alert">{problem}</p>}

          <div className="space-y-3">
            <h2 className="text-lg font-semibold">1. Connect your bot</h2>
            <div role="radiogroup" aria-label="How is your bot built?" className="grid gap-2 sm:grid-cols-2">
              {PLATFORMS.map((item) => (
                <label key={item.id} className="flex items-start gap-2 rounded border-2 p-3">
                  <input
                    type="radio"
                    name="platform"
                    checked={platform === item.id}
                    onChange={() => setPlatform(item.id)}
                  />
                  <span>
                    <span className="block font-medium">{item.label}</span>
                    <span className="block text-sm">{item.hint}</span>
                  </span>
                </label>
              ))}
              <label className="flex items-start gap-2 rounded border-2 border-dashed p-3 opacity-60">
                <input type="radio" name="platform" disabled />
                <span>A chat window on my website — coming soon</span>
              </label>
            </div>

            {platform === "paste" && (
              <div className="space-y-2">
                <label className="block space-y-1">
                  <span className="block text-sm font-medium">
                    Paste a link, a key, a code sample or a curl command
                  </span>
                  <textarea
                    value={pasted}
                    onChange={(event) => setPasted(event.target.value)}
                    rows={4}
                    className={FIELD}
                  />
                </label>
                <button type="button" onClick={readPasted} disabled={!pasted.trim()} className={BUTTON}>
                  Read it
                </button>
                {readNote && <p role="status">{readNote}</p>}
              </div>
            )}

            {platform === "flowise" && (
              <div className="space-y-2">
                <Field label="Flowise address" value={address} onChange={setAddress} />
                <Field label="Chatflow ID" value={chatflow} onChange={setChatflow} />
                <Field
                  label="Access key (if the chatflow has one)"
                  value={key}
                  onChange={setKey}
                  type="password"
                />
              </div>
            )}

            {platform === "openai" && (
              <div className="space-y-2">
                <Field label="API address" value={address} onChange={setAddress} />
                <Field label="Model name" value={model} onChange={setModel} />
                <Field label="Access key" value={key} onChange={setKey} type="password" />
              </div>
            )}

            {(platform === "paste" || platform === "other") && (
              <div className="space-y-2">
                <Field label="API address" value={address} onChange={setAddress} />
                <label className="block space-y-1">
                  <span className="block text-sm font-medium">Message format</span>
                  <select
                    value={format}
                    onChange={(event) => setFormat(event.target.value as "openai" | "custom")}
                    className={FIELD}
                  >
                    <option value="openai">Chat completions style</option>
                    <option value="custom">Custom body</option>
                  </select>
                </label>
                {format === "openai" ? (
                  <Field label="Model name" value={model} onChange={setModel} />
                ) : (
                  <>
                    <Field label="Request template" value={template} onChange={setTemplate} />
                    <Field label="Reply path" value={replyPath} onChange={setReplyPath} />
                  </>
                )}
                <Field label="Key header name" value={headerName} onChange={setHeaderName} />
                <Field label="Key header prefix" value={headerPrefix} onChange={setHeaderPrefix} />
                <Field label="Access key" value={key} onChange={setKey} type="password" />
              </div>
            )}

            {platform && (
              <>
                <button type="button" onClick={sayHello} disabled={!canSayHello} className={BUTTON}>
                  Say hello
                </button>
                {shownHello?.status === "error" && <p role="status">{shownHello.error}</p>}
                {shownHello?.status === "ok" && !confirmed && deniedSig !== signature && (
                  <div className="space-y-2">
                    <p>Your bot answered: “{shownHello.reply}”</p>
                    <p>Is this your bot&apos;s answer?</p>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => setConfirmedSig(signature)} className={BUTTON}>
                        Yes, that&apos;s my bot&apos;s answer
                      </button>
                      <button type="button" onClick={() => setDeniedSig(signature)} className={BUTTON}>
                        No, that&apos;s not right
                      </button>
                    </div>
                  </div>
                )}
                {deniedSig === signature && (
                  <p role="status">
                    Then check the address, the key and the model name, and say hello again.
                  </p>
                )}
              </>
            )}
          </div>

          {confirmed && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">What kind of bot is it?</h2>
              <div role="radiogroup" aria-label="Kind of bot" className="grid gap-2 sm:grid-cols-2">
                {TYPES.map((item) => (
                  <label key={item.id} className="flex items-center gap-2 rounded border-2 p-3">
                    <input
                      type="radio"
                      name="bot-type"
                      checked={botType === item.id}
                      onChange={() => setBotType(item.id)}
                    />
                    {item.label}
                  </label>
                ))}
              </div>

              <Field label="What is it for? (one sentence)" value={purpose} onChange={setPurpose} />

              {botType && (
                <fieldset className="space-y-2">
                  <legend className="font-medium">What must it never do?</legend>
                  {allRules.map((rule) => (
                    <label key={rule} className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={!unticked.has(rule)}
                        onChange={() => toggle(rule)}
                      />
                      {rule}
                    </label>
                  ))}
                  <div className="flex items-end gap-2">
                    <div className="grow">
                      <Field label="Add your own rule" value={draftRule} onChange={setDraftRule} />
                    </div>
                    <button type="button" onClick={addRule} className={BUTTON}>
                      Add rule
                    </button>
                  </div>
                </fieldset>
              )}

              {botType === "agent" && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={sandbox}
                    onChange={(event) => setSandbox(event.target.checked)}
                  />
                  This is a test or sandbox environment, not production
                </label>
              )}
            </div>
          )}

          {confirmed && (
            <button type="button" onClick={run} disabled={!ready} className={PRIMARY}>
              Run starter pack
            </button>
          )}
        </div>
      )}
    </section>
  );
}
