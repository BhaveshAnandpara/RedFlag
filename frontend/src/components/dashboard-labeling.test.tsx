import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeResult, makeScan } from "@/test-support/fixtures";

import { Dashboard } from "./dashboard";

// Label mode (W7): the owner says whether the judge was right, and the dashboard shows how often
// it agrees with those labels, with the number of results each figure rests on.

const accuracy = (overrides: Record<string, unknown> = {}) => ({
  labeled: 2,
  unjudged: 0,
  counted: 2,
  agree: 1,
  false_alarms: 1,
  misses: 0,
  agreement: 0.5,
  small_sample: true,
  min_sample: 20,
  risks: [
    { risk: "LLM02", labeled: 2, counted: 2, agree: 1, false_alarms: 1, misses: 0, agreement: 0.5, small_sample: true },
  ],
  note: "These numbers compare the judge with your own labels.",
  ...overrides,
});

function scanWith(...results: Parameters<typeof makeResult>[0][]) {
  return makeScan(results.map((r) => makeResult(r)));
}

async function conversations(detail = scanWith({ test_id: "g-1", title: "Leak test", judge_status: "pass", judge_reason: "fine", status: "pass" }), labeling?: unknown) {
  const user = userEvent.setup();
  render(
    <Dashboard
      detail={detail}
      history={[]}
      onOpen={() => undefined}
      loadScan={async () => detail}
      labeling={labeling as never}
    />,
  );
  await user.click(screen.getByRole("tab", { name: "Conversations" }));
  return user;
}

describe("label mode", () => {
  it("is not offered when the page has no way to save labels, such as the saved samples", async () => {
    await conversations();
    expect(screen.queryByRole("region", { name: "Judge accuracy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Judge was right" })).not.toBeInTheDocument();
  });

  it("saying the judge was right saves its own verdict as the correct one", async () => {
    const setLabel = vi.fn().mockResolvedValue(undefined);
    const user = await conversations(undefined, { setLabel, loadAccuracy: async () => accuracy() });
    await user.click(screen.getByRole("button", { name: "Judge was right" }));
    expect(setLabel).toHaveBeenCalledWith("g-1", "pass");
  });

  it("saying the judge was wrong saves the opposite verdict", async () => {
    const setLabel = vi.fn().mockResolvedValue(undefined);
    const detail = scanWith({ test_id: "g-9", title: "Odd one", judge_status: "fail", judge_reason: "no", status: "fail" });
    const user = await conversations(detail, { setLabel, loadAccuracy: async () => accuracy() });
    await user.click(screen.getByRole("button", { name: "Judge was wrong" }));
    expect(setLabel).toHaveBeenCalledWith("g-9", "pass");
  });

  it("shows the label that is saved and lets it be cleared", async () => {
    const setLabel = vi.fn().mockResolvedValue(undefined);
    const detail = scanWith({ test_id: "g-1", title: "Leak test", judge_status: "pass", judge_reason: "fine", status: "pass", label: "fail" });
    const user = await conversations(detail, { setLabel, loadAccuracy: async () => accuracy() });
    expect(screen.getByText(/You marked the judge wrong/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear label" }));
    expect(setLabel).toHaveBeenCalledWith("g-1", null);
    await waitFor(() => expect(screen.queryByText(/You marked the judge wrong/)).not.toBeInTheDocument());
  });

  it("does not offer a label where the judge gave no verdict", async () => {
    const detail = scanWith({ test_id: "g-2", title: "No verdict", judge_status: "unavailable", status: "inconclusive" });
    await conversations(detail, { setLabel: vi.fn(), loadAccuracy: async () => accuracy() });
    expect(screen.queryByRole("button", { name: "Judge was right" })).not.toBeInTheDocument();
    expect(screen.getByText(/The judge gave no verdict here/)).toBeInTheDocument();
  });
});

describe("the accuracy panel", () => {
  it("shows agreement, false alarms and misses, with the sample size and a small-sample warning", async () => {
    await conversations(undefined, { setLabel: vi.fn(), loadAccuracy: async () => accuracy() });
    const panel = await screen.findByRole("region", { name: "Judge accuracy" });
    expect(panel).toHaveTextContent("Agreed with you on 1 of 2 labeled results (50%)");
    expect(panel).toHaveTextContent("False alarms: 1");
    expect(panel).toHaveTextContent("Misses: 0");
    expect(panel).toHaveTextContent(/small sample/i);
    const row = within(panel).getByRole("row", { name: /LLM02/ });
    expect(row).toHaveTextContent("1 of 2");
  });

  it("says plainly that nothing has been measured yet when there are no labels", async () => {
    await conversations(undefined, {
      setLabel: vi.fn(),
      loadAccuracy: async () =>
        accuracy({ labeled: 0, counted: 0, agree: 0, false_alarms: 0, agreement: null, risks: [], note: "The judge has not been checked for accuracy yet." }),
    });
    const panel = await screen.findByRole("region", { name: "Judge accuracy" });
    expect(panel).toHaveTextContent("The judge has not been checked for accuracy yet.");
    expect(panel).not.toHaveTextContent("%");
  });

  it("is not called a small sample once there are enough labels", async () => {
    await conversations(undefined, {
      setLabel: vi.fn(),
      loadAccuracy: async () => accuracy({
          small_sample: false,
          counted: 24,
          labeled: 24,
          agree: 22,
          agreement: 22 / 24,
          risks: [{ risk: "LLM02", labeled: 24, counted: 24, agree: 22, false_alarms: 1, misses: 1, agreement: 22 / 24, small_sample: false }],
        }),
    });
    const panel = await screen.findByRole("region", { name: "Judge accuracy" });
    expect(panel).not.toHaveTextContent(/small sample/i);
    expect(panel).toHaveTextContent("22 of 24");
  });

  it("refreshes after a label is saved", async () => {
    const loadAccuracy = vi.fn().mockResolvedValue(accuracy());
    const user = await conversations(undefined, { setLabel: vi.fn().mockResolvedValue(undefined), loadAccuracy });
    await screen.findByRole("region", { name: "Judge accuracy" });
    const before = loadAccuracy.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Judge was right" }));
    await waitFor(() => expect(loadAccuracy.mock.calls.length).toBeGreaterThan(before));
  });
});
