import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The command a build runs (W4). Tested against a stand-in API, never a real one.
import { main } from "../../../ci/redflag-ci.mjs";

const TOKEN = "rf_secret-token-value-1234567890";
const KEY = "target-bot-key-abcdef";

type Call = { method: string; url: string; headers: Record<string, string>; body: unknown };

function standIn(responses: { status: number; body: unknown }[]) {
  const calls: Call[] = [];
  let index = 0;
  const fetchImpl = async (url: string, init: { method?: string; headers?: Record<string, string>; body?: string } = {}) => {
    calls.push({ method: init.method ?? "GET", url, headers: init.headers ?? {}, body: init.body ? JSON.parse(init.body) : undefined });
    const next = responses[Math.min(index, responses.length - 1)];
    index += 1;
    return { ok: next.status < 400, status: next.status, json: async () => next.body };
  };
  return { fetchImpl, calls };
}

const GATE = (verdict: string, reasons: string[] = []) => ({
  verdict,
  reasons,
  message: `Gate says ${verdict}. This is not a guarantee of security. It only reports what these tests checked.`,
});
const RUN = (status: string, gate: unknown) => ({
  run_id: 5,
  status,
  counts: { pass: 2, fail: verdictFails(gate), inconclusive: 0, error: 0, not_applicable: 0 },
  failures: verdictFails(gate) ? [{ test_id: "g-1", title: "Refund promise", severity: "critical", evidence: "It gave in." }] : [],
  gate,
});
function verdictFails(gate: unknown): number {
  return (gate as { verdict: string }).verdict === "fail" ? 1 : 0;
}

async function run(argv: string[], env: Record<string, string>, responses: { status: number; body: unknown }[]) {
  const { fetchImpl, calls } = standIn(responses);
  const lines: string[] = [];
  const code: number = await main(argv, env, fetchImpl, (line: string) => lines.push(line), { sleep: async () => undefined, now: () => 0 });
  return { code, calls, output: lines.join("\n") };
}

const ENV = { REDFLAG_URL: "https://api.example.test/", REDFLAG_TOKEN: TOKEN, REDFLAG_TARGET_KEY: KEY };

