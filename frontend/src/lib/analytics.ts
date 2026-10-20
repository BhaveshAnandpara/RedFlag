// The numbers behind the dashboard, kept as plain functions so the live page, the public page
// and the report all say the same thing. Nothing here may say a bot is safe, secure or ready.
import type { Counts, RiskSummary, ScanDetail, ScanResult, Status } from "@/lib/scan";

export type Tone = "green" | "red" | "yellow" | "grey";

/** Below this many attack tests with a result, a rate is a rough guide only. */
export const SMALL_SAMPLE_UNDER = 20;

export const CLOSING_LINE =
  "This is not a guarantee of security. It only reports what these tests checked.";

export function countByStatus(results: ScanResult[]): Counts {
  const counts: Counts = { pass: 0, fail: 0, inconclusive: 0, error: 0, not_applicable: 0 };
  for (const result of results) counts[result.status] += 1;
  return counts;
}

export type SliceKey = "pass" | "fail" | "unclear" | "not_applicable";
export type Slice = { key: SliceKey; label: string; count: number };

/** Inconclusive and error share one "unclear" slice. Empty slices are left out. */
export function donutSlices(counts: Counts): Slice[] {
  const slices: Slice[] = [
    { key: "pass", label: "Pass", count: counts.pass },
    { key: "fail", label: "Fail", count: counts.fail },
    { key: "unclear", label: "Unclear", count: counts.inconclusive + counts.error },
    { key: "not_applicable", label: "Not applicable", count: counts.not_applicable },
  ];
  return slices.filter((slice) => slice.count > 0);
}

export type RiskBar = {
  id: string;
  name: string;
  state: RiskSummary["state"];
  label: string;
  tone: Tone;
  fullyGreen: boolean;
  tests: number;
  segments: { pass: number; fail: number; unclear: number; not_applicable: number };
};

const STATE_LABEL: Record<RiskSummary["state"], string> = {
  tested: "Tested",
  attempted_no_result: "Attempted, no result",
  not_tested: "Not tested",
};

/**
 * One stacked bar per risk. It is fully green only with at least one test and every test
 * passed. A risk with no pass or fail never shows green, and one with no tests is grey.
 */
export function riskBars(risks: RiskSummary[]): RiskBar[] {
  return risks.map((risk) => {
    const segments = {
      pass: risk.passed,
      fail: risk.failed,
      unclear: risk.errors + risk.inconclusive,
      not_applicable: risk.not_applicable,
    };
    const tone: Tone =
      segments.fail > 0
        ? "red"
        : segments.unclear > 0
          ? "yellow"
          : segments.pass > 0
            ? "green"
            : "grey";
    return {
      id: risk.id,
      name: risk.name,
      state: risk.state,
      label: STATE_LABEL[risk.state],
      tone,
      fullyGreen: risk.tests > 0 && risk.passed === risk.tests,
      tests: risk.tests,
      segments,
    };
  });
}

/** Failed tests rated critical. A result with no rating is never counted as critical. */
export function criticalFailures(results: ScanResult[]): ScanResult[] {
  return results.filter((r) => r.status === "fail" && r.severity === "critical");
}

/** The 95% Wilson score interval for k out of n. */
export function wilson(k: number, n: number): { low: number; high: number } {
  const z = 1.96;
  const p = k / n;
  const denominator = 1 + (z * z) / n;
  const center = (p + (z * z) / (2 * n)) / denominator;
  const margin = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denominator;
  return { low: Math.max(0, center - margin), high: Math.min(1, center + margin) };
}

export type AttackStats = {
  failed: number;
  tested: number;
  couldNotComplete: number;
  notApplicable: number;
  rate: number | null;
  interval: { low: number; high: number } | null;
  smallSample: boolean;
};

/**
 * Attack tests that failed out of those that ended pass or fail. Errors, inconclusive and
 * not-applicable tests are left out of that count and reported beside it. Normal requests
 * are never part of it.
 */
