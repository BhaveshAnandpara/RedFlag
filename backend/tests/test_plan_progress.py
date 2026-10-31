"""Waiting out the models' quota, and telling the user what a plan is doing meanwhile.

No network. The stand-in model raises the quota error a set number of times, with a cool-off of a
millisecond, and the waits are a few hundredths of a second so the tests stay quick.
"""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from redflag_backend.llm.budget import BudgetBook, BudgetCaps
from redflag_backend.llm.router import Router
from redflag_backend.llm.types import LLMAnswer, RateLimited, ServerError
from redflag_backend.personas.writer import Brief, Tool
from redflag_backend.setups.llm import ModelFailure, Patience, SetupLLM
from redflag_backend.supervisor.plan import build_plan
from redflag_backend.supervisor.progress import Progress
from tests.test_quick_plan import finished, start
from tests.test_setup_chat import RoleModel
from tests.test_setup_runs import run_client
from tests.test_supervisor import GOALS, PRIVATE, REFUND, Writers, llm_for

WAIT = 0.02


class Said(BaseModel):
    reply: str


class Quota(RoleModel):
    """Fails `hits` times (by default with the per-minute quota error), then answers."""

    def __init__(self, hits: int, fail: Exception | None = None) -> None:
        super().__init__()
        self.hits, self.fail, self.count = hits, fail, 0

    async def complete(self, request: Any) -> LLMAnswer:
        self.count += 1
        if self.count <= self.hits:
            raise self.fail or RateLimited(retry_after=0.001)
        return LLMAnswer(json.dumps({"reply": "ok"}), "quota", 1, 1)


class Recording(Progress):
    """A progress that also keeps every line said, not only the latest few."""

    def __init__(self, clock: Callable[[], float], wait_seconds: float, max_waits: int) -> None:
        super().__init__(clock, wait_seconds, max_waits)
        self.lines: list[str] = []

    def say(self, text: str) -> None:
        self.lines.append(text)
        super().say(text)


def ask(model: RoleModel, patience: Patience | None) -> Said:
    caps = BudgetCaps(requests=100, tokens=10**6, seconds=600, concurrency=1)
    llm = SetupLLM(Router([model]), BudgetBook(caps, time.time))
    return asyncio.run(llm.ask(1, "planner", "ROLE: planner\nx", "y", Said, patience))


# --- the wait itself --------------------------------------------------------------------------


def test_without_patience_a_used_up_quota_fails_straight_away() -> None:
    model = Quota(hits=1)
    with pytest.raises(ModelFailure) as caught:
        ask(model, None)
    assert caught.value.kind == "model_unavailable" and model.count == 1


def test_with_patience_it_waits_and_asks_again_until_the_answer_comes() -> None:
    model = Quota(hits=2)
    seen: list[tuple[float, int, int]] = []
    resumed: list[int] = []
    patience = Patience(
        WAIT, 5, lambda s, n, of: seen.append((s, n, of)), lambda: resumed.append(1)
    )
    started = time.monotonic()
    assert ask(model, patience).reply == "ok"
    assert time.monotonic() - started >= 2 * WAIT
    assert model.count == 3 and seen == [(WAIT, 1, 5), (WAIT, 2, 5)] and len(resumed) == 2


def test_it_gives_up_after_the_most_waits_it_was_allowed() -> None:
    model = Quota(hits=99)
    with pytest.raises(ModelFailure) as caught:
        ask(model, Patience(WAIT, 3))
    assert caught.value.kind == "model_unavailable" and model.count == 4  # first try + 3 waits


def test_a_failure_that_is_not_the_quota_is_not_waited_for() -> None:
    model = Quota(hits=1, fail=ServerError())
    with pytest.raises(ModelFailure):
        ask(model, Patience(WAIT, 5))
    assert model.count == 1


# --- what the page is told --------------------------------------------------------------------


def test_the_countdown_runs_while_waiting_and_clears_when_the_wait_is_over() -> None:
    now = [100.0]
    progress = Progress(lambda: now[0], 60, 5)
    patience = progress.patience
    assert patience.on_wait is not None and patience.on_resume is not None
    assert progress.snapshot()["waiting"] is False
    patience.on_wait(60, 1, 5)
    snap = progress.snapshot()
    assert snap["waiting"] is True and snap["seconds_left"] == 60
    assert "quota" in snap["feed"][-1] and "Waiting a minute" in snap["feed"][-1]
    now[0] = 130.0
    assert progress.snapshot()["seconds_left"] == 30
    now[0] = 160.0
    patience.on_resume()
    snap = progress.snapshot()
    assert snap["waiting"] is False and snap["feed"][-1] == "Trying again…"


