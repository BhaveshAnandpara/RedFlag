"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  attackStats,
  compareScans,
  conclusion,
  criticalFailures,
  countByStatus,
  isRealBot,
  judgeState,
  type JudgeState,
  judgeSummary,
  NO_JUDGE_LINE,
  overallTone,
  riskBars,
  ruleOutput,
  runDelta,
  UNCHECKED_JUDGE_LINE,
} from "@/lib/analytics";
import { buildReport } from "@/lib/report";
import { reportHtml } from "@/lib/report-html";
import type {
  JudgeAccuracy,
  Labeling,
  ScanDetail,
  ScanListItem,
  ScanResult,
  Status,
} from "@/lib/scan";

import { Donut, RiskBars } from "./dashboard-charts";
import { JUDGE_WORD, JudgeBadge, STATUS_WORD, StatusBadge, TONE_CLASS } from "./status";

const TABS = ["Overview", "Tests", "Conversations", "Compare", "History"] as const;
type Tab = (typeof TABS)[number];

const SEVERITY_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2 };

function severityText(result: ScanResult): string {
  if (result.kind === "positive") return "normal request";
  return result.severity ?? "not rated";
}

function severityRank(result: ScanResult): number {
  if (result.kind === "positive") return 4;
  return result.severity ? SEVERITY_ORDER[result.severity] : 3;
}