export function attackStats(results: ScanResult[]): AttackStats {
  const attacks = results.filter((r) => r.kind === "negative");
  const count = (status: Status) => attacks.filter((r) => r.status === status).length;
  const failed = count("fail");
  const tested = failed + count("pass");
  return {
    failed,
    tested,
    couldNotComplete: count("error") + count("inconclusive"),
    notApplicable: count("not_applicable"),
    rate: tested > 0 ? failed / tested : null,
    interval: tested > 0 ? wilson(failed, tested) : null,
    smallSample: tested < SMALL_SAMPLE_UNDER,
  };
}

export function normalRequests(results: ScanResult[]) {
  const normal = results.filter((r) => r.kind === "positive");
  const worked = normal.filter((r) => r.status === "pass").length;
  const failed = normal.filter((r) => r.status === "fail").length;
  return { tests: normal.length, worked, failed, unclear: normal.length - worked - failed };
}

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

const percent = (value: number) => Math.round(value * 100);

export type Conclusion = { headline: string; details: string[]; closing: string };

/** Counts first, never a verdict on the bot. */
export function conclusion(scan: ScanDetail): Conclusion {
  const { results, summary } = scan;
  const stats = attackStats(results);
  const critical = criticalFailures(results).length;
  const headline =
    stats.tested === 0
      ? "No attack test produced a pass or fail result."
      : `${stats.failed} of ${stats.tested} ${plural(stats.tested, "attack test", "attack tests")} failed${
          critical > 0 ? `, ${critical} of them critical` : ""
        }.`;

  const details: string[] = [];
  if (stats.rate !== null && stats.interval) {
    details.push(
      `Attack success rate: ${stats.failed} of ${stats.tested} (${percent(stats.rate)}%, 95% range ${percent(
        stats.interval.low,
      )}% to ${percent(stats.interval.high)}%).`,
    );
    if (stats.smallSample) {
      details.push("This is a small sample, so treat the rate as rough.");
    }
  }
  const counts = countByStatus(results);
  const unclear = counts.inconclusive + counts.error;
  if (unclear > 0) {
    details.push(
      `${unclear} ${plural(unclear, "test", "tests")} could not be completed, so ${plural(unclear, "it says", "they say")} nothing either way.`,
    );
  }
  const normal = normalRequests(results);
  if (normal.tests > 0) {
    details.push(`Normal requests: ${normal.worked} of ${normal.tests} worked.`);
  }
  const noResult = summary.risks.filter((risk) => risk.state !== "tested").length;
  if (noResult > 0) {
    details.push(
      `${noResult} of ${summary.risks.length} ${plural(noResult, "risk has", "risks have")} no pass or fail result.`,
    );
  }
  details.push(...judgeLines(results));
  if (isRealBot(scan)) {
    details.push(
      "No plain rules ran on this bot, so there was no second opinion: every result was decided by an AI judge from the bot's reply alone.",
    );
  }
  return { headline, details, closing: CLOSING_LINE };
}

export function conclusionText(scan: ScanDetail): string {
  const { headline, details, closing } = conclusion(scan);
  return [headline, ...details, closing].join(" ");
}

/** A scan of the owner's own bot (M6) records the setup version it ran with. */
export function isRealBot(scan: ScanDetail): boolean {
  return scan.scan.settings.setup !== undefined;
}

export type Comparison = {
  /** Rules added or removed between the two scans' setups. Null unless both are real-bot scans. */
  ruleChanges: { added: string[]; removed: string[] } | null;
  sameModels: boolean;
  modelStatement: string;
  suiteVersionsDiffer: boolean;
  /** Set when only one of the two scans had the AI judge. Null when both or neither did. */
  judgeStatement: string | null;
  changed: { test_id: string; title: string; from: Status; to: Status }[];
  onlyInFirst: string[];
  onlyInSecond: string[];
  firstCounts: Counts;
  secondCounts: Counts;
};

/**
 * Compare two scans. "Same model" means the two sets of models that answered are identical,
 * so a scan that mixed models after a rate-limit fallback is not the same as one that did not.
 */
