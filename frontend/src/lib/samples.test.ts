import { describe, expect, it } from "vitest";

import realSamples from "@/data/sample-scans.json";
import { many, makeResult, makeScan } from "@/test-support/fixtures";
// The same rules the export script uses to refuse an unsafe file.
import { findProblems } from "../../scripts/sample-rules.mjs";

const weak = () => makeScan(many(3, "pass"), { id: 5, botId: "acme-weak" });
const hardened = () => makeScan(many(3, "pass"), { id: 6, botId: "acme-hardened" });
const file = (scans: unknown[]) => ({ format_version: 1, saved_at: "2026-10-20T12:00:00Z", scans });

describe("the rules for a saved sample file", () => {
  it("accepts one completed weak scan and one completed hardened scan", () => {
    expect(findProblems(file([weak(), hardened()]))).toEqual([]);
  });

  it("accepts an empty file, which the public page shows as 'No saved scans yet'", () => {
    expect(findProblems(file([]))).toEqual([]);
  });

  it("refuses a scan that is not completed", () => {
    const running = makeScan(many(2, "pass"), { id: 5, botId: "acme-weak", status: "running" });
    expect(findProblems(file([running, hardened()])).join(" ")).toMatch(/not completed/i);
    const interrupted = makeScan(many(2, "pass"), { id: 6, botId: "acme-hardened", status: "interrupted" });
    expect(findProblems(file([weak(), interrupted])).join(" ")).toMatch(/not completed/i);
  });

  it("needs exactly one weak and one hardened scan", () => {
    expect(findProblems(file([weak()])).join(" ")).toMatch(/hardened/i);
    expect(findProblems(file([hardened()])).join(" ")).toMatch(/weak/i);
    expect(findProblems(file([weak(), weak(), hardened()])).join(" ")).toMatch(/exactly/i);
  });

  it("refuses a result with no evidence, or a verdict with no recorded model", () => {
    const noEvidence = makeScan([makeResult({ evidence: "" })], { id: 5, botId: "acme-weak" });
    expect(findProblems(file([noEvidence, hardened()])).join(" ")).toMatch(/evidence/i);
    const noModel = makeScan([makeResult({ status: "fail", model: null, provider: null })], {
      id: 5,
      botId: "acme-weak",
    });
    expect(findProblems(file([noModel, hardened()])).join(" ")).toMatch(/model/i);
    // An error legitimately has no model, so that is allowed.
    const errored = makeScan([makeResult({ status: "error", model: null, provider: null })], {
      id: 5,
      botId: "acme-weak",
    });
    expect(findProblems(file([errored, hardened()]))).toEqual([]);
  });

  it("refuses anything shaped like a key, token or connection string, without repeating it", () => {
    const shapes = [
      "gsk_" + "a".repeat(30),
      "AIza" + "b".repeat(30),
      "sk-or-" + "c".repeat(30),
      "Bearer " + "d".repeat(30),
      "postgresql://user:pw@host/db",
    ];
    for (const shape of shapes) {
      const leaky = makeScan([makeResult({ reply: `here you go ${shape}` })], {
        id: 5,
        botId: "acme-weak",
      });
      const problems = findProblems(file([leaky, hardened()]));
      expect(problems.join(" ")).toMatch(/shaped like a key/i);
      expect(problems.join(" ")).not.toContain(shape);
    }
  });

  it("allows the random fake canary secrets that a leak test legitimately shows", () => {
    const withCanary = makeScan([makeResult({ evidence: 'The reply contains: "CANARY-cdf92979ec7a"' })], {
      id: 5,
      botId: "acme-weak",
    });
    expect(findProblems(file([withCanary, hardened()]))).toEqual([]);
  });

  it("refuses a file in the wrong format", () => {
    expect(findProblems({ format_version: 2, scans: [] }).join(" ")).toMatch(/format/i);
    expect(findProblems({ format_version: 1, scans: "no" }).join(" ")).toMatch(/list/i);
  });
});

describe("the rules for the AI judge fields in a saved sample", () => {
  const judgedResult = (extra: Record<string, unknown>) =>
    makeScan(
      [
        makeResult({
          status: "fail",
          rule_status: "pass",
          rule_evidence: "rules output",
          judge_status: "fail",
          judge_reason: "The reply gives away another customer's address.",
          judge_model: "judge-model",
          judge_provider: "judge",
          ...extra,
        }),
      ],
      { id: 5, botId: "acme-weak" },
    );

  it("accepts results with well-shaped judge fields, and results with none", () => {
    expect(findProblems(file([judgedResult({}), hardened()]))).toEqual([]);
    expect(findProblems(file([weak(), hardened()]))).toEqual([]);
  });

  it("accepts an unavailable judge, which has a cause but no model", () => {
    const unavailable = judgedResult({
      status: "inconclusive",
      judge_status: "unavailable",
      judge_reason: "malformed answer",
      judge_model: null,
      judge_provider: null,
    });
    expect(findProblems(file([unavailable, hardened()]))).toEqual([]);
  });

  it("refuses a judge status that is not pass, fail or unavailable", () => {
    const problems = findProblems(file([judgedResult({ judge_status: "maybe" }), hardened()]));
    expect(problems.join(" ")).toMatch(/judge status/i);
  });

  it("refuses a judge pass or fail with no reason or no model", () => {
    expect(
      findProblems(file([judgedResult({ judge_reason: "" }), hardened()])).join(" "),
    ).toMatch(/judge.*reason/i);
    expect(
      findProblems(file([judgedResult({ judge_model: null }), hardened()])).join(" "),
    ).toMatch(/judge.*model/i);
  });

  it("refuses a key-shaped string in a judge reason, without repeating it", () => {
    const key = "AIza" + "e".repeat(30);
    const problems = findProblems(
      file([judgedResult({ judge_reason: `It printed ${key}` }), hardened()]),
    );
    expect(problems.join(" ")).toMatch(/shaped like a key/i);
    expect(problems.join(" ")).not.toContain(key);
  });
});

describe("the committed sample file", () => {
  it("passes the same rules", () => {
    expect(findProblems(realSamples)).toEqual([]);
  });
});
