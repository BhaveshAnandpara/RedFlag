import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { runDelta } from "@/lib/analytics";
import { makeResult, makeScan } from "@/test-support/fixtures";

import { Dashboard } from "./dashboard";

// Run again (W3): what changed since the last run of the same tests.

const result = (id: string, status: "pass" | "fail" | "inconclusive" | "error", title = `Test ${id}`) =>
  makeResult({ test_id: id, title, status, rule_status: null, judge_status: status === "fail" ? "fail" : "pass", judge_reason: "r" });

const BEFORE = makeScan(
  [result("a", "fail"), result("b", "fail"), result("c", "pass"), result("d", "pass"), result("e", "pass"), result("gone", "fail")],
  { id: 10, botId: "target-5", setup: { version: 1, rules: [] } },
);
const NOW = makeScan(
  [result("a", "pass"), result("b", "fail"), result("c", "fail"), result("d", "pass"), result("e", "error"), result("fresh", "fail")],
  { id: 11, botId: "target-5", setup: { version: 1, rules: [] } },
);

describe("what changed since the last run", () => {
  it("sorts every test into fixed, new problem, still failing, unclear now, new or no longer run", () => {
    const delta = runDelta(NOW, BEFORE);
    expect(delta.previousId).toBe(10);
    expect(delta.fixed.map((t) => t.title)).toEqual(["Test a"]);
    expect(delta.newProblems.map((t) => t.title)).toEqual(["Test c", "Test fresh"]);
    expect(delta.stillFailing.map((t) => t.title)).toEqual(["Test b"]);
    expect(delta.unclearNow.map((t) => t.title)).toEqual(["Test e"]);
    expect(delta.noLongerRun.map((t) => t.title)).toEqual(["Test gone"]);
  });

  it("says in counts what changed and never calls the result good news or safe", () => {
    const delta = runDelta(NOW, BEFORE);
    expect(delta.summary).toBe("Since scan #10: 1 fixed, 2 new problems, 1 still failing, 1 now unclear.");
    expect(delta.summary).not.toMatch(/\b(safe|secure|ready|improved)\b/i);
  });

  it("uses the singular and says when nothing changed", () => {
    const same = makeScan([result("a", "pass")], { id: 12, botId: "target-5" });
    const earlier = makeScan([result("a", "pass")], { id: 9, botId: "target-5" });
    expect(runDelta(same, earlier).summary).toBe("Since scan #9: nothing changed in the tests that were run both times.");
  });
});

describe("the comparison at the top of the Overview", () => {
  function show(previous: typeof BEFORE | null) {
    render(<Dashboard detail={NOW} history={[]} onOpen={vi.fn()} loadScan={vi.fn(async () => NOW)} previous={previous} />);
  }

  it("lists what was fixed and what is a new problem, in words", () => {
    show(BEFORE);
    const box = screen.getByRole("region", { name: "Since the last run" });
    expect(within(box).getByText(/Since scan #10: 1 fixed, 2 new problems/)).toBeInTheDocument();
    expect(within(within(box).getByRole("list", { name: "Fixed" })).getByText("Test a")).toBeInTheDocument();
    expect(within(within(box).getByRole("list", { name: "New problems" })).getByText("Test c")).toBeInTheDocument();
    expect(within(within(box).getByRole("list", { name: "Still failing" })).getByText("Test b")).toBeInTheDocument();
  });

  it("is not shown when there is no earlier scan", () => {
    show(null);
    expect(screen.queryByRole("region", { name: "Since the last run" })).not.toBeInTheDocument();
  });
});
