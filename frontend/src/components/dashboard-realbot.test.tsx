import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ScanDetail } from "@/lib/scan";
import { makeResult, makeScan } from "@/test-support/fixtures";

import { Dashboard } from "./dashboard";

// A scan of the owner's own bot (M6): the judge decided alone, and there is no tool log.

const RULES = [{ text: "Must never transfer money.", kind: "forbidden", status: "stated" }];

const REAL = makeScan(
  [
    makeResult({
      test_id: "g-1",
      title: "Talk it out of its rules",
      status: "fail",
      severity: "high",
      risk: "LLM01",
      reply: "Sure, I moved the money.",
      evidence: "AI judge (FAIL): It gave in.",
      rule_status: null,
      rule_evidence: null,
      judge_status: "fail",
      judge_reason: "It gave in.",
      judge_model: "judge-model",
      judge_provider: "judge",
      model: "external endpoint (bot.example)",
      provider: "http",
      tool_calls: [],
    }),
  ],
  { id: 21, botId: "target-5", setup: { version: 2, rules: RULES } },
);

function renderDashboard(detail: ScanDetail, extra: Partial<ComponentProps<typeof Dashboard>> = {}) {
  const props = {
    detail,
    history: [],
    onOpen: vi.fn(),
    loadScan: vi.fn(async () => detail),
    ...extra,
  };
  render(<Dashboard {...props} />);
  return { user: userEvent.setup() };
}

describe("a scan of the owner's own bot", () => {
  it("says in the conversation that the tool log is not available and that no plain rule applied", async () => {
    const { user } = renderDashboard(REAL);
    await user.click(screen.getByRole("tab", { name: "Conversations" }));
    const item = screen.getByRole("listitem", { name: "Test result: Talk it out of its rules" });
    await user.click(within(item).getByRole("button", { name: /show evidence/i }));
    expect(within(item).getByText(/The tool log is not available for this kind of target\./)).toBeInTheDocument();
    const rules = within(item).getByRole("group", { name: "Plain rules" });
    expect(within(rules).getByText(/No plain rule applied to this bot/)).toBeInTheDocument();
    expect(within(rules).queryByText("FAIL")).not.toBeInTheDocument();
    const judge = within(item).getByRole("group", { name: "AI judge" });
    expect(within(judge).getByText("It gave in.")).toBeInTheDocument();
    expect(within(item).queryByText(/disagreed/)).not.toBeInTheDocument();
  });

  it("shows the target and the setup version in the settings, and no planted secret", () => {
    renderDashboard(REAL);
    expect(screen.getByText(/Target: bot\.example/)).toBeInTheDocument();
    expect(screen.getByText(/Setup version 2/)).toBeInTheDocument();
    expect(screen.queryByText(/Secret planted for this scan/)).not.toBeInTheDocument();
  });

  it("says in the conclusion that no plain rules ran and the judge decided alone", () => {
    renderDashboard(REAL);
    const box = screen.getByTestId("conclusion");
    expect(within(box).getByText(/No plain rules ran on this bot/)).toBeInTheDocument();
    expect(box.textContent).not.toMatch(/\b(safe|secure|ready)\b/i);
  });

  it("lists which rules changed in Compare between two setup versions", async () => {
    const earlier = makeScan(
      [
        makeResult({
          test_id: "g-1",
          title: "Talk it out of its rules",
          status: "pass",
          judge_status: "pass",
          judge_reason: "ok",
          rule_status: null,
        }),
      ],
      { id: 20, botId: "target-5", setup: { version: 1, rules: [] } },
    );
    const { user } = renderDashboard(REAL, {
      history: [
        { id: 20, bot_id: "target-5", status: "completed", started_at: 1, finished_at: 2, counts: { pass: 1, fail: 0, inconclusive: 0, error: 0, not_applicable: 0 } },
      ],
      loadScan: vi.fn(async () => earlier),
    });
    await user.click(screen.getByRole("tab", { name: "Compare" }));
    await user.selectOptions(screen.getByLabelText(/compare with/i), "20");
    expect(await screen.findByText(/Rules that changed between the two setup versions/i)).toBeInTheDocument();
    expect(screen.getByText(/Must never transfer money\./)).toBeInTheDocument();
  });
});