export function compareScans(first: ScanDetail, second: ScanDetail): Comparison {
  const a = [...first.scan.models_used].sort();
  const b = [...second.scan.models_used].sort();
  const sameModels = a.length > 0 && JSON.stringify(a) === JSON.stringify(b);
  let modelStatement: string;
  if (a.length === 0 || b.length === 0) {
    modelStatement =
      "No model answered in one or both of these scans, so the comparison cannot say whether the same model was used.";
  } else if (sameModels) {
    modelStatement = `The same ${plural(a.length, "model", "models")} answered both scans (${a.join(", ")}), so the difference is not explained by a different model.`;
  } else {
    modelStatement = `Different models answered the two scans (first: ${a.join(", ")}; second: ${b.join(", ")}), so the difference may not come from the defenses.`;
  }

  const byId = (scan: ScanDetail) => new Map(scan.results.map((r) => [r.test_id, r]));
  const firstById = byId(first);
  const secondById = byId(second);
  const changed: Comparison["changed"] = [];
  for (const [id, one] of firstById) {
    const two = secondById.get(id);
    if (two && two.status !== one.status) {
      changed.push({ test_id: id, title: one.title, from: one.status, to: two.status });
    }
  }
  const firstRules = first.scan.settings.setup?.rules.map((r) => r.text);
  const secondRules = second.scan.settings.setup?.rules.map((r) => r.text);
  const ruleChanges =
    firstRules && secondRules
      ? {
          added: secondRules.filter((text) => !firstRules.includes(text)),
          removed: firstRules.filter((text) => !secondRules.includes(text)),
        }
      : null;
  return {
    ruleChanges,
    sameModels,
    modelStatement,
    suiteVersionsDiffer: first.scan.settings.suite_version !== second.scan.settings.suite_version,
    judgeStatement:
      judgeSummary(first.results).ran === judgeSummary(second.results).ran
        ? null
        : "Only one of these scans had the AI judge, so they are not like for like: the judge can fail tests that the plain rules pass.",
    changed,
    onlyInFirst: [...firstById].filter(([id]) => !secondById.has(id)).map(([, r]) => r.title),
    onlyInSecond: [...secondById].filter(([id]) => !firstById.has(id)).map(([, r]) => r.title),
    firstCounts: first.summary.counts,
    secondCounts: second.summary.counts,
  };
}

/**
 * The banner colour. Red if anything failed. Yellow if some tests were unclear or some risks
 * have no pass or fail result. Green only when none of that is true, so an incomplete scan can
 * never look like an all-clear.
 */
export function overallTone(scan: ScanDetail): Tone {
  const counts = countByStatus(scan.results);
  if (counts.fail > 0) return "red";
  const incomplete =
    counts.error + counts.inconclusive > 0 || scan.summary.risks.some((r) => r.state !== "tested");
  return incomplete ? "yellow" : "green";
}

export type JudgeState = "pass" | "fail" | "unavailable" | "not_run";

/** The AI judge's own answer for a result. Null or missing means it did not run. */
export function judgeState(result: ScanResult): JudgeState {
  return result.judge_status ?? "not_run";
}

/** What the plain rules said on their own. Old results fall back to the combined result. */
export function ruleOutput(result: ScanResult): { status: Status; evidence: string } {
  return {
    status: result.rule_status ?? result.status,
    evidence: result.rule_evidence ?? result.evidence,
  };
}

export type JudgeSummary = {
  ran: boolean;
  judged: number;
  passed: number;
  failed: number;
  unavailable: number;
  notRun: number;
  /** Tests the judge failed that the plain rules had passed. */
  judgeCaught: number;
  /** Tests the plain rules failed that the judge had passed. */
  rulesCaught: number;
  /** Tests where both decided pass or fail and disagreed. */
  disagreements: number;
};

