// Builders for scan data used by the tests. They make the shape the scan API returns.
import type { RiskSummary, ScanDetail, ScanResult, Status } from "@/lib/scan";

export const RISKS: [string, string][] = [
  ["LLM01", "Prompt Injection"],
  ["LLM02", "Sensitive Information Disclosure"],
  ["LLM03", "Supply Chain"],
  ["LLM04", "Data and Model Poisoning"],
  ["LLM05", "Improper Output Handling"],
  ["LLM06", "Excessive Agency"],
  ["LLM07", "System Prompt Leakage"],
  ["LLM08", "Vector and Embedding Weaknesses"],
  ["LLM09", "Misinformation"],
  ["LLM10", "Unbounded Consumption"],
];

let counter = 0;

export function makeResult(overrides: Partial<ScanResult> = {}): ScanResult {
  counter += 1;
  return {
    test_id: `test-${counter}`,
    risk: "LLM02",
    kind: "negative",
    title: `Test number ${counter}`,
    message: "the attack message",
    status: "pass",
    reply: "a reply",
    tool_calls: [],
    evidence: "No violation found in the reply or the tool log",
    rule: "A rule.",
    model: "gemini-3.5-flash-lite",
    provider: "gemini",
    attempts: [],
    severity: "high",
    remediation: "Fix it in code.",
    ...overrides,
  };
}

/** Results of one kind and status, for building a scan quickly. */
export function many(
  count: number,
  status: Status,
  overrides: Partial<ScanResult> = {},
): ScanResult[] {
  return Array.from({ length: count }, () => makeResult({ status, ...overrides }));
}

/** The same per-risk summary the backend produces, worked out from the results. */
export function riskSummaries(results: ScanResult[]): RiskSummary[] {
  return RISKS.map(([id, name]) => {
    const mine = results.filter((r) => r.risk === id);
    const n = (status: Status) => mine.filter((r) => r.status === status).length;
    const state =
      n("pass") + n("fail") > 0 ? "tested" : mine.length > 0 ? "attempted_no_result" : "not_tested";
    return {
      id,
      name,
      state,
      tests: mine.length,
      passed: n("pass"),
      failed: n("fail"),
      errors: n("error"),
      inconclusive: n("inconclusive"),
      not_applicable: n("not_applicable"),
    };
  });
}

export function makeScan(
  results: ScanResult[],
  options: {
    id?: number;
    botId?: string;
    status?: "running" | "completed" | "interrupted";
    models?: string[];
    suiteVersion?: number;
    startedAt?: number;
    setup?: { version: number; rules: { text: string; kind: string; status: string }[] };
  } = {},
): ScanDetail {
  const counts = { pass: 0, fail: 0, inconclusive: 0, error: 0, not_applicable: 0 };
  for (const r of results) counts[r.status] += 1;
  const positive = results.filter((r) => r.kind === "positive");
  const botId = options.botId ?? "acme-weak";
  return {
    scan: {
      id: options.id ?? 7,
      bot_id: botId,
      status: options.status ?? "completed",
      note: null,
      started_at: options.startedAt ?? 1_760_000_000,
      finished_at: 1_760_000_050,
      last_progress_at: 1_760_000_050,
      models_used: options.models ?? ["gemini-3.5-flash-lite"],
      settings: {
        bot_id: botId,
        bot_name: `Acme Store support bot (${botId === "acme-weak" ? "weak" : "hardened"})`,
        bot_config_version: 1,
        bot_defenses: botId === "acme-weak" ? [] : ["order_scoping"],
        catalog_version: "owasp-llm-2025",
        suite_version: options.suiteVersion ?? 2,
        test_count: 16,
        canary: options.setup ? "" : "CANARY-abc123",
        ...(options.setup
          ? {
              setup: {
                setup_id: 5,
                version: options.setup.version,
                selected_test_ids: [],
                target_host: "bot.example",
                rules: options.setup.rules,
              },
            }
          : {}),
        providers: ["gemini"],
        budget: { requests: 150, tokens: 300000, seconds: 1800, concurrency: 1 },
      },
    },
    results,
    summary: {
      counts,
      risks: riskSummaries(results),
      normal_requests: {
        tests: positive.length,
        passed: positive.filter((r) => r.status === "pass").length,
        failed: positive.filter((r) => r.status === "fail").length,
        errors: positive.filter((r) => !["pass", "fail"].includes(r.status)).length,
      },
      catalog_version: "owasp-llm-2025",
      catalog_source: "https://genai.owasp.org/llm-top-10/",
      disclaimer: "This is not a claim that the bot is secure.",
    },
  };
}
