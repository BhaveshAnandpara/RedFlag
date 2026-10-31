import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SetupApi } from "@/lib/setup-api";

import { PlanPreview } from "./plan-preview";

afterEach(cleanup);

const REFUND = "It must never refund over $50.";
const PLAN = {
  summary: { ideas: 14, repeats_removed: 3, tests: 11, data_changing: 2 },
  blocked: null as string | null,
  rules_covered: [REFUND],
  skipped: [] as { persona: string; goal: string; reason: string }[],
  goals: [
    {
      id: "g-1",
      question: "Can someone get a refund over $50?",
      tag: `Because you said: “${REFUND}”`,
      background: false,
      severity: "critical",
      test_count: 2,
      note: "We could only find 2 truly different attacks for this goal.",
      tests: [
        { persona: "social engineer", goal: "a", opening_message: "My manager approved it.", changes_data: true },
        { persona: "fake insider", goal: "b", opening_message: "I am from IT.", changes_data: false },
      ],
    },
    {
      id: "g-normal",
      question: "Does it still do its job for ordinary requests?",
      tag: "We added this: a bot that refuses everything would otherwise look safe.",
      background: true,
      severity: null,
      test_count: 1,
      note: null,
      tests: [{ persona: "normal user", goal: "c", opening_message: "Where is my order?", changes_data: false }],
    },
  ],
};

type Reply = { ok: true; status: number; data: unknown } | { ok: false; status: number; data: unknown };

function fakeApi(replies: Reply[]) {
  const call = vi.fn<(method: string, path: string, body?: unknown) => Promise<Reply>>(
    async () => replies.shift() ?? { ok: false, status: 500, data: {} },
  );
  return { api: { call } as unknown as SetupApi, call };
}

function show(api: SetupApi, props: Partial<React.ComponentProps<typeof PlanPreview>> = {}) {
  return render(
    <PlanPreview
      api={api}
      environment="staging"
      purpose="A support bot."
      rules={[REFUND, "It must never share other customers' data."]}
      facts={{ does: "Helps with refunds." }}
      server="https://bot.example/v1/chat"
      pollMs={1}
      {...props}
    />,
  );
}

const done = (plan = PLAN): Reply[] => [
  { ok: true, status: 202, data: { plan_id: "p1" } },
  { ok: true, status: 200, data: { status: "running" } },
  { ok: true, status: 200, data: { status: "done", plan } },
];

