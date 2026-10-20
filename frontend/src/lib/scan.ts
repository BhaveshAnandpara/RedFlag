// The shapes the scan API returns (backend/src/redflag_backend/scan/api.py).

export type Status = "pass" | "fail" | "inconclusive" | "error" | "not_applicable";

export type BotInfo = {
  id: string;
  name: string;
  description: string;
  defenses: string[];
  config_version: number;
};

export type ToolRecord = {
  tool: string;
  arguments: Record<string, unknown>;
  outcome: string;
  detail: string;
};

export type ScanResult = {
  test_id: string;
  risk: string | null;
  kind: "negative" | "positive";
  title: string;
  message: string;
  status: Status;
  reply: string;
  tool_calls: ToolRecord[];
  evidence: string;
  rule: string;
  model: string | null;
  provider: string | null;
  attempts: { provider: string; model: string | null; outcome: string; latency_ms: number }[];
  // Saved with the result since M4. Results from before then have neither (null or missing),
  // and are shown as "not rated".
  severity?: Severity | null;
  remediation?: string | null;
  // Every turn of a multi-turn attack, oldest first. Single-message tests have none.
  turns?: { role: "user" | "assistant"; content: string }[] | null;
  // The two sides of the combined `status` and `evidence`, saved since M5. Scans from before
  // the judge, and tests that errored or did not apply, have none (null or missing).
  rule_status?: "pass" | "fail" | "inconclusive" | null;
  rule_evidence?: string | null;
  judge_status?: "pass" | "fail" | "unavailable" | null;
  judge_reason?: string | null;
  judge_model?: string | null;
  judge_provider?: string | null;
};

export type Severity = "critical" | "high" | "medium";

export type RiskSummary = {
  id: string;
  name: string;
  state: "tested" | "attempted_no_result" | "not_tested";
  tests: number;
  passed: number;
  failed: number;
  errors: number;
  inconclusive: number;
  not_applicable: number;
};

export type Counts = Record<Status, number>;

export type ScanSettings = {
  bot_id: string;
  bot_name: string;
  bot_config_version: number;
  bot_defenses: string[];
  catalog_version: string;
  suite_version: number;
  test_count: number;
  canary: string;
  providers: string[];
  // Recorded since M5: which prompt version and which providers the AI judge ran with.
  judge_prompt_version?: number;
  // Present only for a scan of the owner's own bot (M6): which setup version it ran with.
  setup?: {
    setup_id: number;
    version: number;
    selected_test_ids: string[];
    target_host: string;
    rules: { text: string; kind: string; status: string }[];
  };
  judge_providers?: string[];
  budget: { requests: number; tokens: number; seconds: number; concurrency: number };
};

export type ScanDetail = {
  scan: {
    id: number;
    bot_id: string;
    status: "running" | "completed" | "interrupted";
    note: string | null;
    started_at: number;
    finished_at: number | null;
    last_progress_at: number;
    models_used: string[];
    settings: ScanSettings;
  };
  results: ScanResult[];
  summary: {
    counts: Counts;
    risks: RiskSummary[];
    normal_requests: { tests: number; passed: number; failed: number; errors: number };
    catalog_version: string;
    catalog_source: string;
    disclaimer: string;
  };
};

export type ScanListItem = {
  id: number;
  bot_id: string;
  status: "running" | "completed" | "interrupted";
  started_at: number;
  finished_at: number | null;
  counts: Counts;
};
