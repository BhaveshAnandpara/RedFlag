// The Markdown report. It lists everything the scan did, including what failed, what could not
// be decided and what was not tested, and it ends with a plain line that it is no guarantee.
import {
  CLOSING_LINE,
  NO_JUDGE_LINE,
  UNCHECKED_JUDGE_LINE,
  conclusion,
  judgeState,
  judgeSummary,
  ruleOutput,
  type JudgeState,
} from "@/lib/analytics";
import type { ScanDetail, ScanResult, Status } from "@/lib/scan";

const STATUS_WORD: Record<Status, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "INCONCLUSIVE",
  error: "ERROR",
  not_applicable: "NOT APPLICABLE",
};

const JUDGE_WORD: Record<JudgeState, string> = {
  pass: "PASS",
  fail: "FAIL",
  unavailable: "UNAVAILABLE",
  not_run: "NOT RUN",
};

const cell = (text: string) => text.replace(/\|/g, "\\|").replace(/\n/g, " ");

function severityText(result: ScanResult): string {
  if (result.kind === "positive") return "normal request";
  return result.severity ?? "not rated";
}

function when(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

export function buildReport(detail: ScanDetail): string {
  const { scan, results, summary } = detail;
  const { settings } = scan;
  const text = conclusion(detail);
  const lines: string[] = [];

  lines.push("# Redflag scan report", "");
  lines.push(
    `**Scan #${scan.id}** · ${settings.bot_name} · Status: ${scan.status} · Started ${when(scan.started_at)}`,
    "",
  );

  lines.push("## Conclusion", "", text.headline, "");
  for (const detailLine of text.details) lines.push(`- ${detailLine}`);
  lines.push("");

  lines.push("## Settings this scan ran with", "");
  lines.push(`- Bot: ${settings.bot_name} (config version ${settings.bot_config_version})`);
  lines.push(
    `- Defenses on: ${settings.bot_defenses.length > 0 ? settings.bot_defenses.join(", ") : "none"}`,
  );
  lines.push(
    `- Models that answered: ${scan.models_used.length > 0 ? scan.models_used.join(", ") : "none"}`,
  );
  if (settings.setup) {
    lines.push(`- Setup version ${settings.setup.version} (setup ${settings.setup.setup_id})`);
    lines.push(`- Target: ${settings.setup.target_host}`);
    lines.push(`- Tests run: ${settings.test_count}, chosen by the owner from the generated tests`);
  } else {
    lines.push(`- Suite version: ${settings.suite_version} (${settings.test_count} tests)`);
  }
  lines.push(`- Risk list: ${summary.catalog_version}`);
  lines.push(
    `- Budget: up to ${settings.budget.requests} requests and ${settings.budget.tokens} tokens`,
  );
  if (settings.canary) lines.push(`- Secret planted for this scan: ${settings.canary}`);
  lines.push("");

  if (settings.setup) {
    lines.push("## Rules in force", "");
    lines.push(
      "These are the rules this bot was tested against. The tool log is not available for this kind of target, so only the bot's replies were judged.",
      "",
    );
    if (settings.setup.rules.length === 0) lines.push("No rules were recorded.");
    for (const rule of settings.setup.rules) {
      lines.push(`- ${rule.text} (${rule.kind}, ${rule.status})`);
    }
    lines.push("");
  }

  const judge = judgeSummary(results);
  lines.push("## The AI judge", "");
  if (!judge.ran) {
    lines.push(NO_JUDGE_LINE, "");
  } else {
    lines.push(
      "Each test was also read by a second AI, which said pass or fail and gave a reason. If either the plain rules or the AI judge failed a test, the test failed.",
      "",
    );
    lines.push(`- Judged: ${judge.judged} tests (${judge.passed} pass, ${judge.failed} fail)`);
    lines.push(`- Judge verdicts unavailable: ${judge.unavailable}`);
    lines.push(`- Not judged (errors, not applicable): ${judge.notRun}`);
    lines.push(
      `- ${judge.disagreements} ${judge.disagreements === 1 ? "test" : "tests"} where the plain rules and the AI judge disagreed (judge failed ${judge.judgeCaught} the rules passed, rules failed ${judge.rulesCaught} the judge passed)`,
    );
    lines.push("", UNCHECKED_JUDGE_LINE, "");
  }

  lines.push("## What was tested", "");
  lines.push(
    "| Test | Risk | Severity | Result | AI judge | Model |",
    "|---|---|---|---|---|---|",
  );
  for (const r of results) {
    lines.push(
      `| ${cell(r.title)} | ${r.risk ?? "none"} | ${severityText(r)} | ${STATUS_WORD[r.status]} | ${JUDGE_WORD[judgeState(r)]} | ${r.model ?? "none"} |`,
    );
  }
  lines.push("");

  lines.push("## Failures", "");
  const failures = results.filter((r) => r.status === "fail");
  if (failures.length === 0) lines.push("No test failed.", "");
  for (const r of failures) {
    lines.push(`### ${r.title}`, "");
    lines.push(`- Severity: ${severityText(r)}`);
    lines.push(`- Evidence: ${r.evidence}`);
    if (r.turns && r.turns.length > 0) {
      const count = Math.ceil(r.turns.length / 2);
      lines.push(`- Conversation (${count} ${count === 1 ? "turn" : "turns"}):`);
      for (const turn of r.turns) {
        lines.push(`  - ${turn.role === "user" ? "Tester" : "Bot"}: ${turn.content.replace(/\n/g, " ")}`);
      }
    }
    if (judgeState(r) !== "not_run") {
      const rules = ruleOutput(r);
      lines.push(`- Plain rules (${STATUS_WORD[rules.status]}): ${rules.evidence}`);
      lines.push(
        `- AI judge (${JUDGE_WORD[judgeState(r)]}): ${r.judge_reason ?? "no reason recorded"}${
          r.judge_model ? ` [${r.judge_model}]` : ""
        }`,
      );
    }
    lines.push(`- Rule: ${r.rule}`);
    lines.push(`- How to fix: ${r.remediation ?? "No fix note was recorded for this result."}`, "");
  }

  lines.push("## Could not be decided or completed", "");
  const unclear = results.filter((r) => r.status === "inconclusive" || r.status === "error");
  if (unclear.length === 0) lines.push("Nothing.", "");
  for (const r of unclear) {
    lines.push(`- **${r.title}** (${STATUS_WORD[r.status]}): ${r.evidence}`);
  }
  if (unclear.length > 0) lines.push("");

  const notApplicable = results.filter((r) => r.status === "not_applicable");
  if (notApplicable.length > 0) {
    lines.push("## Did not apply to this bot", "");
    for (const r of notApplicable) lines.push(`- **${r.title}**: ${r.evidence}`);
    lines.push("");
  }

  const normal = results.filter((r) => r.kind === "positive");
  if (normal.length > 0) {
    lines.push("## Normal requests", "");
    lines.push(
      `${normal.filter((r) => r.status === "pass").length} of ${normal.length} worked. A bot that refuses normal requests is not working, even if it blocks every attack.`,
      "",
    );
  }

  lines.push("## Risks not tested", "");
  const untested = summary.risks.filter((risk) => risk.state !== "tested");
  if (untested.length === 0) lines.push("Every risk in the list had at least one pass or fail result.", "");
  for (const risk of untested) {
    const state = risk.state === "attempted_no_result" ? "attempted, no result" : "not tested";
    lines.push(`- ${risk.id} ${risk.name}: ${state}`);
  }
  lines.push("", "---", "", CLOSING_LINE, "");
  return lines.join("\n");
}
