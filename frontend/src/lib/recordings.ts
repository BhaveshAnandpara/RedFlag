// The shape of the file the recording script writes (frontend/src/data/recordings.json).

export type ToolRecord = {
  tool: string;
  arguments: Record<string, unknown>;
  outcome: string;
  detail: string;
};

export type Verdict = {
  status: "pass" | "fail" | "inconclusive";
  evidence: string;
  rule: string;
};

export type Run = {
  bot: string;
  defenses: string[];
  reply: string;
  tool_calls: ToolRecord[];
  verdict: Verdict;
  model: string | null;
  provider: string | null;
  attempts: { provider: string; model: string | null; outcome: string; latency_ms: number }[];
  recorded_at: string;
  error: string | null;
};

export type AttackRecord = {
  id: string;
  title: string;
  question: string;
  message: string;
  runs: Record<string, Run>;
};

export type Recordings = {
  format_version: number;
  generated_at: string;
  attacks: AttackRecord[];
};
