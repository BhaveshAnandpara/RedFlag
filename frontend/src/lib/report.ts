// The Markdown report. It lists everything the scan did, including what failed, what could not
// be decided and what was not tested, and it ends with a plain line that it is no guarantee.
import { CLOSING_LINE, conclusion } from "@/lib/analytics";
import type { ScanDetail, ScanResult, Status } from "@/lib/scan";

const STATUS_WORD: Record<Status, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "INCONCLUSIVE",
  error: "ERROR",
  not_applicable: "NOT APPLICABLE",
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
  lines.push(`- Suite version: ${settings.suite_version} (${settings.test_count} tests)`);
  lines.push(`- Risk list: ${summary.catalog_version}`);
  lines.push(
    `- Budget: up to ${settings.budget.requests} requests and ${settings.budget.tokens} tokens`,
  );
  lines.push(`- Secret planted for this scan: ${settings.canary}`, "");

  lines.push("## What was tested", "");
  lines.push("| Test | Risk | Severity | Result | Model |", "|---|---|---|---|---|");
  for (const r of results) {
    lines.push(
      `| ${cell(r.title)} | ${r.risk ?? "none"} | ${severityText(r)} | ${STATUS_WORD[r.status]} | ${r.model ?? "none"} |`,
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
