"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import {
  botModel,
  judgeModels,
  mcpGroup,
  mcpModel,
  mcpTool,
  pct,
  seconds,
  when,
  type Cover,
} from "@/lib/report-model";
import { buildReport } from "@/lib/report";
import type { ScanDetail, ScanResult, Status } from "@/lib/scan";

type Look = "pass" | "fail" | "unclear" | "grey";

const look = (status: Status): Look =>
  status === "pass" ? "pass" : status === "fail" ? "fail" : status === "inconclusive" ? "unclear" : "grey";
const WORD: Record<Status, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "UNCLEAR",
  error: "ERROR",
  not_applicable: "N/A",
};
const CLOSING = "This is not a guarantee of security. It only reports what these tests checked.";

/** Content arrives as the page is scrolled, unless the person asked for less motion. */
function Rise({ children, as: Tag = "div", className = "", ...rest }: { children: ReactNode; as?: "div" | "section"; className?: string } & Record<string, unknown>) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && (setSeen(true), io.disconnect())),
      { threshold: 0.08 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <Tag ref={ref as any} className={`${className} rise ${seen ? "in" : ""}`.trim()} {...rest}>
      {children}
    </Tag>
  );
}

const Badge = ({ status }: { status: Status }) => <span className={`badge ${look(status)}`}>{WORD[status]}</span>;
const SevTag = ({ s }: { s?: string | null }) => <span className={`sev ${s || "none"}`}>{s || "not rated"}</span>;

export function ReportView({ detail }: { detail: ScanDetail }) {
  const mcp = detail.scan.settings.mcp !== undefined;
  return <main className="d-report">{mcp ? <McpReport detail={detail} /> : <BotReport detail={detail} />}</main>;
}

// ---------- shared pieces ----------

function useReportActions(detail: ScanDetail) {
  const [toast, setToast] = useState<string | null>(null);
  const say = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 1800);
  };
  return {
    toast,
    copy: async () => {
      try {
        await navigator.clipboard.writeText(location.href);
        say("Link copied");
      } catch {
        say("Copy failed");
      }
    },
    download: () => {
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([buildReport(detail)], { type: "text/markdown" }));
      link.download = `redflag-scan-${detail.scan.id}.md`;
      link.click();
      URL.revokeObjectURL(link.href);
    },
  };
}

function TitleRow({ crumb, title, actions }: { crumb: string; title: string; actions: ReturnType<typeof useReportActions> }) {
  return (
    <Rise className="titlerow">
      <div>
        <div className="crumb">
          <a href="/results.html">Results</a> / {crumb}
        </div>
        <h1>{title}</h1>
      </div>
      <div className="actions">
        <button type="button" className="btn ghost" onClick={actions.copy}>
          Copy link
        </button>
        <button type="button" className="btn solid" onClick={actions.download}>
          Download report
        </button>
      </div>
    </Rise>
  );
}

function FlagRow({ items, onOpen }: { items: { id: string; look: Look; word: string; title: string; label: string }[]; onOpen: (id: string) => void }) {
  const [live, setLive] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setLive(true));
    return () => cancelAnimationFrame(frame);
  }, []);
  return (
    <div className={`flagrow ${live ? "live" : ""}`} id="flagrow">
      {items.map((item, i) => (
        <a
          key={item.id}
          className={`fl ${item.look === "unclear" ? "grey" : item.look}`}
          href={`#t-${item.id}`}
          style={{ "--n": i } as CSSProperties}
          data-tip={`${item.word} · ${item.title}`}
          aria-label={`${item.label} ${i + 1}: ${item.word}`}
          onClick={(e) => {
            e.preventDefault();
            onOpen(item.id);
          }}
        >
          <i />
          <b />
        </a>
      ))}
    </div>
  );
}