export function judgeSummary(results: ScanResult[]): JudgeSummary {
  const state = (r: ScanResult) => judgeState(r);
  const judgedResults = results.filter((r) => state(r) !== "not_run");
  const judgeCaught = results.filter(
    (r) => state(r) === "fail" && r.rule_status === "pass",
  ).length;
  const rulesCaught = results.filter(
    (r) => state(r) === "pass" && r.rule_status === "fail",
  ).length;
  return {
    ran: judgedResults.length > 0,
    judged: judgedResults.length,
    passed: results.filter((r) => state(r) === "pass").length,
    failed: results.filter((r) => state(r) === "fail").length,
    unavailable: results.filter((r) => state(r) === "unavailable").length,
    notRun: results.length - judgedResults.length,
    judgeCaught,
    rulesCaught,
    disagreements: judgeCaught + rulesCaught,
  };
}

export const NO_JUDGE_LINE =
  "No AI judge ran on this scan, so only the plain rules decided the results.";
export const UNCHECKED_JUDGE_LINE =
  "The AI judge has not been checked for accuracy, so treat its verdicts as unconfirmed.";

/** The sentences about the judge, shared by the conclusion and the report. */
export function judgeLines(results: ScanResult[]): string[] {
  const summary = judgeSummary(results);
  if (!summary.ran) return [NO_JUDGE_LINE];
  const lines: string[] = [];
  if (summary.judgeCaught > 0) {
    lines.push(
      `The AI judge failed ${summary.judgeCaught} ${plural(summary.judgeCaught, "test", "tests")} the plain rules had passed.`,
    );
  }
  if (summary.unavailable > 0) {
    lines.push(
      `${summary.unavailable} AI judge ${plural(summary.unavailable, "verdict was", "verdicts were")} unavailable, so ${plural(summary.unavailable, "that test is", "those tests are")} unclear.`,
    );
  }
  lines.push(UNCHECKED_JUDGE_LINE);
  return lines;
}

export type DeltaTest = { id: string; title: string };

export type RunDelta = {
  previousId: number;
  fixed: DeltaTest[];
  newProblems: DeltaTest[];
  stillFailing: DeltaTest[];
  unclearNow: DeltaTest[];
  noLongerRun: DeltaTest[];
  summary: string;
};

/**
 * What changed between two scans of the same tests. A test is matched by its id. It never says the
 * change is good news: a fixed test only means it passed this time, and a model can vary.
 */
export function runDelta(current: ScanDetail, previous: ScanDetail): RunDelta {
  const before = new Map(previous.results.map((r) => [r.test_id, r]));
  const now = new Set(current.results.map((r) => r.test_id));
  const item = (r: ScanResult): DeltaTest => ({ id: r.test_id, title: r.title });
  const decided = (status: Status) => status === "pass" || status === "fail";

  const fixed: DeltaTest[] = [];
  const newProblems: DeltaTest[] = [];
  const stillFailing: DeltaTest[] = [];
  const unclearNow: DeltaTest[] = [];
  for (const r of current.results) {
    const was = before.get(r.test_id);
    if (r.status === "fail") {
      if (!was || was.status !== "fail") newProblems.push(item(r));
      else stillFailing.push(item(r));
    } else if (r.status === "pass" && was?.status === "fail") {
      fixed.push(item(r));
    } else if (!decided(r.status) && was && decided(was.status)) {
      unclearNow.push(item(r));
    }
  }
  const noLongerRun = previous.results.filter((r) => !now.has(r.test_id)).map(item);

  const parts = [
    fixed.length > 0 ? `${fixed.length} fixed` : null,
    newProblems.length > 0
      ? `${newProblems.length} new ${plural(newProblems.length, "problem", "problems")}`
      : null,
    stillFailing.length > 0 ? `${stillFailing.length} still failing` : null,
    unclearNow.length > 0 ? `${unclearNow.length} now unclear` : null,
  ].filter((part): part is string => part !== null);
  const summary =
    parts.length > 0
      ? `Since scan #${previous.scan.id}: ${parts.join(", ")}.`
      : `Since scan #${previous.scan.id}: nothing changed in the tests that were run both times.`;
  return {
    previousId: previous.scan.id,
    fixed,
    newProblems,
    stillFailing,
    unclearNow,
    noLongerRun,
    summary,
  };
}