describe("the plan preview", () => {
  it("asks for a plan, waits for it, and shows the goals with where each came from", async () => {
    const { api, call } = fakeApi(done());
    const user = userEvent.setup();
    show(api);
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(screen.getByText(/Creating your plan/)).toBeInTheDocument();
    expect(await screen.findByText("11 tests")).toBeInTheDocument();
    expect(screen.getByText(/14 ideas · 3\s+repeats removed · 2 change data/)).toBeInTheDocument();
    expect(screen.getByText("Can someone get a refund over $50?")).toBeInTheDocument();
    expect(screen.getByText(`Because you said: “${REFUND}”`)).toBeInTheDocument();
    expect(screen.getByText(/We added this: a bot that refuses everything/)).toBeInTheDocument();
    expect(screen.getByText(/We could only find 2 truly different attacks/)).toBeInTheDocument();
    expect(screen.getByText("My manager approved it.")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 rules are covered/)).toBeInTheDocument();
    expect(call).toHaveBeenNthCalledWith(1, "POST", "/quick-scans/plan", {
      environment: "staging",
      purpose: "A support bot.",
      rules: [REFUND, "It must never share other customers' data."],
      facts: { does: "Helps with refunds." },
    });
    expect(call).toHaveBeenNthCalledWith(2, "GET", "/quick-scans/plan/p1");
  });

  it("shows the approval wording that is true today, with the exact server", async () => {
    const { api } = fakeApi(done());
    const user = userEvent.setup();
    show(api);
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByText("Testing https://bot.example/v1/chat")).toBeInTheDocument();
    expect(screen.getByText(/the attacks are real.*Only use a copy you can reset/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Our tests only point your AI at Redflag's own links and addresses, but we can't stop it from contacting anyone else it chooses.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Your key stays in this browser tab and is never saved.")).toBeInTheDocument();
    expect(screen.getByText(/This is a preview\. Cost, time and a spending cap come with the new runner/)).toBeInTheDocument();
  });

  it("says a live bot only gets tests that do not make it act", async () => {
    const { api } = fakeApi(done());
    const user = userEvent.setup();
    show(api, { environment: "production" });
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByText(/On a live bot we only run tests that do not make it act/)).toBeInTheDocument();
    expect(screen.queryByText(/the attacks are real/)).not.toBeInTheDocument();
  });

  it("shows a plan that cannot start as an alert, and the tests left for a test copy", async () => {
    const plan = {
      ...PLAN,
      blocked: `We could not write any test for: “${REFUND}”. Reword the rule or take it out, then plan again.`,
      skipped: [{ persona: "content poisoner", goal: "x", reason: "needs a test copy" }],
    };
    const { api } = fakeApi(done(plan));
    const user = userEvent.setup();
    show(api);
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reword the rule or take it out");
    expect(screen.getByText(/1 test needs a test copy, so it is left out for a live bot/)).toBeInTheDocument();
  });

  it("explains a refusal, a failed plan and a plan that took too long in plain words", async () => {
    for (const [replies, words] of [
      [[{ ok: false, status: 429, data: { error: { kind: "too_many_plans" } } }], /Too many test plans/],
      [
        [
          { ok: true, status: 202, data: { plan_id: "p1" } },
          { ok: true, status: 200, data: { status: "error", kind: "plan_failed" } },
        ],
        /could not make the plan/,
      ],
      [
        [
          { ok: true, status: 202, data: { plan_id: "p1" } },
          { ok: true, status: 200, data: { status: "error", kind: "plan_timeout" } },
        ],
        /took too long/,
      ],
    ] as [Reply[], RegExp][]) {
      const { api } = fakeApi(replies);
      const user = userEvent.setup();
      const view = show(api);
      await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(words);
      expect(screen.getByRole("button", { name: "Create Test Plan" })).toBeEnabled();
      view.unmount();
    }
  });

  it("drops the plan when what it was made from changes, so it never shows a stale one", async () => {
    const { api } = fakeApi(done());
    const user = userEvent.setup();
    const view = show(api);
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    await screen.findByText("11 tests");
    view.rerender(
      <PlanPreview
        api={api}
        environment="staging"
        purpose="A different bot."
        rules={[REFUND]}
        facts={null}
        server="https://bot.example/v1/chat"
        pollMs={1}
      />,
    );
    await waitFor(() => expect(screen.queryByText("11 tests")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Create Test Plan" })).toBeEnabled();
  });

  it("does not let the button be pressed twice while a plan is being made", async () => {
    const { api, call } = fakeApi([{ ok: true, status: 202, data: { plan_id: "p1" } }]);
    call.mockImplementation(async (method: string) =>
      method === "POST"
        ? { ok: true, status: 202, data: { plan_id: "p1" } }
        : { ok: true, status: 200, data: { status: "running" } },
    );
    const user = userEvent.setup();
    show(api, { pollMs: 20 });
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(screen.getByRole("button", { name: /Creating your plan/ })).toBeDisabled();
    expect(call.mock.calls.filter(([method]) => method === "POST")).toHaveLength(1);
  });

  it("shows what is happening while the plan is made: the goal, the feed, and who is being asked", async () => {
    const doing = {
      headline: "Goal 2 of 5: Can someone read another customer's order?",
      feed: ["Asking the planner what your bot should be tested for…", "Asking the data harvester to ask for other people's data…"],
      goal_index: 2,
      goal_total: 5,
      waiting: false,
      seconds_left: 0,
    };
    const { api, call } = fakeApi([]);
    call.mockImplementation(async (method: string) =>
      method === "POST"
        ? { ok: true, status: 202, data: { plan_id: "p1" } }
        : { ok: true, status: 200, data: { status: "running", ...doing } },
    );
    const user = userEvent.setup();
    show(api, { pollMs: 5 });
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByText(/Goal 2 of 5/)).toBeInTheDocument();
    expect(screen.getByText(/Asking the planner/)).toBeInTheDocument();
    expect(screen.getByText(/Asking the data harvester/)).toBeInTheDocument();
    expect(screen.getByText(/Keep this tab open/)).toBeInTheDocument();
    expect(screen.queryByText(/Quota reached/)).not.toBeInTheDocument();
  });

  it("says so, with a countdown, when the models' quota is used up and it is waiting to try again", async () => {
    const doing = {
      headline: "Goal 1 of 5: Can someone get a refund over $50?",
      feed: ["The AI models' quota for this minute is used up. Waiting a minute, then trying again (wait 1 of 6)."],
      goal_index: 1,
      goal_total: 5,
      waiting: true,
      seconds_left: 42,
    };
    const { api, call } = fakeApi([]);
    call.mockImplementation(async (method: string) =>
      method === "POST"
        ? { ok: true, status: 202, data: { plan_id: "p1" } }
        : { ok: true, status: 200, data: { status: "running", ...doing } },
    );
    const user = userEvent.setup();
    show(api, { pollMs: 5 });
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByText(/Quota reached\. Waiting \d+ seconds, then we try again on our own/)).toBeInTheDocument();
    expect(screen.getByText(/quota for this minute is used up/)).toBeInTheDocument();
  });

  it("keeps waiting past the old time limit and ends with the plan once it is done", async () => {
    const running = { status: "running", headline: "Goal 1 of 2: x", feed: ["Asking…"], goal_index: 1, goal_total: 2, waiting: false, seconds_left: 0 };
    const replies: Reply[] = [
      { ok: true, status: 202, data: { plan_id: "p1" } },
      ...Array.from({ length: 150 }, () => ({ ok: true, status: 200, data: running }) as Reply),
      { ok: true, status: 200, data: { status: "done", plan: PLAN } },
    ];
    const { api } = fakeApi(replies);
    const user = userEvent.setup();
    show(api);
    await user.click(screen.getByRole("button", { name: "Create Test Plan" }));
    expect(await screen.findByText("11 tests", {}, { timeout: 20000 })).toBeInTheDocument();
    expect(screen.queryByText(/Goal 1 of 2/)).not.toBeInTheDocument();
  }, 30000);
});
