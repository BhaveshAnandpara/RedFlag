"""The plan endpoints of Test your bot: a background job, open to anyone, limited, keeps nothing.

The only faked part is the model. The bot is never called, and nothing is saved.
"""

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import OWNER
from tests.test_setup_runs import run_client
from tests.test_supervisor import GOALS, PRIVATE, REFUND, Writers

FACTS = {
    "does": "Helps customers with refunds.",
    "can_read": ["order history"],
    "can_do": ["issue refunds", "look up orders"],
    "risky": ["issue refunds"],
    "unknown": [],
}


def plan_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "environment": "staging",
        "purpose": "A support bot for ShopCo.",
        "rules": [REFUND, PRIVATE],
        "facts": FACTS,
    }
    body.update(changes)
    return body


def finished(client: TestClient, plan_id: str) -> dict[str, Any]:
    for _ in range(100):
        job: dict[str, Any] = client.get(f"/quick-scans/plan/{plan_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("the plan never finished")


def start(client: TestClient, **changes: Any) -> Any:
    return client.post("/quick-scans/plan", json=plan_body(**changes))


def test_a_plan_is_made_in_the_background_and_read_back_in_plain_fields() -> None:
    with run_client(roles=Writers(GOALS)) as (client, _, endpoint):
        started = start(client)
        assert started.status_code == 202
        job = finished(client, started.json()["plan_id"])
        assert job["status"] == "done"
        plan = job["plan"]
        first = plan["goals"][0]
        assert first["question"] == "Can someone get a refund over $50?"
        assert first["tag"] == f"Because you said: “{REFUND}”"
        assert first["test_count"] >= 30 and first["tests"][0]["persona"]
        assert plan["summary"]["tests"] > 0 and plan["blocked"] is None
        assert REFUND in plan["rules_covered"] and PRIVATE in plan["rules_covered"]
        assert plan["goals"][-1]["background"] is True
        assert endpoint.requests == []  # planning never calls the bot
        assert client.get("/setups", headers=OWNER).json()["setups"] == []


def test_the_bots_own_description_becomes_its_tools_for_the_planner() -> None:
    model = Writers(GOALS)
    with run_client(roles=model) as (client, _, _):
        finished(client, start(client).json()["plan_id"])
        prompt = model.prompts("planner")[0]
        assert '"name": "issue refunds"' in prompt and '"effect": "acts"' in prompt
        assert "look up orders" not in prompt.split("<<<BOT DESCRIBES ITSELF")[0]
        assert "<<<BOT DESCRIBES ITSELF" in prompt


def test_a_bot_that_only_answers_questions_has_no_tools_to_misuse() -> None:
    chat_only = {**FACTS, "can_do": ["explain fees", "share opening hours"], "risky": []}
    model = Writers(GOALS)
    with run_client(roles=model) as (client, _, _):
        job = finished(client, start(client, facts=chat_only).json()["plan_id"])
        assert '"tools": []' in model.prompts("planner")[0]
        questions = [g["question"] for g in job["plan"]["goals"]]
        assert "Can someone get a refund over $50?" not in questions


def test_a_plan_with_nothing_to_go_on_is_refused() -> None:
    with run_client(roles=Writers(GOALS)) as (client, _, _):
        refused = start(client, purpose="", rules=[], facts=None)
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "nothing_to_plan"


def test_in_production_the_poisoning_tests_come_back_as_needing_a_test_copy() -> None:
    with run_client(roles=Writers(GOALS)) as (client, _, _):
        job = finished(client, start(client, environment="production").json()["plan_id"])
        plan = job["plan"]
        assert plan["skipped"] and {s["reason"] for s in plan["skipped"]} == {"needs a test copy"}
        assert all(t["persona"] != "content poisoner" for g in plan["goals"] for t in g["tests"])


def test_a_rule_with_no_tests_comes_back_blocked_with_a_plain_message() -> None:
    model = Writers(GOALS, bad_risk=("social_engineer", "content_poisoner"))
    with run_client(roles=model) as (client, _, _):
        job = finished(client, start(client).json()["plan_id"])
        assert job["status"] == "done" and REFUND in job["plan"]["blocked"]


def test_planning_has_a_limit_so_it_cannot_be_used_to_burn_the_models() -> None:
    with run_client(roles=Writers(GOALS), quick_plans_per_window=2) as (client, _, _):
        for _ in range(2):
            finished(client, start(client).json()["plan_id"])
        blocked = start(client)
        assert blocked.status_code == 429 and blocked.json()["error"]["kind"] == "too_many_plans"


def test_a_plan_that_takes_too_long_ends_as_an_error_the_page_can_show() -> None:
    with run_client(roles=Writers(GOALS), quick_plan_timeout_seconds=0.0001) as (client, _, _):
        job = finished(client, start(client).json()["plan_id"])
        assert job == {"status": "error", "kind": "plan_timeout"}


def test_a_plan_that_does_not_exist_is_a_plain_404() -> None:
    with run_client(roles=Writers(GOALS)) as (client, _, _):
        missing = client.get("/quick-scans/plan/nope")
        assert missing.status_code == 404 and missing.json()["error"]["kind"] == "no_such_plan"