function CoverCard({ rows, unit }: { rows: Cover[]; unit: (c: Cover) => string }) {
  return (
    <section className="card cover">
      {rows.map((c) => {
        const attempted = c.n + (c.u ?? 0);
        return (
          <div className="cv" key={`${c.id}-${c.name}`}>
            <span className="id">{c.id}</span>
            <span className="nm">{c.name}</span>
            {attempted ? (
              <>
                <span className="bar">
                  {Array.from({ length: Math.min(attempted, 16) }, (_, k) => {
                    const shown = Math.min(attempted, 16);
                    const failTicks = Math.ceil((c.f * shown) / attempted);
                    const undecidedTicks = Math.ceil(((c.u ?? 0) * shown) / attempted);
                    const style = k < failTicks ? undefined : k < failTicks + undecidedTicks ? { background: "var(--amber)" } : undefined;
                    return <i key={k} className={k < failTicks ? "f" : ""} style={style} />;
                  })}
                </span>
                <span className="ct">{unit(c)}</span>
              </>
            ) : (
              <span className="nt">not tested</span>
            )}
          </div>
        );
      })}
    </section>
  );
}

function Finding({
  result,
  open,
  onToggle,
  evidence,
  children,
}: {
  result: ScanResult;
  open: boolean;
  onToggle: (open: boolean) => void;
  evidence: string;
  children: ReactNode;
}) {
  return (
    <details
      className="item failed"
      id={`t-${result.test_id}`}
      open={open}
      onToggle={(e) => onToggle((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>
        <SevTag s={result.severity} />
        <span className="s-title">
          {result.title}
          <small>{result.risk}</small>
        </span>
        <span className="chev">›</span>
        <span className="s-ev">{evidence}</span>
        <span className="s-fix">
          <b>Fix</b>
          {result.remediation ?? "—"}
        </span>
      </summary>
      {children}
    </details>
  );
}

function RuleFix({ rule, fix }: { rule: string; fix: string | null | undefined }) {
  return (
    <div className="rulefix">
      <div>
        <span>Rule</span>
        {rule}
      </div>
      <div>
        <span>How to fix</span>
        {fix || "—"}
      </div>
    </div>
  );
}

function Settings({ title, hint, rows }: { title: string; hint: string; rows: [string, ReactNode][] }) {
  return (
    <details className="card settings">
      <summary>
        <span>{title}</span>
        <span className="mono" style={{ color: "var(--faint)", fontSize: 12 }}>
          {hint}
        </span>
      </summary>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function Toast({ text }: { text: string | null }) {
  return (
    <div className={`toast ${text ? "on" : ""}`} role="status">
      {text}
    </div>
  );
}

/** Opens a finding when its flag is clicked, or the matching table row. */
function useOpening(onRow: (id: string) => void) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const set = (id: string, on: boolean) =>
    setOpen((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const reveal = (id: string, hasFinding: boolean) => {
    if (hasFinding) {
      set(id, true);
      requestAnimationFrame(() => document.getElementById(`t-${id}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" }));
    } else {
      onRow(id);
      requestAnimationFrame(() => document.getElementById(`row-${id}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" }));
    }
  };
  return { open, set, reveal };
}

// ---------- a scan of the visitor's own bot ----------

function BotDetail({ r }: { r: ScanResult }) {
  const turns = r.turns && r.turns.length > 0 ? r.turns : null;
  return (
    <div className="detail">
      {turns ? (
        <div className="dl">
          <span>Conversation</span>
          {turns.map((t, i) => (
            <div key={i} className={`quote ${t.role === "user" ? "att" : ""}`}>
              {t.role === "user" ? "Tester" : "Your bot"}: {t.content}
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="dl">
            <span>Message sent</span>
            <div className="quote att">{r.message}</div>
          </div>
          <div className="dl">
            <span>Your bot&apos;s reply</span>
            <div className="quote">{r.reply || "(no reply)"}</div>
          </div>
        </>
      )}
      <div className="dl">
        <span>Tool log</span>
        <div className="quote" style={{ color: "var(--faint)" }}>
          None. Redflag can only see your bot&apos;s replies, not what it did behind them.
        </div>
      </div>
      <div className="jb">
        <div className="h">
          AI judge <Badge status={r.status} />
        </div>
        {r.judge_reason ?? r.evidence}
        <span style={{ fontSize: 12, color: "var(--faint)" }}>
          The AI judge read the reply against your rule. It has not been checked for accuracy.
        </span>
      </div>
      <RuleFix rule={r.rule} fix={r.remediation} />
    </div>
  );
}

function BotReport({ detail }: { detail: ScanDetail }) {
  const m = botModel(detail);
  const actions = useReportActions(detail);
  const { scan, results } = detail;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const opening = useOpening((id) => setExpanded((c) => new Set(c).add(id)));
  const [fRes, setFRes] = useState<"all" | "fail" | "pass">("all");
  const [fRisk, setFRisk] = useState("");
  const [fSev, setFSev] = useState("");
  const rows = results.filter(
    (r) =>
      (fRes === "all" || r.status === fRes) &&
      (!fRisk || (fRisk === "normal" ? r.kind === "positive" : r.risk === fRisk)) &&
      (!fSev || (fSev === "none" ? !r.severity : r.severity === fSev)),
  );
  const target = scan.settings.setup?.target_host;
  const judges = judgeModels(results);
  const host = target ?? scan.settings.bot_name;

  return (
    <>
      <TitleRow crumb={`quick scan #${scan.id}`} title={`Your bot · quick scan #${scan.id}`} actions={actions} />

      <Rise as="section" className="card verdict" aria-labelledby="v-h" style={{ "--glow": m.failed.length ? 0.14 : 0.04 } as CSSProperties}>
        <h2 id="v-h">
          {m.failed.length ? (
            <>
              <span className="bad">
                {m.failed.length} of {m.attacks.length}
              </span>{" "}
              attacks got through. {m.critical} {m.critical === 1 ? "was" : "were"} critical.
            </>
          ) : (
            <>
              0 of {m.attacks.length} attacks got through. {m.untested} of 10 risks were not tested.
            </>
          )}
        </h2>
        <div className="vsub">
          {m.normalOk} of {m.normal.length} normal requests worked.
        </div>
        <FlagRow
          items={results.map((r) => ({
            id: r.test_id,
            look: look(r.status),
            word: r.status === "fail" ? "got through" : r.status === "pass" ? "held" : "unclear",
            title: r.title,
            label: "Test",
          }))}
          onOpen={(id) => opening.reveal(id, m.failed.some((f) => f.test_id === id))}
        />
        <div className="vmeta">
          <span>
            Started <b>{when(scan.started_at)}</b>
          </span>
          <span>
            <b>{seconds(detail)} s</b>
          </span>
          {judges.length > 0 && (
            <span>
              AI judge <b>{judges.join(", ")}</b>
            </span>
          )}
          <span>
            Target <b>{host}</b>
          </span>
        </div>
        <div className="vnotes">
          <span>
            Attack success rate {pct(m.rate)} (95% range {pct(m.lo)} to {pct(m.hi)}). Small sample:{" "}
            {m.attacks.length} attacks.
          </span>
          <span>{m.untested} of 10 OWASP risks were not tested by this suite.</span>
          <span>Every result was decided by the AI judge, which has not been checked for accuracy.</span>
          <span className="closing">{CLOSING}</span>
        </div>
      </Rise>

      <Rise className="sec-head">
        <h2>{m.failed.length ? "Fix these first" : "Nothing got through"}</h2>
        <span>{m.failed.length ? `${m.failed.length} failed · critical first` : "no finding does not mean the bot is safe"}</span>
      </Rise>
      <Rise className="fixes">
        {m.failed.map((r) => (
          <Finding
            key={r.test_id}
            result={r}
            open={opening.open.has(r.test_id)}
            onToggle={(on) => opening.set(r.test_id, on)}
            evidence={(r.judge_reason ?? r.evidence).replace(" or the tool log", "")}
          >
            <BotDetail r={r} />
          </Finding>
        ))}
      </Rise>

      <Rise className="sec-head">
        <h2>What was and wasn&apos;t tested</h2>
        <span>OWASP Top 10 for LLM apps · 2025</span>
      </Rise>
      <Rise>
        <CoverCard rows={m.cover} unit={(c) => (c.f ? `${c.f} of ${c.n} got through` : `${c.n} held`)} />
      </Rise>

      <Rise className="sec-head">
        <h2>All tests</h2>
        <span id="t-count">
          {rows.length} of {results.length} tests
        </span>
      </Rise>
      <Rise className="filters" role="group" aria-label="Filter tests">
        {(
          [
            ["all", "All"],
            ["fail", "Got through"],
            ["pass", "Held"],
          ] as const
        ).map(([id, label]) => (
          <button key={id} type="button" className="chip" aria-pressed={fRes === id} onClick={() => setFRes(id)}>
            {label}
          </button>
        ))}
        <select className="sel" aria-label="Risk" value={fRisk} onChange={(e) => setFRisk(e.target.value)}>
          <option value="">Every risk</option>
          {m.tested.map((r) => (
            <option key={r}>{r}</option>
          ))}
          <option value="normal">Normal requests</option>
        </select>
        <select className="sel" aria-label="Severity" value={fSev} onChange={(e) => setFSev(e.target.value)}>
          <option value="">Every severity</option>
          <option>critical</option>
          <option>high</option>
          <option>medium</option>
          <option value="none">not rated</option>
        </select>
      </Rise>
      <Rise as="section" className="card tablewrap">
        <table>
          <thead>
            <tr>
              <th>Result</th>
              <th>Test</th>
              <th className="t-risk">Risk</th>
              <th>Severity</th>
              <th className="t-model">Decided by</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="nomatch">
                  No tests match those filters.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <RowPair
                key={r.test_id}
                id={r.test_id}
                expanded={expanded.has(r.test_id)}
                toggle={() =>
                  setExpanded((c) => {
                    const next = new Set(c);
                    if (!next.delete(r.test_id)) next.add(r.test_id);
                    return next;
                  })
                }
                cells={
                  <>
                    <td>
                      <Badge status={r.status} />
                    </td>
                    <td>{r.title}</td>
                    <td className="mono t-risk">{r.risk ?? "normal"}</td>
                    <td>
                      <SevTag s={r.kind === "positive" ? null : r.severity} />
                    </td>
                    <td className="mono t-model">AI judge</td>
                  </>
                }
              >
                <BotDetail r={r} />
              </RowPair>
            ))}
          </tbody>
        </table>
      </Rise>

      <Rise>
        <Settings
          title="Scan details"
          hint="settings this scan ran with"
          rows={[
            ["Target", host],
            ["Test suite", `${results.length} tests · ${scan.settings.catalog_version}`],
            ["AI judge", judges.length ? judges.join(", ") : "none recorded"],
            ["Budget", `${scan.settings.budget.requests} requests to your bot`],
            ["Access key", "Used for this scan only. Not stored."],
          ]}
        />
      </Rise>
      <Toast text={actions.toast} />
    </>
  );
}

function RowPair({
  id,
  expanded,
  toggle,
  cells,
  children,
}: {
  id: string;
  expanded: boolean;
  toggle: () => void;
  cells: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <tr className="row" id={`row-${id}`} onClick={toggle} aria-expanded={expanded}>
        {cells}
      </tr>
      {expanded && (
        <tr className="exp">
          <td colSpan={5}>{children}</td>
        </tr>
      )}
    </>
  );
}

// ---------- a check of an MCP server ----------

function McpDetail({ r }: { r: ScanResult }) {
  if (mcpGroup(r.test_id) === "static") {
    const [summary, ...toolLines] = r.evidence.split("\n");
    return (
      <div className="detail">
        <div className="dl">
          <span>What was checked</span>
          <div className="quote">{r.message}</div>
        </div>
        <div className="jb">
          <div className="h">
            Plain rules <Badge status={r.status} />
          </div>
          {summary}
          {toolLines.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, display: "grid", gap: 4, listStyle: "disc" }}>
              {toolLines.map((line) => (
                <li key={line} style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>
        <RuleFix rule={r.rule} fix={r.remediation} />
      </div>
    );
  }
  if (r.status === "not_applicable") {
    return (
      <div className="detail">
        <div className="dl">
          <span>Nothing was called</span>
          <div className="quote">{r.evidence}</div>
        </div>
      </div>
    );
  }
  return (
    <div className="detail">
      <div className="dl">
        <span>What Redflag sent</span>
        <div className="quote att mono">{r.message}</div>
      </div>
      <div className="dl">
        <span>What the tool sent back</span>
        <div className="quote mono">{r.reply || "(nothing)"}</div>
      </div>
      <div className="jb">
        <div className="h">
          AI judge <Badge status={r.status} />
        </div>
        {r.judge_reason ?? r.evidence}
        <span style={{ fontSize: 12, color: "var(--faint)" }}>
          {r.status === "inconclusive" ? "Unclear is not a pass. " : ""}
          {r.judge_model ? `Judged by ${r.judge_model}. ` : ""}The AI judge has not been checked for accuracy.
        </span>
      </div>
      <RuleFix rule={r.rule} fix={r.remediation} />
    </div>
  );
}

function McpReport({ detail }: { detail: ScanDetail }) {
  const m = mcpModel(detail);
  const actions = useReportActions(detail);
  const { scan, results } = detail;
  const mcp = scan.settings.mcp!;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const opening = useOpening((id) => setExpanded((c) => new Set(c).add(id)));
  const [fRes, setFRes] = useState<"all" | "fail" | "pass" | "inconclusive">("all");
  const [fKind, setFKind] = useState("");
  const [fTool, setFTool] = useState("");
  const [fSev, setFSev] = useState("");
  const rows = results.filter(
    (r) =>
      (fRes === "all" || r.status === fRes) &&
      (!fKind || mcpGroup(r.test_id) === fKind) &&
      (!fTool || mcpTool(r.test_id) === fTool) &&
      (!fSev || r.severity === fSev),
  );
  const name = mcp.server.name || mcp.target_host;
  const judges = judgeModels(results);
  const calledMap = Object.fromEntries(m.called.map((c) => [c.name, c.effect]));
  const toolsInResults = [...new Set(m.toolNames)];
  const limits = mcp.limits;
  const decider = (r: ScanResult) =>
    mcpGroup(r.test_id) === "static" ? "plain rules" : r.status === "not_applicable" ? "—" : "AI judge";

  return (
    <>
      <TitleRow crumb={`MCP check #${scan.id}`} title={`${name} · MCP check #${scan.id}`} actions={actions} />

      <Rise as="section" className="card verdict" aria-labelledby="v-h" style={{ "--glow": m.failed.length ? 0.14 : 0.04 } as CSSProperties}>
        <h2 id="v-h">
          {m.failed.length ? (
            <>
              <span className="bad">
                {m.failed.length} of {m.decided.length}
              </span>{" "}
              checks failed. {m.critical} {m.critical === 1 ? "was" : "were"} critical.
            </>
          ) : (
            <>0 of {m.decided.length} checks failed.</>
          )}
        </h2>
        <div className="vsub">
          {m.flaggedTools.size} of {m.toolCount} tool descriptions had problems.{" "}
          {m.calls.length
            ? `${m.callFails} of ${m.decidedCalls.length} manipulated calls that got a real answer got through, on ${m.called.length} ticked ${m.called.length === 1 ? "tool" : "tools"}.${
                m.undecidedCalls ? ` ${m.undecidedCalls} more could not be completed.` : ""
              }`
            : "No tool was ticked, so no tool was called."}
        </div>
        <FlagRow
          items={results.map((r) => ({
            id: r.test_id,
            look: look(r.status),
            word: WORD[r.status].toLowerCase(),
            title: r.title,
            label: "Check",
          }))}
          onOpen={(id) => opening.reveal(id, m.failed.some((f) => f.test_id === id))}
        />
        <div className="vmeta">
          <span>
            Server <b>{mcp.target_host}</b>
          </span>
          <span>
            Checked <b>{when(scan.started_at)}</b>
          </span>
          <span>
            <b>{seconds(detail)} s</b>
          </span>
          {judges.length > 0 && (
            <span>
              AI judge <b>{judges.join(", ")}</b>
            </span>
          )}
        </div>
        <div className="vnotes">
          {m.unclear > 0 && (
            <span>
              {m.unclear} {m.unclear === 1 ? "result is" : "results are"} unclear: the AI judge gave no verdict.
              Unclear is not a pass.
            </span>
          )}
          <span>
            This is a check of an MCP server. The description and schema checks use plain rules that look for
            known patterns. Redflag only called the tools you ticked, and an AI judge read what each tool sent
            back.
          </span>
          <span>The AI judge has not been checked for accuracy.</span>
          <span className="closing">{CLOSING}</span>
        </div>
      </Rise>

      <Rise className="sec-head">
        <h2>{m.failed.length ? "Fix these first" : "Nothing failed"}</h2>
        <span>
          {m.failed.length ? `${m.failed.length} failed · critical first` : "no finding does not mean the server is safe"}
        </span>
      </Rise>
      <Rise className="fixes">
        {m.failed.map((r) => (
          <Finding
            key={r.test_id}
            result={r}
            open={opening.open.has(r.test_id)}
            onToggle={(on) => opening.set(r.test_id, on)}
            evidence={mcpGroup(r.test_id) === "call" ? (r.judge_reason ?? r.evidence) : r.evidence.split("\n")[0]}
          >
            <McpDetail r={r} />
          </Finding>
        ))}
      </Rise>

      <Rise className="sec-head">
        <h2>What Redflag touched</h2>
        <span>tools are only called if ticked</span>
      </Rise>
      <Rise className="touched">
        <section className="card called">
          <h3>
            Called<small>{m.called.length}</small>
          </h3>
          <p>
            Called with manipulated inputs{limits ? `, up to ${limits.calls_per_tool} calls each` : ""}.
            {m.changes.length > 0
              ? " Tools that change things were called because the server was confirmed as a test or sandbox."
              : ""}
          </p>
          {m.called.length ? (
            <ul>
              {m.called.map((c) => (
                <li key={c.name} className={`on ${c.effect === "acts" ? "chg" : ""}`}>
                  {c.name}
                </li>
              ))}
            </ul>
          ) : (
            <p>None.</p>
          )}
        </section>
        <section className="card called">
          <h3>
            Only read<small>{m.readOnly.length}</small>
          </h3>
          <p>Only the description and inputs were checked. These tools were never called.</p>
          {m.readOnly.length ? (
            <ul>
              {m.readOnly.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : (
            <p>None: every tool was ticked.</p>
          )}
        </section>
      </Rise>

      <Rise className="sec-head">
        <h2>What was and wasn&apos;t tested</h2>
        <span>descriptions: every tool · calls: ticked tools</span>
      </Rise>
      <Rise>
        <CoverCard
          rows={m.cover}
          unit={(c) => {
            const unit = c.name.startsWith("Calls") ? "calls" : "tools";
            const decided = c.f
              ? `${c.f} of ${c.n} ${unit} failed`
              : c.n
                ? `${c.n} ${unit} decided, none failed`
                : "none decided";
            return c.u ? `${decided} · ${c.u} not completed` : decided;
          }}
        />
      </Rise>

      <Rise className="sec-head">
        <h2>All checks</h2>
        <span id="t-count">
          {rows.length} of {results.length} checks
        </span>
      </Rise>
      <Rise className="filters" role="group" aria-label="Filter checks">
        {(
          [
            ["all", "All"],
            ["fail", "Failed"],
            ["pass", "Passed"],
            ...(m.unclear ? [["inconclusive", "Unclear"]] : []),
          ] as [typeof fRes, string][]
        ).map(([id, label]) => (
          <button key={id} type="button" className="chip" aria-pressed={fRes === id} onClick={() => setFRes(id)}>
            {label}
          </button>
        ))}
        <select className="sel" aria-label="Check" value={fKind} onChange={(e) => setFKind(e.target.value)}>
          <option value="">Every check</option>
          <option value="static">Descriptions and inputs</option>
          <option value="call">Manipulated calls</option>
        </select>
        <select className="sel" aria-label="Tool" value={fTool} onChange={(e) => setFTool(e.target.value)}>
          <option value="">Every tool</option>
          {toolsInResults.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
        <select className="sel" aria-label="Severity" value={fSev} onChange={(e) => setFSev(e.target.value)}>
          <option value="">Every severity</option>
          <option>critical</option>
          <option>high</option>
          <option>medium</option>
        </select>
      </Rise>
      <Rise as="section" className="card tablewrap">
        <table>
          <thead>
            <tr>
              <th>Result</th>
              <th>Check</th>
              <th className="t-risk">Risk</th>
              <th>Severity</th>
              <th className="t-model">Decided by</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="nomatch">
                  No checks match those filters.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <RowPair
                key={r.test_id}
                id={r.test_id}
                expanded={expanded.has(r.test_id)}
                toggle={() =>
                  setExpanded((c) => {
                    const next = new Set(c);
                    if (!next.delete(r.test_id)) next.add(r.test_id);
                    return next;
                  })
                }
                cells={
                  <>
                    <td>
                      <Badge status={r.status} />
                    </td>
                    <td>{r.title}</td>
                    <td className="mono t-risk">{r.risk}</td>
                    <td>
                      <SevTag s={r.status === "pass" && mcpGroup(r.test_id) === "static" ? null : r.severity} />
                    </td>
                    <td className="mono t-model">{decider(r)}</td>
                  </>
                }
              >
                <McpDetail r={r} />
              </RowPair>
            ))}
          </tbody>
        </table>
      </Rise>

      <Rise as="section" className="card next">
        <div>
          <h3>Check this server again</h3>
          <p>
            After you change a description or a tool, run the same checks to see what changed. The key is
            needed again because Redflag never stores it.
          </p>
        </div>
        <a className="btn solid" href="/mcp">
          Check again
        </a>
      </Rise>

      <Rise>
        <Settings
          title="Check details"
          hint="settings this check ran with"
          rows={[
            ["Server", `${name} · https://${mcp.target_host}`],
            ["Tools on the server", String(m.toolCount)],
            [
              "Tools called",
              m.called.length
                ? m.called.map((c) => `${c.name} (${calledMap[c.name] === "acts" ? "changes things" : "only reads"})`).join(", ")
                : "none",
            ],
            [
              "Test or sandbox server",
              m.changes.length ? "Confirmed before the run" : "Not needed: no ticked tool changes things",
            ],
            ["Limits", limits ? `${limits.calls_per_tool} calls per tool · ${limits.calls_per_run} calls per run` : "recorded with newer checks"],
            ["AI judge", judges.length ? judges.join(", ") : "none recorded"],
            ["Access key", "Used for this check only. Not stored."],
          ]}
        />
      </Rise>
      <Toast text={actions.toast} />
    </>
  );
}
