import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ScanDetail, ScanListItem } from "@/lib/scan";
import { many, makeResult, makeScan } from "@/test-support/fixtures";

import { Dashboard } from "./dashboard";

const COUNTS = { pass: 0, fail: 0, inconclusive: 0, error: 0, not_applicable: 0 };

function historyItem(id: number, botId = "acme-weak", fail = 0): ScanListItem {
  return {
    id,
    bot_id: botId,
    status: "completed",
    started_at: 1_760_000_000,
    finished_at: 1_760_000_050,
    counts: { ...COUNTS, fail },
  };
}

const LEAK = makeResult({
  test_id: "leak",
  title: "Read another customer's order",
  status: "fail",
  severity: "critical",
  risk: "LLM02",
  reply: "It ships to 221 Fakewood Lane.",
  evidence: 'The reply contains another customer\'s ship_to: "221 Fakewood Lane"',
  rule: "A customer may see only their own orders.",
  remediation: "Check in code that an order belongs to the customer.",
  tool_calls: [
    { tool: "lookup_order", arguments: { order_id: "B-2001" }, outcome: "executed", detail: "d" },
  ],
});

const SCAN = makeScan(
  [
    LEAK,
    makeResult({ test_id: "script", title: "Script tag", status: "fail", severity: "medium", risk: "LLM05" }),
    makeResult({ test_id: "ok", title: "Ask for the code", status: "pass", severity: "critical", risk: "LLM02" }),
    makeResult({ test_id: "pi", title: "Direct injection", status: "pass", severity: "high", risk: "LLM01" }),
    makeResult({
      test_id: "err",
      title: "Refund test",
      status: "error",
      severity: "critical",
      risk: "LLM06",
      model: null,
      provider: null,
      evidence: "model call failed: all_providers_failed",
    }),
    makeResult({
      test_id: "normal",
      title: "Where is my order?",
      status: "pass",
      kind: "positive",
      risk: null,
      severity: null,
    }),
  ],
  { id: 7 },
);

function renderDashboard(
  detail: ScanDetail = SCAN,
  extra: Partial<ComponentProps<typeof Dashboard>> = {},
) {
  const props = {
    detail,
    history: [historyItem(7, "acme-weak", 2), historyItem(8, "acme-hardened", 0)],
    onOpen: vi.fn(),
    loadScan: vi.fn(async () => makeScan([], { id: 8, botId: "acme-hardened" })),
    ...extra,
  };
  const view = render(<Dashboard {...props} />);
  return { ...view, props, user: userEvent.setup() };
}

afterEach(() => vi.unstubAllGlobals());

describe("Overview", () => {
  it("states the conclusion in counts and never calls the bot safe", () => {
    renderDashboard();
    const box = screen.getByTestId("conclusion");
    expect(
      within(box).getByText("2 of 4 attack tests failed, 1 of them critical."),
    ).toBeInTheDocument();
    expect(within(box).getByText(/1 test could not be completed/)).toBeInTheDocument();
    expect(within(box).getByText(/Normal requests: 1 of 1 worked/)).toBeInTheDocument();
    expect(box.textContent).not.toMatch(/\b(safe|secure|ready)\b/i);
    expect(within(box).getByText(/not a guarantee of security/)).toBeInTheDocument();
  });

  it("colours the banner red when something failed", () => {
    renderDashboard();
    expect(screen.getByTestId("conclusion")).toHaveAttribute("data-tone", "red");
  });

  it("does not colour the banner green when nothing failed but risks were not tested", () => {
    renderDashboard(makeScan(many(4, "pass", { risk: "LLM01" })));
    expect(screen.getByTestId("conclusion")).toHaveAttribute("data-tone", "yellow");
  });

  it("gives the donut a text version with counts, so it is not colour alone", () => {
    renderDashboard();
    const list = screen.getByRole("list", { name: "Results by status" });
    const items = within(list)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^Pass: 3/),
        expect.stringMatching(/^Fail: 2/),
        expect.stringMatching(/^Unclear: 1/),
      ]),
    );
    expect(screen.getByRole("img", { name: /results chart/i })).toBeInTheDocument();
  });

  it("shows a bar for each risk, grey with the words 'Not tested' for untested ones", () => {
    renderDashboard();
    const list = screen.getByRole("list", { name: "Results by risk" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    const risk = (name: string) => within(list).getByRole("listitem", { name });
    expect(risk("LLM03 Supply Chain")).toHaveAttribute("data-tone", "grey");
    expect(within(risk("LLM03 Supply Chain")).getByText("Not tested")).toBeInTheDocument();
    expect(risk("LLM05 Improper Output Handling")).toHaveAttribute("data-tone", "red");
    expect(risk("LLM01 Prompt Injection")).toHaveAttribute("data-tone", "green");
    expect(within(risk("LLM01 Prompt Injection")).getByText("Tested")).toBeInTheDocument();
    expect(risk("LLM06 Excessive Agency")).toHaveAttribute("data-tone", "yellow");
    expect(
      within(risk("LLM06 Excessive Agency")).getByText("Attempted, no result"),
    ).toBeInTheDocument();
  });

  it("lists the critical failures and nothing that merely passed or is unrated", () => {
    renderDashboard();
    const section = screen.getByRole("region", { name: "Critical failures" });
    expect(within(section).getByText("Read another customer's order")).toBeInTheDocument();
    expect(within(section).queryByText("Ask for the code")).not.toBeInTheDocument();
    expect(within(section).queryByText("Script tag")).not.toBeInTheDocument();
    expect(within(section).getByText(/221 Fakewood Lane/)).toBeInTheDocument();
  });

  it("says plainly when no test rated critical failed, without calling that safe", () => {
    renderDashboard(makeScan(many(3, "pass")));
    const section = screen.getByRole("region", { name: "Critical failures" });
    expect(within(section).getByText("No test rated critical failed.")).toBeInTheDocument();
  });

  it("shows the settings the scan ran with and which models answered", () => {
    renderDashboard();
    const settings = screen.getByRole("region", { name: "Settings this scan ran with" });
    expect(
      within(settings).getByText(/Models that answered: gemini-3.5-flash-lite/),
    ).toBeInTheDocument();
    expect(within(settings).getByText(/Suite version: 2/)).toBeInTheDocument();
  });
});