def test_several_personas_hitting_the_quota_together_make_one_wait_and_one_line() -> None:
    progress = Progress(lambda: 0.0, 60, 5)
    on_wait = progress.patience.on_wait
    assert on_wait is not None
    for _ in range(3):
        on_wait(60, 1, 5)
    assert len([line for line in progress.snapshot()["feed"] if "quota" in line]) == 1


def test_the_feed_keeps_only_the_latest_lines_and_names_who_is_being_asked() -> None:
    progress = Progress(lambda: 0.0, 60, 5)
    for n in range(20):
        progress.say(f"line {n}")
    feed = progress.snapshot()["feed"]
    assert feed[-1] == "line 19" and len(feed) == 8
    progress.asking(["content_poisoner"])
    assert progress.snapshot()["feed"][-1] == (
        "Asking the content poisoner to hide instructions inside data…"
    )
    progress.asking(["social_engineer", "fake_insider", "data_harvester"], retry_round=2)
    last = progress.snapshot()["feed"][-1]
    assert "the fake insider to pose as staff and the data harvester" in last
    assert last.endswith("for different angles (try 2 of 3)…")


# --- a whole plan -----------------------------------------------------------------------------

BRIEF = Brief(
    purpose="A support bot.",
    rules=[REFUND, PRIVATE],
    tools=[Tool(name="refund", effect="acts")],
)


def test_a_plan_rides_out_the_quota_and_still_gets_every_persona_through() -> None:
    model = Writers(
        GOALS, quota={"planner": 1, "persona-social_engineer": 2, "persona-data_harvester": 1}
    )
    progress = Recording(time.time, WAIT, 5)
    plan = asyncio.run(build_plan(llm_for(model), BRIEF, -1, progress))
    assert plan.blocked is None and plan.summary.tests > 0
    assert all(c.failed is None for c in plan.counts)
    assert any("quota" in line for line in progress.lines)
    assert progress.goal_total == len(plan.goals) and progress.goal_index == len(plan.goals)


def test_the_progress_names_the_goal_and_the_personas_as_the_plan_goes() -> None:
    progress = Recording(time.time, WAIT, 5)
    asyncio.run(build_plan(llm_for(Writers(GOALS)), BRIEF, -1, progress))
    joined = "\n".join(progress.lines)
    assert "Asking the planner" in joined and "Found " in joined
    assert "Asking the social engineer" in joined and "wrote" in joined
    assert "the content poisoner to hide instructions inside data" in joined
    assert "Asking a normal user" in joined


def test_a_plan_that_never_gets_through_blames_the_models_not_the_rule() -> None:
    model = Writers(GOALS, broken=("social_engineer", "content_poisoner"))
    plan = asyncio.run(build_plan(llm_for(model), BRIEF, -1, Progress(time.time, WAIT, 1)))
    assert plan.blocked is not None and REFUND in plan.blocked
    assert "because the AI models did not answer" in plan.blocked
    assert "Reword" not in plan.blocked


# --- over HTTP --------------------------------------------------------------------------------


def test_while_a_plan_waits_for_the_quota_the_page_can_see_the_countdown() -> None:
    model = Writers(GOALS, quota={"persona-social_engineer": 1})
    with run_client(roles=model, quick_plan_quota_wait_seconds=1.0) as (client, _, _):
        plan_id = start(client).json()["plan_id"]
        waiting: dict[str, Any] | None = None
        for _ in range(300):
            job: dict[str, Any] = client.get(f"/quick-scans/plan/{plan_id}").json()
            if job["status"] != "running":
                break
            if job["waiting"]:
                waiting = job
                break
            time.sleep(0.02)
        assert waiting is not None, "never saw the wait"
        assert waiting["seconds_left"] >= 0 and waiting["headline"]
        assert any("quota" in line for line in waiting["feed"])
        assert finished(client, plan_id)["status"] == "done"


def test_a_running_plan_reports_a_headline_and_a_feed_and_never_the_internals() -> None:
    with run_client(roles=Writers(GOALS)) as (client, _, _):
        plan_id = start(client).json()["plan_id"]
        job = client.get(f"/quick-scans/plan/{plan_id}").json()
        if job["status"] == "running":
            assert set(job) == {
                "status",
                "headline",
                "feed",
                "goal_index",
                "goal_total",
                "waiting",
                "seconds_left",
            }
        assert finished(client, plan_id)["status"] == "done"
