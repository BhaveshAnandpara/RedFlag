"""Everyday twins (ticket 18): for each rule of the user's that has attacks, ordinary requests next
to it that the bot must still help with, so over-refusal is measured on more than a handful.
"""

import asyncio

from redflag_backend.personas.writer import Brief
from redflag_backend.supervisor.plan import Plan, build_plan
from redflag_backend.supervisor.run_tests import build_tests, save_specs
from tests.test_supervisor import BRIEF, GOALS, PRIVATE, REFUND, Writers, llm_for, plan_for


def normal(plan: Plan) -> list:  # type: ignore[type-arg]
    return [(p, s) for p in plan.goals for s in p.specs if s.kind == "normal"]


def twins_of(plan: Plan) -> list:  # type: ignore[type-arg]
    return [(p, s) for p, s in normal(plan) if not p.goal.background]


def test_each_rule_with_attacks_gets_everyday_requests_that_sit_next_to_it() -> None:
    plan = plan_for(Writers(GOALS))
    twins = twins_of(plan)
    assert twins and plan.summary.twins == len(twins)
    for goal, spec in twins:
        assert goal.goal.source == "user" and spec.rule == goal.goal.rule
        assert spec.kind == "normal" and spec.risk is None and spec.severity is None
    assert {goal.goal.rule for goal, _ in twins} == {REFUND, PRIVATE}


def test_it_takes_one_model_call_for_all_the_rules() -> None:
    model = Writers(GOALS)
    plan_for(model)
    asked = [
        c
        for c in model.calls["persona-normal_user"]
        if "close to the rule" in c.messages[0].content
    ]
    assert len(asked) == 1
    text = asked[0].messages[0].content
    assert REFUND in text and PRIVATE in text


def test_a_rule_with_no_attacks_gets_no_twin_so_it_never_looks_covered_by_one() -> None:
    from redflag_backend.supervisor.plan import PlannedGoal

    model = Writers(GOALS, broken=("social_engineer", "fake_insider", "data_harvester"))
    plan = plan_for(model)
    for item in plan.goals:
        if item.goal.source == "user" and not any(s.kind == "attack" for s in item.specs):
            assert not any(s.kind == "normal" for s in item.specs)
    assert isinstance(plan.goals[0], PlannedGoal)


def test_a_normal_user_that_cannot_answer_leaves_the_plan_without_twins_and_still_whole() -> None:
    plan = plan_for(Writers(GOALS, broken=("normal_user",)))
    assert plan.summary.twins == 0 and twins_of(plan) == []
    assert any(s.kind == "attack" for p in plan.goals for s in p.specs)


def test_no_user_rules_means_no_call_for_twins() -> None:
    model = Writers(GOALS)
    brief = Brief(purpose="A support bot for ShopCo.", rules=[])
    plan = asyncio.run(build_plan(llm_for(model), brief))
    assert plan.summary.twins == 0
    assert not any(
        "close to the rule" in c.messages[0].content
        for c in model.calls.get("persona-normal_user", [])
    )


def test_a_twin_runs_once_as_one_normal_request() -> None:
    from sqlalchemy import create_engine

    from redflag_backend.specs.store import SpecStore
    from tests.helpers import TEST_DB_URL

    plan = plan_for(Writers(GOALS))
    stored = save_specs(SpecStore(create_engine(TEST_DB_URL)), plan)
    tests = build_tests(plan, 5, stored)
    twin_texts = {s.opening_message for _, s in twins_of(plan)}
    mine = [t for t in tests if t["prompt"] in twin_texts]
    assert mine and all(t["kind"] == "positive" and t["runs"] == 1 for t in mine)
    assert all(t["max_turns"] == 1 and t["risk"] is None for t in mine)


def test_the_brief_is_the_one_the_rest_of_the_tests_use() -> None:
    assert REFUND in BRIEF.rules and PRIVATE in BRIEF.rules
