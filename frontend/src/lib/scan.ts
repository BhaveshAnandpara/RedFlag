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

/** What proves a test: how it was decided, how often it broke, and the attacker's exact messages.
 *  Saved for tests that ran from a made plan. Standard tests, and scans from before, have none. */
export type Proof = {
  outcome: "broke" | "held" | "refused" | "couldnt_test" | "skipped" | "needs_review";
  how_sure: "confirmed_by_logs" | "confirmed_by_checks" | "reply_only" | "couldnt_confirm" | null;
  reason: string;
  what_happened: string;
  repeat_count: number;
  repeats_broke: number;
  // Index into `conversation` of the bot reply where it broke.
  broke_at_turn: number | null;
  conversation: { role: "user" | "assistant"; content: string }[];
  attacker_messages: string[];
  spec_id: string;
  spec_version: number;
  spec_hash: string;
  compared_with_last: "new" | "still_broken" | "fixed" | "first_run" | null;
  // The test's rule and what it wants caught, in plain words: what was checked.
  rule?: string | null;
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
  // What the owner says the right verdict was (W7). Null or missing when not labeled.
  label?: "pass" | "fail" | null;
  proof?: Proof | null;
};

export type AccuracyRisk = {
  risk: string;
  labeled: number;
  counted: number;
  agree: number;
  false_alarms: number;
  misses: number;
  agreement: number;
  small_sample: boolean;
};

/** How often the judge agrees with the owner's labels (GET /judge-accuracy). */
export type JudgeAccuracy = {
  labeled: number;
  unjudged: number;
  counted: number;
  agree: number;
  false_alarms: number;
  misses: number;
  agreement: number | null;
  small_sample: boolean;
  min_sample: number;
  risks: AccuracyRisk[];
  note: string;
};

/** The way a page saves labels. Pages that cannot (the saved samples) pass none. */
export type Labeling = {
  setLabel: (testId: string, correct: "pass" | "fail" | null) => Promise<void>;
  loadAccuracy: () => Promise<JudgeAccuracy>;
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
  // MITRE ATLAS techniques that best match this risk. Missing on scans saved before the tags.
  atlas?: { id: string; name: string }[];
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
    // Set when this scan is a run-again of an earlier one.
    rerun_of?: number;
  };
  judge_providers?: string[];
  // Present only for a run of a made test plan: how many tests ran, how many times at most each
  // attack ran, and the rules the user gave that got no test.
  plan?: { tests: number; runs: number; untested_rules: string[] };
  // Present only for a check of an MCP server (W8).
  mcp?: {
    target_host: string;
    server: { name: string; version: string };
    tool_count: number;
    // Every tool name and the limits, saved since the report page. Older scans have neither.
    tools?: string[];
    limits?: { calls_per_tool: number; calls_per_run: number };
    exercised: { name: string; effect: "reads" | "acts" }[];
    sandbox_confirmed: boolean;
  };
  budget: { requests: number; tokens: number; seconds: number; concurrency: number };
};

export type ScanDetail = {
  scan: {
    id: number;
    bot_id: string;
    // "paused": the bot stopped answering and the run is waiting for a person to retry or stop.
    status: "running" | "paused" | "completed" | "interrupted";
    note: string | null;
    started_at: number;
    finished_at: number | null;
    last_progress_at: number;
    models_used: string[];
    // The latest completed scan of the same project before this one (null for the first).
    previous_scan_id?: number | null;
    settings: ScanSettings;
  };
  results: ScanResult[];
  summary: {
    counts: Counts;
    risks: RiskSummary[];
    normal_requests: { tests: number; passed: number; failed: number; errors: number };
    catalog_version: string;
    catalog_source: string;
    // Where the ATLAS tags came from. Missing on scans saved before the tags.
    atlas?: { source: string; version: string; checked: string; note: string };
    disclaimer: string;
  };
};

export type ScanListItem = {
  id: number;
  bot_id: string;
  status: "running" | "paused" | "completed" | "interrupted";
  started_at: number;
  finished_at: number | null;
  counts: Counts;
};
