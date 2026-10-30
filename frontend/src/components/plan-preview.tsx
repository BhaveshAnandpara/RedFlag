"use client";

import { useEffect, useRef, useState } from "react";

import { problemFor } from "@/lib/open-api";
import type { SetupApi } from "@/lib/setup-api";

/** One goal of the plan, as the supervisor wrote it. */
type PlanGoal = {
  id: string;
  question: string;
  tag: string;
  background: boolean;
  severity: string | null;
  test_count: number;
  note: string | null;
  tests: { persona: string; goal: string; opening_message: string; changes_data: boolean }[];
};
type PlanView = {
  summary: { ideas: number; repeats_removed: number; tests: number; data_changing: number };
  blocked: string | null;
  rules_covered: string[];
  skipped: { persona: string; goal: string; reason: string }[];
  goals: PlanGoal[];
};
type Job = { status: "running" } | { status: "done"; plan: PlanView } | { status: "error"; kind: string };

const POLLS = 120;
const CONTACT_WARNING =
  "Our tests only point your AI at Redflag's own links and addresses, but we can't stop it from contacting anyone else it chooses.";

const failure = (kind: string) =>
  kind === "plan_timeout"
    ? "Planning took too long. Try again."
    : "We could not make the plan. Nothing was run. Try again.";

type Props = {
  api: SetupApi;
  environment: "staging" | "production";
  purpose: string;
  rules: string[];
  facts: unknown;
  server: string;
  pollMs?: number;
};

/** A read-only look at the tests the supervisor would write, before anything runs. */
export function PlanPreview({ api, environment, purpose, rules, facts, server, pollMs = 3000 }: Props) {
  const [phase, setPhase] = useState<"idle" | "working" | "done" | "error">("idle");
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const alive = useRef(true);
  const made = useRef("");
  const inputs = JSON.stringify([environment, purpose, rules, facts]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // What was asked about changed, so the plan on screen no longer matches it.
  useEffect(() => {
    if (made.current && made.current !== inputs) {
      made.current = "";
      setPlan(null);
      setPhase("idle");
    }
  }, [inputs]);

  async function makePlan() {
    setPhase("working");
    setProblem(null);
    setPlan(null);
    made.current = inputs;
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
    for (let i = 0; i < POLLS; i++) {
      await new Promise((resolve) => setTimeout(resolve, pollMs));
      if (!alive.current) return;
      const job = await api.call<Job>("GET", `/quick-scans/plan/${started.data.plan_id}`);
      if (!alive.current) return;
      if (!job.ok) {
        setProblem(problemFor(job.status, job.data));
        setPhase("error");
        return;
      }
      if (job.data.status === "done") {
        setPlan(job.data.plan);
        setPhase("done");
        return;
      }
      if (job.data.status === "error") {
        setProblem(failure(job.data.kind));
        setPhase("error");
        return;
      }
    }
    setProblem(failure("plan_timeout"));
    setPhase("error");
  }

  return (
    <div className="plan">
      <div className="actions">
        <button type="button" className="btn ghost" disabled={phase === "working"} onClick={makePlan}>
          {phase === "working" ? (
            <>
              <span className="spin" />
              Planning your tests…
            </>
          ) : (
            "Preview the test plan"
          )}
        </button>
        <span className="hint">
          {phase === "working"
            ? "This can take a minute or two. Nothing is sent to your bot."
            : "See the tests we would write for your bot, before anything runs."}
        </span>
      </div>
      {phase === "error" && problem && (
        <div className="alert" role="alert">
          {problem}
        </div>
      )}
      {plan && (
        <div className="planview">
          <p className="plan-head">
            <b>{plan.summary.tests} tests</b> from {plan.summary.ideas} ideas · {plan.summary.repeats_removed}{" "}
            repeats removed · {plan.summary.data_changing} change data
          </p>
          {plan.blocked && (
            <div className="alert" role="alert">
              {plan.blocked}
            </div>
          )}
          {plan.rules_covered.length > 0 && (
            <details className="covered">
              <summary>
                Your {plan.rules_covered.length} of {rules.length} {rules.length === 1 ? "rule is" : "rules are"}{" "}
                covered
              </summary>
              <ul>
                {plan.rules_covered.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </details>
          )}
          <div className="goals">
            {plan.goals.map((g) => (
              <details key={g.id} className={`goal ${g.background ? "background" : ""}`}>
                <summary>
                  <span className="q">{g.question}</span>
                  <span className="mine">
                    {g.test_count} {g.test_count === 1 ? "test" : "tests"}
                    {g.background ? " · background" : ""}
                  </span>
                </summary>
                <p className="hint">{g.tag}</p>
                {g.note && <p className="hint">{g.note}</p>}
                <ul>
                  {g.tests.map((t, i) => (
                    <li key={i}>
                      <span className="mine">{t.persona}</span> {t.opening_message}
                      {t.changes_data ? <span className="mine"> · changes data</span> : null}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
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
      )}
    </div>
  );
}