describe("the CI command", () => {
  it("starts a run with the token, waits for it, prints the gate and exits 0 on a pass", async () => {
    const result = await run([], ENV, [
      { status: 202, body: { run_id: 5, status_url: "/ci/runs/5" } },
      { status: 200, body: RUN("running", GATE("running")) },
      { status: 200, body: RUN("completed", GATE("pass")) },
    ]);
    expect(result.code).toBe(0);
    expect(result.calls[0]).toMatchObject({ method: "POST", url: "https://api.example.test/ci/runs" });
    expect(result.calls[0].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(result.calls[0].body).toEqual({ key: KEY, fail_on: "critical", fail_on_unclear: false });
    expect(result.calls[2].url).toBe("https://api.example.test/ci/runs/5");
    expect(result.output).toContain("Gate says pass.");
  });

  it("exits 1 on a failed gate and lists the failures", async () => {
    const result = await run([], ENV, [
      { status: 202, body: { run_id: 5 } },
      { status: 200, body: RUN("completed", GATE("fail", ["Refund promise (critical): AI judge (FAIL): It gave in."])) },
    ]);
    expect(result.code).toBe(1);
    expect(result.output).toContain("Refund promise (critical): AI judge (FAIL): It gave in.");
  });

  it("passes the options on and reads them in the way a build writes them", async () => {
    const result = await run(["--fail-on", "high", "--fail-on-unclear", "--version", "3"], ENV, [
      { status: 202, body: { run_id: 5 } },
      { status: 200, body: RUN("completed", GATE("pass")) },
    ]);
    expect(result.calls[0].body).toEqual({ key: KEY, fail_on: "high", fail_on_unclear: true, version: 3 });
  });

  it("does not send a key when the bot needs none", async () => {
    const withoutKey: Record<string, string> = { ...ENV };
    delete withoutKey.REDFLAG_TARGET_KEY;
    const result = await run([], withoutKey, [
      { status: 202, body: { run_id: 5 } },
      { status: 200, body: RUN("completed", GATE("pass")) },
    ]);
    expect(result.calls[0].body).toEqual({ key: null, fail_on: "critical", fail_on_unclear: false });
  });

  it("exits 2 with a plain message when something needed is missing, calling nothing", async () => {
    for (const missing of ["REDFLAG_URL", "REDFLAG_TOKEN"]) {
      const env: Record<string, string> = { ...ENV };
      delete env[missing];
      const result = await run([], env, [{ status: 200, body: {} }]);
      expect(result.code).toBe(2);
      expect(result.output).toContain(missing);
      expect(result.calls).toEqual([]);
    }
  });

  it("exits 2 for a bad option and for a refused token or a busy server, in plain words", async () => {
    expect((await run(["--fail-on", "whenever"], ENV, [{ status: 200, body: {} }])).code).toBe(2);
    const refused = await run([], ENV, [{ status: 401, body: {} }]);
    expect(refused.code).toBe(2);
    expect(refused.output).toMatch(/token was not accepted/i);
    const busy = await run([], ENV, [{ status: 409, body: { error: { kind: "scan_running" } } }]);
    expect(busy.code).toBe(2);
    expect(busy.output).toMatch(/already running/i);
  });

  it("exits 2 when the run ends in an error, and never counts that as a pass", async () => {
    const result = await run([], ENV, [
      { status: 202, body: { run_id: 5 } },
      { status: 200, body: RUN("completed", GATE("error", ["The run could not be completed."])) },
    ]);
    expect(result.code).toBe(2);
    expect(result.output).toContain("The run could not be completed.");
  });

  it("gives up with exit 2 when the run takes longer than the timeout", async () => {
    const { fetchImpl } = standIn([
      { status: 202, body: { run_id: 5 } },
      { status: 200, body: RUN("running", GATE("running")) },
    ]);
    let clock = 0;
    const lines: string[] = [];
    const code: number = await main(["--timeout", "30", "--poll", "10"], ENV, fetchImpl, (l: string) => lines.push(l), {
      sleep: async () => {
        clock += 10_000;
      },
      now: () => clock,
    });
    expect(code).toBe(2);
    expect(lines.join("\n")).toMatch(/did not finish within 30 seconds/i);
  });

  it("never prints the token or the key, even when things go wrong", async () => {
    for (const responses of [
      [{ status: 401, body: {} }],
      [{ status: 202, body: { run_id: 5 } }, { status: 200, body: RUN("completed", GATE("fail", ["x"])) }],
      [{ status: 500, body: { detail: `oops ${TOKEN} ${KEY}` } }],
    ]) {
      const result = await run([], ENV, responses);
      expect(result.output).not.toContain(TOKEN);
      expect(result.output).not.toContain(KEY);
    }
  });
});

describe("the GitHub Action", () => {
  const root = resolve(__dirname, "../../..");
  const action = readFileSync(resolve(root, ".github/actions/redflag-scan/action.yml"), "utf8");

  it("takes the address, token, key and options as inputs and runs the command", () => {
    for (const name of ["url", "token", "target-key", "fail-on", "fail-on-unclear", "version", "timeout"]) {
      expect(action).toContain(`  ${name}:`);
    }
    expect(action).toContain("redflag-ci.mjs");
    expect(action).toContain("REDFLAG_TOKEN");
  });

  it("is documented with a scheduled example that keeps the token and key in secrets", () => {
    const example = readFileSync(resolve(root, "docs/examples/redflag-ci.yml"), "utf8");
    expect(example).toContain("schedule:");
    expect(example).toContain("secrets.REDFLAG_TOKEN");
    expect(example).toContain("secrets.REDFLAG_TARGET_KEY");
    expect(example).not.toMatch(/rf_[A-Za-z0-9_-]{20,}/);
  });
});
