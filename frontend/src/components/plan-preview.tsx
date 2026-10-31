"use client";

import { useEffect, useRef, useState } from "react";

import { problemFor } from "@/lib/open-api";
import type { SetupApi } from "@/lib/setup-api";

/** One thing that really happened while the plan was made: a step, or a finished test. */
type Item =
  | { seq: number; kind: "status" | "goal" | "wait"; text: string }
  | {
      seq: number;
      kind: "test";
      text: string;
      persona: string;
      persona_id: string;
      goal: string;
      changes_data: boolean;
    };
/** An item on the timeline, with the beat it arrived in and its place in that beat. */
type Shown = Item & { batch: number; slot: number };
type PlanView = {
  summary: { ideas: number; repeats_removed: number; tests: number; data_changing: number };
  blocked: string | null;
  rules_covered: string[];
  skipped: { persona: string; goal: string; reason: string }[];
};
type Doing = {
  goal_index: number;
  goal_total: number;
  waiting: boolean;
  seconds_left: number;
  at: number;
};
type Reply =
  | ({ status: "running"; events: Item[]; next: number; total: number } & Omit<Doing, "at">)
  | { status: "done"; plan: PlanView }
  | { status: "error"; kind: string };

// One item every beat. Never faster than the beat, never slower than the longest beat.
const BEAT_MS = 2500;
const LONGEST_BEAT_MS = 6000;
// Even a quick plan is shown over about this long, so there is time to watch it being written.
const MIN_MS = 60_000;
// A plan waits out the models' per-minute quota, so it can take a while: ask for up to ~40 minutes.
const POLLS = 900;
const CONTACT_WARNING =
  "Our tests only point your AI at Redflag's own links and addresses, but we can't stop it from contacting anyone else it chooses.";

const failure = (kind: string) =>
  kind === "plan_timeout"
    ? "Planning took too long. Try again."
    : "We could not make the plan. Nothing was run. Try again.";

const PILL: Record<string, string> = {
  social_engineer: "se",
  fake_insider: "fi",
  content_poisoner: "cp",
  data_harvester: "dh",
  resource_abuser: "ra",
  qa_tester: "qa",
  normal_user: "nu",
};

const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

type Props = {
  api: SetupApi;
  environment: "staging" | "production";
  purpose: string;
  rules: string[];
  facts: unknown;
  server: string;
  beatMs?: number;
  minMs?: number;
};

