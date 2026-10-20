// The shapes the setup API returns (backend/src/redflag_backend/setups), and plain-words errors.

export type Source = "user" | "model" | "edited";
export type RuleStatus = "stated" | "inferred" | "unclear";

export type FieldValue = { value: string; source: Source; locked: boolean };

export type Rule = {
  id: string;
  text: string;
  kind: "allowed" | "forbidden";
  severity: "critical" | "high" | "medium";
  status: RuleStatus;
  question: string | null;
  source: Source;
  locked: boolean;
};

export type Item = { id: string; text: string; source: Source; locked: boolean };
export type Tool = {
  name: string;
  description: string;
  effect: "reads" | "acts";
  source: Source;
  locked: boolean;
};
export type Example = {
  id: string;
  text: string;
  label: "bad_reply" | "good_reply" | "conversation";
};

export type Endpoint = {
  url: string;
  format: "openai" | "custom";
  model: string;
  header_name: string;
  header_prefix: string;
  request_template: string | null;
  reply_path: string | null;
};

export type Tagged = { text: string; source: "user" | "model" };

export type Contexts = {
  tester: {
    purpose: string;
    tools: Tool[];
    weak_spots: Tagged[];
    what_to_try: Tagged[];
    notes: string;
  };
  judge: {
    purpose: string;
    rules: Tagged[];
    limits: Tagged[];
    protected_data: Tagged[];
    tools: Tool[];
    examples: Example[];
    unclear: string[];
    notes: string;
  };
  locked: string[];
};

export type Required = {
  connection: boolean;
  purpose: boolean;
  forbidden_rule: boolean;
  ready: boolean;
};

export type SetupView = {
  setup_id: number;
  project_slug: string;
  fields: {
    purpose: FieldValue;
    rules: Rule[];
    limits: Item[];
    protected_data: Item[];
    tools: Tool[];
    examples: Example[];
    notes: FieldValue;
    unclear: string[];
  };
  endpoint: Endpoint;
  connection: { ok: boolean; attempts: number; last_error: string | null };
  required: Required;
  chat: { role: "user" | "assistant"; content: string }[];
  files: { name: string; bytes: number }[];
  contexts: Contexts | null;
  followups_asked: number;
  user_messages: number;
};

export type SetupListItem = {
  setup_id: number;
  project_slug: string;
  updated_at: number;
  purpose: string;
  versions: number;
};

export type GeneratedTest = {
  id: string;
  title: string;
  risk: string | null;
  kind: "negative" | "positive";
  severity: "critical" | "high" | "medium" | null;
  prompt: string;
  goal: string;
  expected: string;
  rule: string | null;
  rule_unconfirmed: boolean;
  real_action: boolean;
  fix: string;
  selected: boolean;
  // Set on an attack variation: the strategy that rewrote it, and the test it is a copy of.
  strategy?: string;
  variation_of?: string;
};

export type Strategy = { id: string; name: string; description: string };

export type ConnectionResult = {
  status: "ok" | "error";
  http_status: number | null;
  raw_reply: string;
  parsed_reply: string;
  error: string;
  attempts_left: number;
};

export const REQUIRED_LABELS: Record<Exclude<keyof Required, "ready">, string> = {
  connection: "A working connection to your bot",
  purpose: "What the app is for",
  forbidden_rule: "At least one thing it must never do or reveal",
};

type ErrorBody = { error?: { kind?: string; message?: string; missing?: string[] } };

/** Plain words for every way a call can fail, never the raw server text. */
export function describeError(status: number, body: ErrorBody | null | undefined): string {
  if (status === 0) return "Could not reach the backend. It may still be waking up.";
  if (status === 401) return "That password was not accepted.";
  const kind = body?.error?.kind;
  switch (kind) {
    case "model_unavailable":
      return "The AI model is not available right now (its free quota may be used up). Nothing was saved. Try again later.";
    case "budget_exceeded":
      return "This setup has used up its share of the AI quota, so the AI cannot be asked again for it.";
    case "bad_model_answer":
      return "The AI answered in a way we could not read, twice. Nothing was changed. Try again.";
    case "scan_running":
      return "A scan is already running. Wait for it to finish, then try again.";
    case "too_many_tests":
      return "All 5 connection tests for this setup are used. Check the settings carefully before changing them.";
    case "not_ready": {
      const missing = (body?.error?.missing ?? [])
        .map((name) => REQUIRED_LABELS[name as keyof typeof REQUIRED_LABELS] ?? name)
        .join(", ");
      return `These items are still required: ${missing}.`;
    }
    case "bad_selection":
      return "Pick at least one test to run.";
    case "test_cap_reached":
      return "That would make too many tests for one setup. Remove some variations or generate the tests again.";
    case "unknown_strategy":
      return "Pick at least one way to vary the attacks.";
    case "no_tests":
      return "Generate the tests first.";
    case "file_type":
    case "file_too_large":
    case "too_many_files":
      return body?.error?.message ?? "That file cannot be used.";
    default:
      return "Something went wrong. Nothing was changed.";
  }
}
