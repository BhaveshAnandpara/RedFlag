import { describe, expect, it } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { buildReport } from "./report";
import type { JudgeAccuracy } from "./scan";

const base: JudgeAccuracy = {
  labeled: 4,
  unjudged: 0,
  counted: 4,
  agree: 3,
  false_alarms: 1,
  misses: 0,
  agreement: 0.75,
  small_sample: true,
  min_sample: 20,
  risks: [],
  note: "These numbers compare the judge with your own labels.",
};

const detail = makeScan([makeResult({ judge_status: "pass", judge_reason: "ok" })]);

describe("the report's judge accuracy section", () => {
  it("is left out when no labels were used", () => {
    expect(buildReport(detail)).not.toContain("## Judge accuracy");
    expect(buildReport(detail, { ...base, agreement: null, counted: 0, labeled: 0 })).not.toContain(
      "## Judge accuracy",
    );
  });

  it("states the counts, the sample size and that a small sample is only a hint", () => {
    const report = buildReport(detail, base);
    expect(report).toContain("## Judge accuracy");
    expect(report).toContain("agreed on 3 of 4 labeled results (75%)");
    expect(report).toContain("1 false alarms and 0 misses");
    expect(report).toContain("fewer than 20 labeled results");
  });

  it("does not call a large sample small", () => {
    expect(buildReport(detail, { ...base, small_sample: false })).not.toContain("fewer than 20 labeled");
  });
});