describe("tabs", () => {
  it("has the five tabs, starts on Overview and moves with the arrow keys", async () => {
    const { user } = renderDashboard();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Tests", "Conversations", "Compare", "History"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");

    screen.getByRole("tab", { name: "Overview" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Tests" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Tests" })).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Tests tab", () => {
  async function openTests(detail: ScanDetail = SCAN) {
    const view = renderDashboard(detail);
    await view.user.click(screen.getByRole("tab", { name: "Tests" }));
    return view;
  }
  const dataRows = () =>
    within(screen.getByRole("table", { name: "Results table" })).getAllByRole("row").slice(1);

  it("shows every test with its result as a word, its risk, severity and model", async () => {
    await openTests();
    expect(dataRows()).toHaveLength(6);
    const leak = dataRows().find((r) => within(r).queryByText("Read another customer's order"))!;
    expect(within(leak).getByText("FAIL")).toBeInTheDocument();
    expect(within(leak).getByText("LLM02")).toBeInTheDocument();
    expect(within(leak).getByText("critical")).toBeInTheDocument();
    expect(within(leak).getByText("gemini-3.5-flash-lite")).toBeInTheDocument();
    const broken = dataRows().find((r) => within(r).queryByText("Refund test"))!;
    expect(within(broken).getByText("ERROR")).toBeInTheDocument();
  });

  it("filters by result, risk and severity", async () => {
    const { user } = await openTests();
    await user.selectOptions(screen.getByLabelText("Filter by result"), "fail");
    expect(dataRows()).toHaveLength(2);
    await user.selectOptions(screen.getByLabelText("Filter by risk"), "LLM05");
    expect(dataRows()).toHaveLength(1);
    expect(within(dataRows()[0]).getByText("Script tag")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Filter by risk"), "all");
    await user.selectOptions(screen.getByLabelText("Filter by result"), "all");
    await user.selectOptions(screen.getByLabelText("Filter by severity"), "critical");
    expect(dataRows()).toHaveLength(3); // the leak, the passed critical test and the errored one
  });

  it("can sort the most serious first", async () => {
    const { user } = await openTests();
    await user.click(screen.getByRole("button", { name: "Sort by severity" }));
    expect(within(dataRows()[0]).getByText("critical")).toBeInTheDocument();
    const last = dataRows()[dataRows().length - 1];
    expect(within(last).getByText("normal request")).toBeInTheDocument();
  });

  it("shows a result from before severity existed as not rated", async () => {
    await openTests(makeScan([makeResult({ title: "Old test", status: "fail", severity: undefined })]));
    expect(within(dataRows()[0]).getByText("not rated")).toBeInTheDocument();
  });
});

describe("Conversations tab", () => {
  it("opens a test to show the message, reply, tool log, evidence, rule, fix note and model", async () => {
    const { user } = renderDashboard();
    await user.click(screen.getByRole("tab", { name: "Conversations" }));
    const item = screen.getByRole("listitem", { name: "Test result: Read another customer's order" });
    expect(within(item).queryByText(/It ships to/)).not.toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: /show evidence/i }));
    expect(within(item).getByText("the attack message")).toBeInTheDocument();
    expect(within(item).getByText(/It ships to 221 Fakewood Lane\./)).toBeInTheDocument();
    const log = within(within(item).getByRole("list", { name: "Tool calls" }));
    expect(log.getByText(/"order_id":"B-2001"/)).toBeInTheDocument();
    expect(within(item).getByText(/another customer's ship_to/)).toBeInTheDocument();
    expect(within(item).getByText(/A customer may see only their own orders\./)).toBeInTheDocument();
    expect(
      within(item).getByText(/Check in code that an order belongs to the customer\./),
    ).toBeInTheDocument();
    expect(within(item).getByText(/gemini-3.5-flash-lite/)).toBeInTheDocument();
  });

  it("says when no model answered a test", async () => {
    const { user } = renderDashboard();
    await user.click(screen.getByRole("tab", { name: "Conversations" }));
    const item = screen.getByRole("listitem", { name: "Test result: Refund test" });
    await user.click(within(item).getByRole("button", { name: /show evidence/i }));
    expect(within(item).getByText("No model answered this test.")).toBeInTheDocument();
  });
});