/** Writes the test plan in front of the user: steps and test cards arrive one beat at a time. */
export function PlanPreview({
  api,
  environment,
  purpose,
  rules,
  facts,
  server,
  beatMs = BEAT_MS,
  minMs = MIN_MS,
}: Props) {
  const [phase, setPhase] = useState<"idle" | "working" | "done" | "error">("idle");
  const [items, setItems] = useState<Shown[]>([]);
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [doing, setDoing] = useState<Doing | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const alive = useRef(true);
  const made = useRef("");
  const began = useRef(0);
  const inputs = JSON.stringify([environment, purpose, rules, facts]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // The clock beside the title, while the plan is being written.
  useEffect(() => {
    if (phase !== "working") return;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - began.current) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  // What was asked about changed, so the plan on screen no longer matches it.
  useEffect(() => {
    if (made.current && made.current !== inputs) {
      made.current = "";
      setPlan(null);
      setItems([]);
      setPhase("idle");
    }
  }, [inputs]);

  async function makePlan() {
    setPhase("working");
    setProblem(null);
    setPlan(null);
    setItems([]);
    setDoing(null);
    setElapsed(0);
    made.current = inputs;
    began.current = Date.now();
    const started = await api.call<{ plan_id: string }>("POST", "/quick-scans/plan", {
      environment,
      purpose,
      rules,
      facts,
    });
    if (!alive.current) return;
    if (!started.ok) {
      setProblem(problemFor(started.status, started.data));
      setPhase("error");
      return;
    }
    let after = 0;
    let batch = 0;
    for (let i = 0; i < POLLS; i++) {
      const job = await api.call<Reply>("GET", `/quick-scans/plan/${started.data.plan_id}?after=${after}`);
      if (!alive.current) return;
      if (!job.ok) {
        setProblem(problemFor(job.status, job.data));
        setPhase("error");
        return;
      }
      const reply = job.data;
      if (reply.status === "done") {
        setPlan(reply.plan);
        setPhase("done");
        return;
      }
      if (reply.status === "error") {
        setProblem(failure(reply.kind));
        setPhase("error");
        return;
      }
      after = reply.next;
      batch += 1;
      const arrived = reply.events.map((item, slot) => ({ ...item, batch, slot }));
      if (arrived.length) setItems((was) => [...was, ...arrived]);
      setDoing({
        goal_index: reply.goal_index,
        goal_total: reply.goal_total,
        waiting: reply.waiting,
        seconds_left: reply.seconds_left,
        at: Date.now(),
      });
      // Spread what is still to come over the time that is left, but keep to the beat.
      const left = reply.total - reply.next;
      const spread = left > 0 ? (minMs - (Date.now() - began.current)) / left : beatMs;
      await new Promise((resolve) => setTimeout(resolve, Math.min(Math.max(spread, beatMs), LONGEST_BEAT_MS)));
      if (!alive.current) return;
    }
    setProblem(failure("plan_timeout"));
    setPhase("error");
  }

  const working = phase === "working";
  const shown = phase === "idle" || phase === "error" ? [] : items;
  const tests = shown.filter((i) => i.kind === "test").length;
  const last = shown[shown.length - 1];
  const lastBatch = last?.batch;

  return (
    <div className="plan">
      <div className="actions">
        <button type="button" className="btn ghost" disabled={working} onClick={makePlan}>
          {working ? (
            <>
              <span className="spin" />
              Creating your plan…
            </>
          ) : (
            "Create Test Plan"
          )}
        </button>
        <span className="hint">
          {working
            ? "This takes a few minutes. Keep this tab open. Nothing is sent to your bot."
            : "See the tests we would write for your bot, before anything runs."}
        </span>
      </div>
      {phase === "error" && problem && (
        <div className="alert" role="alert">
          {problem}
        </div>
      )}
      {(working || phase === "done") && (
        <div className="live" role="status" aria-live="polite">
          <div className="lv-top">
            <span>
              {working && <span className="lv-dot" />}
              <b>{working ? "Writing your tests" : "Your tests are ready"}</b>
              <span className="lv-clock">{clock(elapsed)}</span>
            </span>
            <span className="lv-count">
              <b>{tests}</b> {tests === 1 ? "test" : "tests"}
              {doing && doing.goal_total > 0 && working ? ` · goal ${doing.goal_index} of ${doing.goal_total}` : ""}
            </span>
          </div>
          {working && doing && doing.goal_total > 0 && (
            <div className="lv-bar" aria-hidden="true">
              <span style={{ width: `${Math.round((doing.goal_index / doing.goal_total) * 100)}%` }} />
            </div>
          )}
          {working && doing?.waiting && (
            <div className="wait">
              <span className="spin" />
              <Countdown from={doing.seconds_left} at={doing.at} />
            </div>
          )}
          <ol className="lv-tl">
            {shown.map((item) => {
              const fresh = working && item.batch === lastBatch;
              const style = { animationDelay: `${item.slot * 140}ms` };
              if (item.kind === "test") {
                return (
                  <li key={item.seq} className={`lv-card ${fresh ? "new" : ""}`} style={style}>
                    <div className="lv-who">
                      <span className={`lv-pill ${PILL[item.persona_id] ?? "nu"}`}>{item.persona}</span>
                      {item.changes_data && <span className="lv-tag">changes data</span>}
                    </div>
                    <div className="lv-msg">“{item.text}”</div>
                    <div className="lv-goal">Goal: {item.goal}</div>
                  </li>
                );
              }
              const now = working && item === last;
              return (
                <li key={item.seq} className={`lv-ev ${item.kind} ${now ? "now typing" : ""}`} style={style}>
                  {item.text}
                </li>
              );
            })}
            {working && (!last || last.kind === "test") && (
              <li className="lv-ev now typing">{last ? "Thinking about the next test" : "Starting up"}</li>
            )}
          </ol>
        </div>
      )}
      {plan && <Summary plan={plan} rules={rules} environment={environment} server={server} />}
    </div>
  );
}

/** Counts the seconds down between polls, so the wait looks alive. A new poll restarts it. */
function Countdown({ from, at }: { from: number; at: number }) {
  const [left, setLeft] = useState(from);
  const [synced, setSynced] = useState(at);
  if (synced !== at) {
    // A new poll says how long is really left, so start from that, without replacing the element.
    setSynced(at);
    setLeft(from);
  }
  useEffect(() => {
    const timer = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <span>
      Quota reached. Waiting {left > 0 ? `${left} seconds` : "a moment"}, then we try again on our own.
    </span>
  );
}

/** What the finished plan adds beneath the list of tests: the counts, the rules, what to know first. */
function Summary({
  plan,
  rules,
  environment,
  server,
}: {
  plan: PlanView;
  rules: string[];
  environment: "staging" | "production";
  server: string;
}) {
  return (
    <div className="planview">
      <p className="plan-head">
        <b>{plan.summary.tests} tests</b> from {plan.summary.ideas} ideas · {plan.summary.repeats_removed} repeats
        removed · {plan.summary.data_changing} change data
      </p>
      {plan.blocked && (
        <div className="alert" role="alert">
          {plan.blocked}
        </div>
      )}
      {plan.rules_covered.length > 0 && (
        <details className="covered">
          <summary>
            Your {plan.rules_covered.length} of {rules.length} {rules.length === 1 ? "rule is" : "rules are"} covered
          </summary>
          <ul>
            {plan.rules_covered.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </details>
      )}
      {plan.skipped.length > 0 && (
        <p className="hint">
          {plan.skipped.length} {plan.skipped.length === 1 ? "test needs" : "tests need"} a test copy, so{" "}
          {plan.skipped.length === 1 ? "it is" : "they are"} left out for a live bot.
        </p>
      )}
      <div className="before">
        <b>Before you start</b>
        <ul>
          <li>
            <span className="server">Testing {server}</span>
          </li>
          <li>
            {environment === "staging"
              ? "On a test copy the attacks are real: if your bot is tricked, it will really do what the attack asks. Only use a copy you can reset."
              : "On a live bot we only run tests that do not make it act."}
          </li>
          <li>{CONTACT_WARNING}</li>
          <li>Your key stays in this browser tab and is never saved.</li>
          <li>
            This is a preview. Cost, time and a spending cap come with the new runner, so the button below still runs
            the standard tests for now.
          </li>
        </ul>
      </div>
    </div>
  );
}
