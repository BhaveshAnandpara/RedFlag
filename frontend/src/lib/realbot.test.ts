import { describe, expect, it } from "vitest";

import { many, makeResult, makeScan } from "@/test-support/fixtures";

import { compareScans, conclusionText, isRealBot } from "./analytics";
import { buildReport } from "./report";

// Scans of the owner's own bot (M6): decided by the AI judge alone, from the reply alone.

const realBotResult = (status: "pass" | "fail" | "inconclusive", judge: "pass" | "fail" | "unavailable") =>
  makeResult({
    status,
    rule_status: null,
    rule_evidence: null,
    judge_status: judge,
    judge_reason: `judge said ${judge}`,
    judge_model: "judge-model",
    model: "external endpoint (bot.example)",
    provider: "http",
  });

const RULES_V1 = [{ text: "Must never transfer money.", kind: "forbidden", status: "stated" }];
const RULES_V2 = [
  { text: "Must never transfer money.", kind: "forbidden", status: "stated" },
  { text: "Never reveal account numbers.", kind: "forbidden", status: "stated" },
];

describe("a scan of the owner's own bot", () => {
  const real = makeScan([realBotResult("fail", "fail"), realBotResult("pass", "pass")], {
    setup: { version: 1, rules: RULES_V1 },
  });

  it("is told apart from a demo-bot scan by the setup it ran with", () => {
    expect(isRealBot(real)).toBe(true);
    expect(isRealBot(makeScan(many(2, "pass")))).toBe(false);
  });

  it("says there was no second opinion from plain rules and that the judge decided from the reply alone", () => {
    const text = conclusionText(real);
    expect(text).toContain("No plain rules ran on this bot");
    expect(text).toContain("decided by an AI judge from the bot's reply alone");
    expect(text).toContain("has not been checked for accuracy");
    expect(text).not.toMatch(/\b(safe|secure|ready)\b/i);
  });

  it("keeps the demo-bot conclusion exactly as before", () => {
    expect(conclusionText(makeScan(many(2, "pass")))).not.toContain("No plain rules ran on this bot");
  });

  it("lists the rules that were added or removed between two setup versions", () => {
    const one = makeScan([realBotResult("pass", "pass")], { id: 1, setup: { version: 1, rules: RULES_V1 } });
    const two = makeScan([realBotResult("pass", "pass")], { id: 2, setup: { version: 2, rules: RULES_V2 } });
    expect(compareScans(one, two).ruleChanges).toEqual({
      added: ["Never reveal account numbers."],
      removed: [],
    });
    expect(compareScans(two, one).ruleChanges).toEqual({
      added: [],
      removed: ["Never reveal account numbers."],
    });
  });

  it("has no rule changes to show for demo scans, and an empty change when the rules are the same", () => {
    const a = makeScan(many(1, "pass"), { id: 1 });
    const b = makeScan(many(1, "pass"), { id: 2 });
    expect(compareScans(a, b).ruleChanges).toBeNull();
    const same1 = makeScan([realBotResult("pass", "pass")], { id: 3, setup: { version: 1, rules: RULES_V1 } });
    const same2 = makeScan([realBotResult("pass", "pass")], { id: 4, setup: { version: 2, rules: RULES_V1 } });
    expect(compareScans(same1, same2).ruleChanges).toEqual({ added: [], removed: [] });
  });

  it("puts the setup version, the rules in force and the missing tool log in the report", () => {
    const report = buildReport(real);
    expect(report).toContain("Setup version 1");
    expect(report).toContain("## Rules in force");
    expect(report).toContain("Must never transfer money.");
    expect(report).toMatch(/tool log is not available/i);
    expect(report).toContain("bot.example");
    expect(report).not.toContain("Secret planted");
    expect(report).not.toMatch(/\b(safe|secure|ready)\b/i);
  });

  it("does not add those sections to a demo-bot report", () => {
    const report = buildReport(makeScan(many(1, "pass")));
    expect(report).not.toContain("## Rules in force");
    expect(report).toContain("Secret planted for this scan");
  });
});
