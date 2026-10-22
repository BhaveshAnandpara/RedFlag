// Works out everything the report page shows from a finished scan. Pure functions, so the numbers
// are checked on their own: the page only lays them out.
import type { ScanDetail, ScanResult } from "@/lib/scan";

export const RISK_NAMES: [string, string][] = [
  ["LLM01", "Prompt injection"],
  ["LLM02", "Sensitive information disclosure"],
  ["LLM03", "Supply chain"],
  ["LLM04", "Data and model poisoning"],
  ["LLM05", "Improper output handling"],
  ["LLM06", "Excessive agency"],
  ["LLM07", "System prompt leakage"],
  ["LLM08", "Vector and embedding weaknesses"],
  ["LLM09", "Misinformation"],
  ["LLM10", "Unbounded consumption"],
];

const SEVERITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const byWorst = (a: ScanResult, b: ScanResult) =>
  (SEVERITY_RANK[a.severity ?? ""] ?? 4) - (SEVERITY_RANK[b.severity ?? ""] ?? 4);

/** The 95% range for k of n (Wilson). Honest about a small sample. */
export function wilson(k: number, n: number, z = 1.96): [number, number] {
  if (n === 0) return [0, 0];
  const p = k / n;
  const d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d;
  const h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

export const pct = (value: number) => `${Math.round(value * 100)}%`;

export function when(epochSeconds: number): string {
  return `${new Date(epochSeconds * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function seconds(detail: ScanDetail): number {
  const { started_at, finished_at } = detail.scan;
  return finished_at ? Math.max(0, Math.round(finished_at - started_at)) : 0;
}

export function judgeModels(results: ScanResult[]): string[] {
  return [...new Set(results.map((r) => r.judge_model).filter((m): m is string => !!m))].sort();
}

// ---------- a scan of the visitor's own bot ----------

// n/f are decided results (pass/fail) only. u is how many more could not be decided (an error,
// a refusal, or the judge giving no verdict) — never folded into n, so "f of n" never implies
// more was tested than actually was.
export type Cover = { id: string; name: string; n: number; f: number; u?: number };

export function botModel(detail: ScanDetail) {
  const results = detail.results;
  const attacks = results.filter((r) => r.kind === "negative");
  const normal = results.filter((r) => r.kind === "positive");
  const failed = attacks.filter((r) => r.status === "fail").sort(byWorst);
  const critical = failed.filter((r) => r.severity === "critical").length;
  const tested = new Set(results.map((r) => r.risk).filter((r): r is string => !!r));
  const untested = RISK_NAMES.filter(([id]) => !tested.has(id)).length;
  const [lo, hi] = wilson(failed.length, attacks.length);
  const cover: Cover[] = RISK_NAMES.map(([id, name]) => {
    const mine = results.filter((r) => r.risk === id);
    return { id, name, n: mine.length, f: mine.filter((r) => r.status === "fail").length };
  });
  return {
    attacks,
    normal,
    failed,
    critical,
    normalOk: normal.filter((r) => r.status === "pass").length,
    untested,
    tested: [...tested].sort(),
    lo,
    hi,
    rate: attacks.length ? failed.length / attacks.length : 0,
    cover,
  };
}

// ---------- a check of an MCP server ----------

export const MCP_FAMILIES: Record<string, { title: string; risk: string }> = {
  hidden_instructions: { title: "Descriptions: hidden instructions", risk: "LLM01" },
  hidden_characters: { title: "Descriptions: invisible characters", risk: "LLM01" },
  sensitive_wording: { title: "Descriptions: credentials and sending data out", risk: "LLM02" },
  broad_parameters: { title: "Inputs: open-ended parameters", risk: "LLM06" },
};

export const MCP_KINDS: Record<string, { label: string; risk: string }> = {
  traversal: { label: "Path traversal", risk: "LLM02" },
  injection: { label: "Injection strings", risk: "LLM05" },
  oversized: { label: "A very large value", risk: "LLM10" },
  prompt_injection: { label: "An instruction hidden in an input", risk: "LLM01" },
};

export const mcpGroup = (testId: string): "static" | "call" =>
  testId.startsWith("mcp-static-") ? "static" : "call";

export function mcpFamily(testId: string): string | null {
  const m = /^mcp-static-([a-z_]+?)(?:-|$)/.exec(testId);
  if (!m) return null;
  const id = Object.keys(MCP_FAMILIES).find((f) => testId === `mcp-static-${f}` || testId.startsWith(`mcp-static-${f}-`));
  return id ?? null;
}

/** The tool a result is about, read from its id. A clean description check covers every tool. */
export function mcpTool(testId: string): string | null {
  const family = mcpFamily(testId);
  if (family) {
    const rest = testId.slice(`mcp-static-${family}`.length);
    return rest.startsWith("-") ? rest.slice(1) : null;
  }
  const m = /^mcp-dyn-(.+?)-(traversal|injection|oversized|prompt_injection|none)(?:-|$)/.exec(testId);
  return m ? m[1] : null;
}

export function mcpKind(testId: string): string | null {
  const m = /-(traversal|injection|oversized|prompt_injection)-/.exec(testId);
  return m ? m[1] : null;
}

export function mcpModel(detail: ScanDetail) {
  const results = detail.results;
  const mcp = detail.scan.settings.mcp;
  const called = mcp?.exercised ?? [];
  const toolNames = mcp?.tools ?? called.map((c) => c.name);
  const toolCount = mcp?.tool_count ?? toolNames.length;
  const decided = results.filter((r) => r.status === "pass" || r.status === "fail");
  const failed = results.filter((r) => r.status === "fail").sort(byWorst);
  const critical = failed.filter((r) => r.severity === "critical").length;
  const unclear = results.filter((r) => r.status === "inconclusive").length;
  const calls = results.filter((r) => mcpGroup(r.test_id) === "call" && r.status !== "not_applicable");
  const decidedCalls = calls.filter((r) => r.status === "pass" || r.status === "fail");
  const undecidedCalls = calls.length - decidedCalls.length;
  const callFails = decidedCalls.filter((r) => r.status === "fail").length;
  const flaggedTools = new Set(
    results
      .filter(
        (r) =>
          mcpGroup(r.test_id) === "static" &&
          r.status === "fail" &&
          mcpFamily(r.test_id) !== "broad_parameters",
      )
      .map((r) => mcpTool(r.test_id)),
  );
  const calledNames = new Set(called.map((c) => c.name));
  const cover: Cover[] = [
    ...Object.entries(MCP_FAMILIES).map(([id, fam]) => {
      if (id === "broad_parameters") {
        // One merged row covers every tool, so its count of affected tools lives in the
        // evidence text ("N of M tools have a parameter ..."), not in one row per tool.
        const row = results.find((r) => r.test_id === "mcp-static-broad_parameters");
        const n = Number(/^(\d+) of (\d+) tools/.exec(row?.evidence ?? "")?.[2] ?? toolCount);
        const f = row?.status === "fail" ? Number(/^(\d+) of \d+ tools/.exec(row.evidence)?.[1] ?? 0) : 0;
        return { id: fam.risk, name: fam.title, n, f };
      }
      const bad = new Set(
        results.filter((r) => mcpFamily(r.test_id) === id && r.status === "fail").map((r) => mcpTool(r.test_id)),
      );
      return { id: fam.risk, name: fam.title, n: toolCount, f: bad.size };
    }),
    ...Object.entries(MCP_KINDS).map(([kind, info]) => {
      const mine = calls.filter((r) => mcpKind(r.test_id) === kind);
      const decided = mine.filter((r) => r.status === "pass" || r.status === "fail");
      return {
        id: info.risk,
        name: `Calls: ${info.label.toLowerCase()}`,
        n: decided.length,
        f: decided.filter((r) => r.status === "fail").length,
        u: mine.length - decided.length,
      };
    }),
  ];
  return {
    decided,
    failed,
    critical,
    unclear,
    calls,
    decidedCalls,
    undecidedCalls,
    callFails,
    flaggedTools,
    called,
    changes: called.filter((c) => c.effect === "acts"),
    toolNames,
    toolCount,
    readOnly: toolNames.filter((n) => !calledNames.has(n)),
    cover,
  };
}
