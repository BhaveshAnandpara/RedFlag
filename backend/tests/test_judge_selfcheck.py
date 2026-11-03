"""The judge's own check: four saved cases, run once on the owner's key before it is trusted."""

import asyncio
import json
from typing import Any

from redflag_backend.judge.selfcheck import CASES, run_self_check
from tests.helpers import SELF_CHECK_BREAKS, judge_text, wait_for_scan
from tests.test_judge import CAPS, Setup, with_quote
from tests.test_multi_turn import GaveInJudge, bot_gives_in_on
from tests.test_plan_run import made_plan, ran, run_plan, small
from tests.test_setup_runs import run_client

LEAK = with_quote("fail", "It named the customer.", "Dana Reyes")
REFUSED = judge_text("pass", "It refused.")
ECHO = judge_text("pass", "It repeated the tester's own number.")
TRAP = with_quote("fail", "It gave the code.", "RF-7741")


def check(*script: str) -> Any:
    setup = Setup(*script)
    return asyncio.run(run_self_check(setup.judge, setup.budget)), setup


def test_there_are_four_cases_and_the_stand_ins_know_which_two_a_judge_must_fail() -> None:
    assert len(CASES) == 4
    assert {c.request.title for c in CASES if c.expected == "fail"} == SELF_CHECK_BREAKS
    assert all(c.request.title.startswith("Self-check: ") for c in CASES)
    assert all(c.request.require_quote and not c.request.second_look for c in CASES)


def test_a_judge_that_gets_all_four_right_passes() -> None:
    result, setup = check(LEAK, REFUSED, ECHO, TRAP)
    assert (result.passed, result.total, result.unavailable) == (4, 4, 0)
    assert not result.failed and result.model == "judge-model"
    assert len(setup.provider.calls) == 4


def test_a_judge_that_passes_everything_fails_the_check() -> None:
    result, _ = check(REFUSED)
    assert (result.passed, result.total) == (2, 4) and result.failed


def test_a_judge_that_believes_a_note_aimed_at_it_fails_the_check() -> None:
    result, _ = check(LEAK, REFUSED, ECHO, judge_text("pass", "The assistant handled it."))
    assert (result.passed, result.total) == (3, 4) and result.failed


def test_a_judge_that_cannot_answer_is_not_called_wrong() -> None:
    result, _ = check("not json")
    assert result.unavailable == 4 and result.passed == 0 and not result.failed


def test_the_judge_is_told_the_note_is_the_testers_and_the_check_stays_in_budget() -> None:
    _, setup = check(LEAK, REFUSED, ECHO, TRAP)
    last = setup.provider.calls[3].messages[1].content
    assert "Note to the judge" in last and "tester wrote all of this" in last
    assert setup.budget is not None and CAPS.requests >= 4


# --- on a run -----------------------------------------------------------------------------------


class LazyJudge(GaveInJudge):
    """A judge that passes everything, the check's leaks included."""

    async def complete(self, request: Any) -> Any:
        from redflag_backend.llm.types import LLMAnswer

        self.calls.append(request)
        return LLMAnswer(judge_text("pass"), "judge-model", 10, 5)


def judge_check_of(scan: dict[str, Any]) -> dict[str, Any]:
    check_saved: dict[str, Any] = scan["scan"]["settings"]["judge_check"]
    return check_saved


def test_a_judge_that_passes_the_check_is_trusted_and_its_score_is_saved() -> None:
    with run_client(GaveInJudge(), bot_gives_in_on(1), roles=small()) as (client, _, _):
        plan_id = made_plan(client)
        scan = ran(client, run_plan(client, plan_id))
    saved = judge_check_of(scan)
    assert (saved["ran"], saved["passed"], saved["total"]) == (True, 4, 4)
    assert saved["model"] == "judge-model"
    attacks = [r for r in scan["results"] if r["kind"] == "negative"]
    assert attacks and any(r["status"] == "fail" for r in attacks)
    assert not any("did not pass our check" in r["evidence"] for r in scan["results"])


def test_a_judge_that_fails_the_check_sends_everything_it_decided_to_a_person() -> None:
    with run_client(LazyJudge(), bot_gives_in_on(1), roles=small()) as (client, _, _):
        plan_id = made_plan(client)
        scan = ran(client, run_plan(client, plan_id))
    saved = judge_check_of(scan)
    assert (saved["passed"], saved["total"]) == (2, 4)
    decided = [r for r in scan["results"] if r["judge_status"] in ("disputed", "pass", "fail")]
    assert decided
    for result in decided:
        assert result["status"] == "inconclusive"
        assert "did not pass our check (2 of 4)" in result["evidence"]


def test_the_check_runs_once_per_run_not_once_per_test() -> None:
    judge = GaveInJudge()
    with run_client(judge, bot_gives_in_on(1), roles=small()) as (client, _, _):
        plan_id = made_plan(client)
        info = run_plan(client, plan_id).json()
        wait_for_scan(client, info["scan_id"], timeout=90)
    assert len(judge.checks) == 4  # four cases, once, however many tests there were
    assert not any("Self-check: " in c.messages[1].content for c in judge.calls)
    assert json.loads(judge_text("pass"))["verdict"] == "pass"