function when(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

export type DashboardProps = {
  detail: ScanDetail;
  history: ScanListItem[];
  onOpen: (scanId: number) => void;
  loadScan: (scanId: number) => Promise<ScanDetail>;
  // A scan the Compare tab opens already compared with (the public page uses it).
  defaultCompareId?: number;
  // The scan before this one, to show what changed since the last run.
  previous?: ScanDetail | null;
  // Saving the owner's labels of the judge's verdicts. Without it there is no Label mode.
  labeling?: Labeling;
};

export function Dashboard({
  detail,
  history,
  onOpen,
  loadScan,
  defaultCompareId,
  previous,
  labeling,
}: DashboardProps) {
  const [tab, setTab] = useState<Tab>("Overview");
  const [printNote, setPrintNote] = useState<string | null>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function move(next: Tab) {
    setTab(next);
    tabRefs.current[next]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.indexOf(tab);
    if (event.key === "ArrowRight") move(TABS[(index + 1) % TABS.length]);
    else if (event.key === "ArrowLeft") move(TABS[(index + TABS.length - 1) % TABS.length]);
    else if (event.key === "Home") move(TABS[0]);
    else if (event.key === "End") move(TABS[TABS.length - 1]);
    else return;
    event.preventDefault();
  }

  async function accuracyForReport(): Promise<JudgeAccuracy | null> {
    if (!labeling) return null;
    try {
      return await labeling.loadAccuracy();
    } catch {
      return null;
    }
  }

  async function printReport() {
    setPrintNote(null);
    const win = window.open("", "_blank");
    if (!win) {
      setPrintNote(
        "Your browser blocked the print window. Allow pop-ups for this site, or use Download report.",
      );
      return;
    }
    const accuracy = await accuracyForReport();
    win.document.write(
      reportHtml(buildReport(detail, accuracy), `Redflag scan #${detail.scan.id}`),
    );
    win.document.close();
    win.focus();
    win.print();
  }

  async function downloadReport() {
    const blob = new Blob([buildReport(detail, await accuracyForReport())], {
      type: "text/markdown",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `redflag-scan-${detail.scan.id}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const { scan } = detail;
  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold">Scan #{scan.id}</h2>
          <p>
            {scan.settings.bot_name} · Status: {scan.status} · Started {when(scan.started_at)}
          </p>
          {scan.note && <p>{scan.note}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => void downloadReport()} className="rounded border-2 px-3 py-2 text-sm">
            Download report
          </button>
          <button type="button" onClick={() => void printReport()} className="rounded border-2 px-3 py-2 text-sm">
            Print or save as PDF
          </button>
        </div>
        {printNote && <p role="status" className="basis-full text-sm">{printNote}</p>}
      </header>

      <div role="tablist" aria-label="Scan results" className="flex flex-wrap gap-2">
        {TABS.map((name) => (
          <button
            key={name}
            ref={(element) => {
              tabRefs.current[name] = element;
            }}
            id={`tab-${name}`}
            role="tab"
            type="button"
            aria-selected={tab === name}
            aria-controls={`panel-${name}`}
            tabIndex={tab === name ? 0 : -1}
            onClick={() => setTab(name)}
            onKeyDown={onKeyDown}
            className={`rounded border-2 px-3 py-2 text-sm ${
              tab === name ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-black" : ""
            }`}
          >
            {name}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "Overview" && <Overview detail={detail} previous={previous ?? null} />}
        {tab === "Tests" && <TestsTable results={detail.results} risks={detail.summary.risks} />}
        {tab === "Conversations" && (
          <Conversations
            results={detail.results}
            realBot={isRealBot(detail)}
            labeling={labeling}
          />
        )}
        {tab === "Compare" && (
          <Compare
            detail={detail}
            history={history}
            loadScan={loadScan}
            defaultId={defaultCompareId}
          />
        )}
        {tab === "History" && <History current={scan.id} history={history} onOpen={onOpen} />}
      </div>
    </div>
  );
}

function Overview({ detail, previous }: { detail: ScanDetail; previous: ScanDetail | null }) {
  const text = conclusion(detail);
  const tone = overallTone(detail);
  const critical = criticalFailures(detail.results);
  const { scan } = detail;
  const { settings } = scan;
  const bars = useMemo(() => riskBars(detail.summary.risks), [detail.summary.risks]);
  return (
    <div className="space-y-6">
      <div
        data-testid="conclusion"
        data-tone={tone}
        className={`space-y-2 rounded border-2 p-4 ${TONE_CLASS[tone]}`}
      >
        <p className="text-lg font-semibold">{text.headline}</p>
        {text.details.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {text.details.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        <p className="text-sm font-semibold">{text.closing}</p>
      </div>

      {previous && <SinceLastRun detail={detail} previous={previous} />}

      <p role="note" aria-label="About the AI judge" className="rounded border-2 p-3 text-sm">
        {judgeSummary(detail.results).ran
          ? `${UNCHECKED_JUDGE_LINE} If either the plain rules or the AI judge fails a test, the test fails.`
          : NO_JUDGE_LINE}
      </p>

      <section aria-label="Results" className="space-y-2">
        <h3 className="font-semibold">Results</h3>
        <Donut counts={countByStatus(detail.results)} />
      </section>

      <section aria-label="Critical failures" className="space-y-2">
        <h3 className="font-semibold">Critical failures</h3>
        {critical.length === 0 ? (
          <p className="text-sm">No test rated critical failed.</p>
        ) : (
          <ul className="space-y-2">
            {critical.map((result) => (
              <li
                key={result.test_id}
                className={`space-y-1 rounded border-2 p-2 text-sm ${TONE_CLASS.red}`}
              >
                <p className="font-semibold">{result.title}</p>
                <p>{result.evidence}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Risks" className="space-y-2">
        <h3 className="font-semibold">What this scan checked and did not check</h3>
        <RiskBars bars={bars} />
        {detail.summary.atlas && (
          <p role="note" aria-label="About the ATLAS tags" className="text-xs">
            ATLAS tags are Redflag&apos;s own best match between each OWASP risk and MITRE ATLAS
            techniques, not a claim of coverage ({detail.summary.atlas.version}, checked{" "}
            {detail.summary.atlas.checked},{" "}
            <a href={detail.summary.atlas.source} className="underline">
              atlas.mitre.org
            </a>
            ).
          </p>
        )}
      </section>

      <section
        aria-label="Settings this scan ran with"
        className="space-y-1 rounded border-2 p-4 text-sm"
      >
        <h3 className="font-semibold">Settings this scan ran with</h3>
        <p>
          Bot: {settings.bot_name} (config version {settings.bot_config_version}) · Defenses on:{" "}
          {settings.bot_defenses.length > 0 ? settings.bot_defenses.join(", ") : "none"}
        </p>
        <p>
          Models that answered: {scan.models_used.length > 0 ? scan.models_used.join(", ") : "none"}
        </p>
        {settings.setup ? (
          <p>
            Setup version {settings.setup.version} · Target: {settings.setup.target_host} · Tests run:{" "}
            {settings.test_count} · Risk list: {detail.summary.catalog_version}
          </p>
        ) : (
          <p>
            Suite version: {settings.suite_version} · Tests: {settings.test_count} · Risk list:{" "}
            {detail.summary.catalog_version}
          </p>
        )}
        <p>
          Budget: up to {settings.budget.requests} requests and{" "}
          {settings.budget.tokens.toLocaleString("en-US")} tokens
        </p>
        {settings.canary && <p>Secret planted for this scan: {settings.canary}</p>}
      </section>
    </div>
  );
}

const STATUS_FILTERS: ("all" | Status)[] = [
  "all",
  "pass",
  "fail",
  "inconclusive",
  "error",
  "not_applicable",
];

function TestsTable({
  results,
  risks,
}: {
  results: ScanResult[];
  risks: { id: string; name: string }[];
}) {
  const [status, setStatus] = useState("all");
  const [risk, setRisk] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [bySeverity, setBySeverity] = useState(false);

  const present = new Set(results.map((r) => r.risk).filter(Boolean));
  const hasNormal = results.some((r) => r.kind === "positive");

  let rows = results.filter((r) => {
    if (status !== "all" && r.status !== status) return false;
    if (risk === "normal" ? r.kind !== "positive" : risk !== "all" && r.risk !== risk) return false;
    if (severity !== "all") {
      if (r.kind === "positive") return false;
      if (severity === "not_rated" ? Boolean(r.severity) : r.severity !== severity) return false;
    }
    return true;
  });
  if (bySeverity) rows = [...rows].sort((a, b) => severityRank(a) - severityRank(b));

  const select = "rounded border-2 border-zinc-500 bg-white p-1 text-black";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="space-y-1">
          <span className="block font-medium">Filter by result</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={select}>
            {STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {value === "all" ? "All results" : STATUS_WORD[value]}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block font-medium">Filter by risk</span>
          <select value={risk} onChange={(e) => setRisk(e.target.value)} className={select}>
            <option value="all">All risks</option>
            {risks
              .filter((r) => present.has(r.id))
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id} {r.name}
                </option>
              ))}
            {hasNormal && <option value="normal">Normal requests</option>}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block font-medium">Filter by severity</span>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} className={select}>
            <option value="all">All severities</option>
            <option value="critical">critical</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="not_rated">not rated</option>
          </select>
        </label>
      </div>

      <div className="overflow-x-auto">
        <table aria-label="Results table" className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b-2">
              <th className="p-2">Result</th>
              <th className="p-2">AI judge</th>
              <th className="p-2">Test</th>
              <th className="p-2">Risk</th>
              <th className="p-2">
                <button
                  type="button"
                  aria-pressed={bySeverity}
                  onClick={() => setBySeverity(!bySeverity)}
                  className="rounded border-2 px-2 py-0.5"
                >
                  Sort by severity
                </button>
                <span className="ml-2">Severity</span>
              </th>
              <th className="p-2">Model</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((result) => (
              <tr key={result.test_id} className="border-b">
                <td className="p-2">
                  <StatusBadge status={result.status} />
                </td>
                <td className="p-2">
                  <JudgeBadge state={judgeState(result)} />
                </td>
                <td className="p-2">{result.title}</td>
                <td className="p-2">{result.risk ?? "normal"}</td>
                <td className="p-2">{severityText(result)}</td>
                <td className="p-2">{result.model ?? "none"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="text-sm">No tests match those filters.</p>}
    </div>
  );
}

function LabelControls({
  result,
  label,
  onLabel,
}: {
  result: ScanResult;
  label: "pass" | "fail" | null;
  onLabel: (correct: "pass" | "fail" | null) => void;
}) {
  const verdict = result.judge_status;
  if (verdict !== "pass" && verdict !== "fail") {
    return <p className="text-sm">The judge gave no verdict here, so there is nothing to label.</p>;
  }
  const opposite = verdict === "pass" ? "fail" : "pass";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {label === null ? (
        <>
          <span>Was the judge&apos;s verdict ({verdict}) right?</span>
          <button type="button" onClick={() => onLabel(verdict)} className="rounded border-2 px-3 py-1">
            Judge was right
          </button>
          <button type="button" onClick={() => onLabel(opposite)} className="rounded border-2 px-3 py-1">
            Judge was wrong
          </button>
        </>
      ) : (
        <>
          <span>You marked the judge {label === verdict ? "right" : "wrong"}.</span>
          <button type="button" onClick={() => onLabel(null)} className="rounded border-2 px-3 py-1">
            Clear label
          </button>
        </>
      )}
    </div>
  );
}

function ConversationItem({
  result,
  realBot,
  label,
  onLabel,
}: {
  result: ScanResult;
  realBot: boolean;
  label?: "pass" | "fail" | null;
  onLabel?: (correct: "pass" | "fail" | null) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li aria-label={`Test result: ${result.title}`} className="space-y-2 rounded border-2 p-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <StatusBadge status={result.status} />
        <span>{result.title}</span>
        <span className="text-xs">{result.risk ?? "normal request"}</span>
        <span className="text-xs">{severityText(result)}</span>
      </div>
      {onLabel && <LabelControls result={result} label={label ?? null} onLabel={onLabel} />}
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
          {result.turns && result.turns.length > 0 ? (
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase">
                Conversation: {Math.ceil(result.turns.length / 2)}{" "}
                {Math.ceil(result.turns.length / 2) === 1 ? "turn" : "turns"}
              </p>
              <ul aria-label="Conversation turns" className="space-y-1">
                {result.turns.map((turn, index) => (
                  <li key={index} className="whitespace-pre-wrap">
                    {turn.role === "user" ? "Tester" : "Bot"}: {turn.content}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <>
              <div>
                <p className="text-xs font-semibold uppercase">Message sent</p>
                <p className="whitespace-pre-wrap">{result.message}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase">Reply</p>
                <p className="whitespace-pre-wrap">{result.reply || "(no reply)"}</p>
              </div>
            </>
          )}
          <div>
            <p className="text-xs font-semibold uppercase">What the bot did (tool-call log)</p>
            {realBot ? (
              <p>The tool log is not available for this kind of target.</p>
            ) : result.tool_calls.length === 0 ? (
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
          <JudgeBlocks result={result} />
          <p>
            <span className="font-semibold">Rule:</span> {result.rule}
          </p>
          <p>
            <span className="font-semibold">How to fix:</span>{" "}
            {result.remediation ?? "No fix note was recorded for this result."}
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

function JudgeBlocks({ result }: { result: ScanResult }) {
  const state = judgeState(result);
  if (state === "not_run") {
    return <p>The AI judge did not run on this test. Only the plain rules decided it.</p>;
  }
  // A real bot has no plain rules: the judge decided alone, so there is nothing to compare.
  if (result.rule_status == null) {
    return (
      <div className="space-y-2">
        <div role="group" aria-label="Plain rules" className="space-y-1 rounded border-2 p-2">
          <p className="text-xs font-semibold uppercase">Plain rules</p>
          <p>No plain rule applied to this bot. The AI judge decided alone.</p>
        </div>
        <JudgeBlock result={result} state={state} />
      </div>
    );
  }
  const rules = ruleOutput(result);
  const disagreed =
    (rules.status === "pass" || rules.status === "fail") &&
    (state === "pass" || state === "fail") &&
    rules.status !== state;
  return (
    <div className="space-y-2">
      <div className="grid gap-2 md:grid-cols-2">
        <div role="group" aria-label="Plain rules" className="space-y-1 rounded border-2 p-2">
          <p className="text-xs font-semibold uppercase">Plain rules</p>
          <StatusBadge status={rules.status} />
          <p>{rules.evidence}</p>
        </div>
        <JudgeBlock result={result} state={state} />
      </div>
      {disagreed && (
        <p className="font-semibold">
          The plain rules and the AI judge disagreed. If either fails a test, the test fails.
        </p>
      )}
    </div>
  );
}

function SinceLastRun({ detail, previous }: { detail: ScanDetail; previous: ScanDetail }) {
  const delta = runDelta(detail, previous);
  const groups: [string, { id: string; title: string }[], string][] = [
    ["Fixed", delta.fixed, "green"],
    ["New problems", delta.newProblems, "red"],
    ["Still failing", delta.stillFailing, "red"],
    ["Now unclear", delta.unclearNow, "yellow"],
    ["No longer run", delta.noLongerRun, "grey"],
  ];
  return (
    <section
      aria-label="Since the last run"
      role="region"
      className="space-y-2 rounded border-2 p-4 text-sm"
    >
      <h3 className="font-semibold">{delta.summary}</h3>
      <p className="text-xs">
        A fixed test only means it passed this time. A model can answer differently each run.
      </p>
      {groups
        .filter(([, items]) => items.length > 0)
        .map(([name, items, tone]) => (
          <div key={name} className="space-y-1">
            <p className="font-medium">{name}</p>
            <ul aria-label={name} className="list-disc pl-5">
              {items.map((item) => (
                <li key={item.id} data-tone={tone}>
                  {item.title}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </section>
  );
}

function JudgeBlock({ result, state }: { result: ScanResult; state: JudgeState }) {
  return (
    <div role="group" aria-label="AI judge" className="space-y-1 rounded border-2 p-2">
      <p className="text-xs font-semibold uppercase">AI judge</p>
      <span
        data-tone={state === "unavailable" ? "yellow" : state === "fail" ? "red" : "green"}
        className="inline-block text-xs font-semibold"
      >
        {JUDGE_WORD[state]}
      </span>
      <p>{result.judge_reason ?? "No reason was recorded."}</p>
      {result.judge_model && (
        <p className="text-xs">
          Answered by {result.judge_provider} ({result.judge_model})
        </p>
      )}
    </div>
  );
}

function Conversations({
  results,
  realBot,
  labeling,
}: {
  results: ScanResult[];
  realBot: boolean;
  labeling?: Labeling;
}) {
  const [labels, setLabels] = useState<Record<string, "pass" | "fail" | null>>(() =>
    Object.fromEntries(results.map((r) => [r.test_id, r.label ?? null])),
  );
  const [accuracy, setAccuracy] = useState<JudgeAccuracy | null>(null);
  const [failed, setFailed] = useState(false);

  async function refresh() {
    if (!labeling) return;
    try {
      setAccuracy(await labeling.loadAccuracy());
    } catch {
      setFailed(true);
    }
  }

  useEffect(() => {
    let alive = true;
    labeling
      ?.loadAccuracy()
      .then((loaded) => alive && setAccuracy(loaded))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
    // The page passes a new object each render; loading once per opening of the tab is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(testId: string, correct: "pass" | "fail" | null) {
    if (!labeling) return;
    try {
      await labeling.setLabel(testId, correct);
      setLabels((current) => ({ ...current, [testId]: correct }));
      await refresh();
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="space-y-4">
      {labeling && <AccuracyPanel accuracy={accuracy} failed={failed} />}
      <ul aria-label="Conversations" className="space-y-3">
        {results.map((result) => (
          <ConversationItem
            key={result.test_id}
            result={result}
            realBot={realBot}
            label={labels[result.test_id] ?? null}
            onLabel={labeling ? (correct) => void save(result.test_id, correct) : undefined}
          />
        ))}
      </ul>
    </div>
  );
}

const percent = (value: number) => `${Math.round(value * 100)}%`;

function AccuracyPanel({ accuracy, failed }: { accuracy: JudgeAccuracy | null; failed: boolean }) {
  return (
    <section aria-label="Judge accuracy" role="region" className="space-y-2 rounded border-2 p-3 text-sm">
      <h3 className="font-semibold">Judge accuracy</h3>
      {failed && <p>Could not save or load labels. Nothing was changed.</p>}
      {accuracy === null ? (
        <p>Loading…</p>
      ) : accuracy.agreement === null ? (
        <p>{accuracy.note}</p>
      ) : (
        <>
          <p>
            Agreed with you on {accuracy.agree} of {accuracy.counted} labeled results (
            {percent(accuracy.agreement)})
          </p>
          <p>
            False alarms: {accuracy.false_alarms} (the judge failed a reply you say was fine).
            Misses: {accuracy.misses} (the judge passed a reply you say broke the rule).
          </p>
          {accuracy.small_sample && (
            <p>
              This is a small sample (fewer than {accuracy.min_sample} labeled results), so treat
              it as a hint, not a measure.
            </p>
          )}
          <table className="w-full text-left">
            <thead>
              <tr>
                <th className="p-1">Risk</th>
                <th className="p-1">Agreed</th>
                <th className="p-1">False alarms</th>
                <th className="p-1">Misses</th>
              </tr>
            </thead>
            <tbody>
              {accuracy.risks.map((risk) => (
                <tr key={risk.risk}>
                  <td className="p-1">{risk.risk}</td>
                  <td className="p-1">
                    {risk.agree} of {risk.counted}
                    {risk.small_sample ? " (small sample)" : ""}
                  </td>
                  <td className="p-1">{risk.false_alarms}</td>
                  <td className="p-1">{risk.misses}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>{accuracy.note}</p>
        </>
      )}
    </section>
  );
}

function Compare({
  detail,
  history,
  loadScan,
  defaultId,
}: {
  detail: ScanDetail;
  history: ScanListItem[];
  loadScan: DashboardProps["loadScan"];
  defaultId?: number;
}) {
  const [other, setOther] = useState<ScanDetail | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [selected, setSelected] = useState(defaultId === undefined ? "" : String(defaultId));

  // When the tab opens already pointed at a scan, load it.
  useEffect(() => {
    if (defaultId === undefined) return;
    let cancelled = false;
    loadScan(defaultId)
      .then((scan) => {
        if (!cancelled) setOther(scan);
      })
      .catch(() => {
        if (!cancelled) setProblem("Could not load that scan.");
      });
    return () => {
      cancelled = true;
    };
  }, [defaultId, loadScan]);

  async function choose(value: string) {
    setSelected(value);
    setProblem(null);
    if (!value) {
      setOther(null);
      return;
    }
    try {
      setOther(await loadScan(Number(value)));
    } catch {
      setProblem("Could not load that scan.");
    }
  }

  const choices = history.filter((item) => item.id !== detail.scan.id);
  const comparison = other ? compareScans(detail, other) : null;
  return (
    <div className="space-y-4">
      <label className="block space-y-1 text-sm">
        <span className="block font-medium">Compare with</span>
        <select
          value={selected}
          onChange={(event) => choose(event.target.value)}
          className="rounded border-2 border-zinc-500 bg-white p-1 text-black"
        >
          <option value="">Choose a scan</option>
          {choices.map((item) => (
            <option key={item.id} value={item.id}>
              Scan #{item.id} · {item.bot_id} · {item.status}
            </option>
          ))}
        </select>
      </label>
      {problem && <p role="alert">{problem}</p>}

      {other && comparison && (
        <div className="space-y-3 text-sm">
          <h3 className="font-semibold">
            Scan #{detail.scan.id} ({detail.scan.settings.bot_name}) compared with Scan #
            {other.scan.id} ({other.scan.settings.bot_name})
          </h3>
          <p
            className={`rounded border-2 p-3 font-semibold ${
              TONE_CLASS[comparison.sameModels ? "green" : "yellow"]
            }`}
          >
            {comparison.modelStatement}
          </p>
          {comparison.judgeStatement && <p>{comparison.judgeStatement}</p>}
          {comparison.ruleChanges && (
            <div>
              <h4 className="font-semibold">Rules that changed between the two setup versions</h4>
              {comparison.ruleChanges.added.length === 0 &&
              comparison.ruleChanges.removed.length === 0 ? (
                <p>No rule changed.</p>
              ) : (
                <ul aria-label="Rules that changed" className="list-disc pl-5">
                  {comparison.ruleChanges.added.map((text) => (
                    <li key={`added-${text}`}>Added in the second scan: {text}</li>
                  ))}
                  {comparison.ruleChanges.removed.map((text) => (
                    <li key={`removed-${text}`}>Missing from the second scan: {text}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {comparison.suiteVersionsDiffer && (
            <p>
              These scans ran different versions of the test library (version{" "}
              {detail.scan.settings.suite_version} and version {other.scan.settings.suite_version}),
              so some tests may appear in only one of them.
            </p>
          )}
          <p>
            Attack tests that failed: {attackStats(detail.results).failed} of{" "}
            {attackStats(detail.results).tested} in the first scan, and{" "}
            {attackStats(other.results).failed} of {attackStats(other.results).tested} in the
            second.
          </p>
          <div>
            <h4 className="font-semibold">Tests that changed result</h4>
            {comparison.changed.length === 0 ? (
              <p>No test changed result.</p>
            ) : (
              <ul aria-label="Tests that changed" className="list-disc pl-5">
                {comparison.changed.map((change) => (
                  <li key={change.test_id}>
                    {change.title}: {STATUS_WORD[change.from]} to {STATUS_WORD[change.to]}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {comparison.onlyInFirst.length > 0 && (
            <div>
              <h4 className="font-semibold">In the first scan only</h4>
              <ul className="list-disc pl-5">
                {comparison.onlyInFirst.map((title) => (
                  <li key={title}>{title}</li>
                ))}
              </ul>
            </div>
          )}
          {comparison.onlyInSecond.length > 0 && (
            <div>
              <h4 className="font-semibold">In the second scan only</h4>
              <ul className="list-disc pl-5">
                {comparison.onlyInSecond.map((title) => (
                  <li key={title}>{title}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function History({
  current,
  history,
  onOpen,
}: {
  current: number;
  history: ScanListItem[];
  onOpen: (scanId: number) => void;
}) {
  if (history.length === 0) return <p className="text-sm">No scans yet.</p>;
  return (
    <ul aria-label="Scan history" className="space-y-2">
      {history.map((item) => (
        <li key={item.id} className="flex flex-wrap items-baseline gap-3 rounded border-2 p-3">
          <span>
            Scan #{item.id} · {item.bot_id} · {item.status} · {item.counts.fail} failed
            {item.id === current ? " · shown now" : ""}
          </span>
          <button
            type="button"
            aria-label={`Open scan #${item.id}`}
            onClick={() => onOpen(item.id)}
            className="rounded border-2 px-3 py-1 text-sm"
          >
            Open
          </button>
        </li>
      ))}
    </ul>
  );
}