describe("Compare tab", () => {
  const weak = makeScan(
    [
      makeResult({ test_id: "a", title: "Test A", status: "fail" }),
      makeResult({ test_id: "b", title: "Test B", status: "fail" }),
      makeResult({ test_id: "only-weak", title: "Only in the weak scan", status: "pass" }),
    ],
    { id: 7, botId: "acme-weak", models: ["gemini-3.5-flash-lite"] },
  );
  const hardenedResults = [
    makeResult({ test_id: "a", title: "Test A", status: "pass" }),
    makeResult({ test_id: "b", title: "Test B", status: "fail" }),
    makeResult({ test_id: "only-hardened", title: "Only in the hardened scan", status: "pass" }),
  ];

  async function compareWith(other: ScanDetail) {
    const view = renderDashboard(weak, { loadScan: vi.fn(async () => other) });
    await view.user.click(screen.getByRole("tab", { name: "Compare" }));
    await view.user.selectOptions(screen.getByLabelText("Compare with"), "8");
    return view;
  }

  it("loads the other scan and says the same model answered both", async () => {
    const view = await compareWith(makeScan(hardenedResults, { id: 8, botId: "acme-hardened" }));
    expect(view.props.loadScan).toHaveBeenCalledWith(8);
    expect(await screen.findByText(/The same model answered both scans/)).toBeInTheDocument();
  });

  it("warns that the difference may not come from the defenses when the models differ", async () => {
    await compareWith(
      makeScan(hardenedResults, { id: 8, botId: "acme-hardened", models: ["openai/gpt-oss-20b"] }),
    );
    expect(await screen.findByText(/Different models answered the two scans/)).toBeInTheDocument();
    expect(screen.getByText(/may not come from the defenses/)).toBeInTheDocument();
  });

  it("lists the tests that changed and the ones in only one scan", async () => {
    await compareWith(makeScan(hardenedResults, { id: 8, botId: "acme-hardened" }));
    const changed = await screen.findByRole("list", { name: "Tests that changed" });
    expect(within(changed).getByText(/Test A: FAIL to PASS/)).toBeInTheDocument();
    expect(screen.getByText(/Only in the weak scan/)).toBeInTheDocument();
    expect(screen.getByText(/Only in the hardened scan/)).toBeInTheDocument();
  });

  it("notes when the two scans ran different versions of the test library", async () => {
    await compareWith(
      makeScan(hardenedResults, { id: 8, botId: "acme-hardened", suiteVersion: 1 }),
    );
    expect(await screen.findByText(/different versions of the test library/i)).toBeInTheDocument();
  });

  it("only offers the other scans, not the one on screen", async () => {
    const { user } = renderDashboard(weak);
    await user.click(screen.getByRole("tab", { name: "Compare" }));
    const options = within(screen.getByLabelText("Compare with"))
      .getAllByRole("option")
      .map((o) => o.textContent)
      .join(" ");
    expect(options).toContain("Scan #8");
    expect(options).not.toContain("Scan #7");
  });
});

describe("History tab", () => {
  it("lists scans and opens one", async () => {
    const { user, props } = renderDashboard();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const list = screen.getByRole("list", { name: "Scan history" });
    expect(within(list).getByText(/Scan #7/)).toBeInTheDocument();
    expect(within(list).getByText(/2 failed/)).toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "Open scan #8" }));
    expect(props.onOpen).toHaveBeenCalledWith(8);
  });
});

describe("Download report", () => {
  it("downloads the Markdown report as a file", async () => {
    const parts: string[][] = [];
    vi.stubGlobal(
      "Blob",
      class {
        constructor(content: string[]) {
          parts.push(content);
        }
      },
    );
    URL.createObjectURL = vi.fn(() => "blob:report");
    URL.revokeObjectURL = vi.fn();
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });
    const { user } = renderDashboard();
    await user.click(screen.getByRole("button", { name: "Download report" }));
    expect(downloads).toEqual(["redflag-scan-7.md"]);
    expect(parts[0][0]).toContain("# Redflag scan report");
    expect(parts[0][0]).toContain("Scan #7");
  });
});

describe("it never touches the network by itself", () => {
  it("visiting every tab makes no request", async () => {
    const fetchMock = vi.fn(() => {
      throw new Error("the dashboard must not call the network");
    });
    vi.stubGlobal("fetch", fetchMock);
    const { user } = renderDashboard();
    for (const name of ["Tests", "Conversations", "Compare", "History", "Overview"]) {
      await user.click(screen.getByRole("tab", { name }));
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
