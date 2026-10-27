"""The quick scan (W6): a built-in starter pack, a hello check, and one call that sets a bot up and
runs the pack with no select step.

The pack is fixed text, so writing the tests costs no model quota and gives the same tests every
time. The only faked parts are the outside models and the user's endpoint.
"""

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from redflag_backend.quick.pack import (
    AGENT_RULES,
    CHATBOT_RULES,
    DEFAULT_RULES,
    production_tests,
    starter_tests,
)
from redflag_backend.scan.catalog import load_catalog
from tests.helpers import OWNER, TitleJudge, wait_for_scan
from tests.test_setup_api import KEY
from tests.test_setup_chat import RoleModel
from tests.test_setup_runs import requests_seen, run_client
from tests.test_targets import StandIn

ENDPOINT = {
    "url": "https://bot.example/v1/chat/completions",
    "format": "openai",
    "model": "my-model",
}
CATALOG_IDS = {r.id for r in load_catalog().risks}


# --- the starter pack on its own ------------------------------------------------------------


def all_rules(kind: str) -> list[str]:
    return list(DEFAULT_RULES[kind])


def test_the_pack_for_a_chatbot_and_for_an_agent_has_the_expected_size_and_shape() -> None:
    chatbot = starter_tests("chatbot", all_rules("chatbot"), [])
    agent = starter_tests("agent", all_rules("agent"), [])
    assert len(chatbot) == 31 and len(agent) == 43
    for tests in (chatbot, agent):
        ids = [t["id"] for t in tests]
        bases = [t["id"] for t in tests if not t.get("strategy")]
        assert bases == [f"g-{i}" for i in range(1, len(bases) + 1)]
        assert len(set(ids)) == len(ids)
        for t in tests:
            if t.get("strategy"):
                assert t["id"] == f"{t['variation_of']}~{t['strategy']}"
        assert len({t["prompt"] for t in tests}) == len(tests)  # no two the same
        for t in tests:
            for key in (
                "title",
                "prompt",
                "goal",
                "expected",
                "rule",
                "fix",
                "kind",
                "risk",
                "severity",
            ):
                assert key in t, (t["id"], key)
            assert t["goal"].strip() and t["expected"].strip() and t["prompt"].strip()
            if t["kind"] == "negative":
                assert t["risk"] in CATALOG_IDS and t["severity"] in {"critical", "high", "medium"}
            else:
                assert t["risk"] is None and t["severity"] is None
        assert (
            sum(1 for t in tests if t["kind"] == "positive") == 5
        )  # normal requests always present


def test_the_pack_is_the_same_every_time() -> None:
    assert starter_tests("chatbot", all_rules("chatbot"), []) == starter_tests(
        "chatbot", all_rules("chatbot"), []
    )


def test_an_agent_pack_has_action_tests_that_a_chatbot_pack_does_not() -> None:
    chatbot = starter_tests("chatbot", all_rules("chatbot"), [])
    agent = starter_tests("agent", all_rules("agent"), [])
    assert not any(t["risk"] == "LLM06" for t in chatbot)
    actions = [t for t in agent if t["risk"] == "LLM06"]
    assert actions and all(t["real_action"] is True for t in actions)
    assert not any(t["real_action"] for t in chatbot)


def test_variations_are_added_to_the_key_attacks_with_the_strategies_that_name_them() -> None:
    tests = starter_tests("chatbot", all_rules("chatbot"), [])
    variants = [t for t in tests if t.get("strategy")]
    assert len(variants) == 12 and {t["strategy"] for t in variants} == {
        "authority",
        "override",
        "document",
    }
    base = {t["id"]: t for t in tests if not t.get("strategy")}
    for variant in variants:
        original = base[variant["variation_of"]]
        assert original["prompt"] in variant["prompt"] and variant["prompt"] != original["prompt"]
        assert variant["goal"] == original["goal"] and variant["expected"] == original["expected"]
        assert variant["title"].startswith(original["title"])
    assert not any(t["kind"] == "positive" and t.get("strategy") for t in tests)


def test_a_rule_the_user_unticks_removes_the_tests_that_belong_to_it() -> None:
    rules = [r for r in all_rules("chatbot") if r != CHATBOT_RULES["invented_facts"]]
    tests = starter_tests("chatbot", rules, [])
    assert not any(t["rule"] == CHATBOT_RULES["invented_facts"] for t in tests)
    assert len(tests) < 31 and sum(1 for t in tests if t["kind"] == "positive") == 5


def test_the_users_own_rule_gets_its_own_test_that_names_it() -> None:
    mine = "It must never promise a delivery date."
    tests = starter_tests("chatbot", all_rules("chatbot"), [mine])
    own = [t for t in tests if t["rule"] == mine]
    assert len(own) == 1 and mine in own[0]["prompt"] and own[0]["kind"] == "negative"
    assert own[0]["rule_unconfirmed"] is False


def test_the_default_rules_are_plain_sentences_a_person_would_tick() -> None:
    for kind in ("chatbot", "agent"):
        for rule in DEFAULT_RULES[kind]:
            assert rule.startswith("It must") and rule.endswith(".")
    assert set(CHATBOT_RULES.values()) <= set(DEFAULT_RULES["chatbot"])
    assert set(AGENT_RULES.values()) <= set(DEFAULT_RULES["agent"])
    assert set(DEFAULT_RULES["chatbot"]) <= set(
        DEFAULT_RULES["agent"]
    )  # an agent has all of them too


# --- the hello check ------------------------------------------------------------------------


def check(client: TestClient, key: str | None = KEY, **endpoint: Any) -> Any:
    return client.post(
        "/quick-scans/check", json={"endpoint": {**ENDPOINT, **endpoint}, "key": key}, headers=OWNER
    )


def test_the_hello_check_shows_what_the_bot_answered_and_saves_nothing() -> None:
    with run_client() as (client, _, endpoint):
        body = check(client).json()
        assert body["status"] == "ok" and body["parsed_reply"] == "hello from the bot"
        assert json.loads(endpoint.requests[0].content)["messages"][0]["content"] == "Hello"
        assert endpoint.requests[0].headers["authorization"] == f"Bearer {KEY}"
        assert client.get("/setups", headers=OWNER).json()["setups"] == []
        assert KEY not in json.dumps(body)


def test_the_hello_check_says_why_it_failed_and_refuses_internal_addresses() -> None:
    server = StandIn(lambda request: httpx.Response(401, text="nope"))
    with run_client(stand_in=server) as (client, _, _):
        failed = check(client).json()
        assert failed["status"] == "error" and failed["http_status"] == 401
        inside = check(client, url="http://127.0.0.1:9000/chat").json()
        assert inside["status"] == "error" and "not allowed" in inside["error"]
        assert client.post("/quick-scans/check", json={"endpoint": ENDPOINT}).status_code == 200


def test_the_hello_check_has_a_limit_so_it_cannot_be_used_to_hammer_a_server() -> None:
    with run_client(quick_checks_per_window=3) as (client, _, endpoint):
        for _ in range(3):
            assert check(client).status_code == 200
        blocked = check(client)
        assert blocked.status_code == 429 and blocked.json()["error"]["kind"] == "too_many_checks"
        assert len(endpoint.requests) == 3


def logs_answer(found: bool, fields: list[str] | None = None, shape: str = "") -> str:
    return json.dumps({"found": found, "fields": fields or [], "shape": shape})


def test_the_hello_check_says_whether_the_reply_carries_logs_and_what_they_look_like() -> None:
    model = RoleModel(
        supervisor=[logs_answer(True, ["_meta.logs"], "tool name and arguments per step")]
    )
    with run_client(roles=model) as (client, _, _):
        body = check(client).json()
        assert body["status"] == "ok"
        assert body["logs"] == {
            "found": True,
            "fields": ["_meta.logs"],
            "shape": "tool name and arguments per step",
        }


def test_a_reply_without_logs_is_reported_as_none_found_and_the_hello_still_succeeds() -> None:
    with run_client(roles=RoleModel(supervisor=[logs_answer(False)])) as (client, _, _):
        body = check(client).json()
        assert body["status"] == "ok" and body["logs"] == {
            "found": False,
            "fields": [],
            "shape": "",
        }


def test_when_the_model_cannot_read_the_reply_logs_are_unknown_not_a_failed_hello() -> None:
    model = RoleModel(supervisor=["not json", "still not json"])
    with run_client(roles=model) as (client, _, _):
        body = check(client).json()
        assert body["status"] == "ok" and body["logs"] is None


def test_the_bots_reply_goes_to_the_model_fenced_as_data_and_a_failed_hello_asks_nothing() -> None:
    model = RoleModel(supervisor=[logs_answer(False)])
    with run_client(roles=model) as (client, _, _):
        check(client)
        prompt = model.prompts("supervisor")[0]
        assert "<<<BOT REPLY" in prompt and "hello from the bot" in prompt
    failing = StandIn(lambda request: httpx.Response(401, text="nope"))
    model = RoleModel(supervisor=[logs_answer(True, ["logs"])])
    with run_client(stand_in=failing, roles=model) as (client, _, _):
        body = check(client).json()
        assert body["status"] == "error" and body["logs"] is None
        assert model.prompts("supervisor") == []


# --- setting up and running in one call -----------------------------------------------------


def quick(client: TestClient, **changes: Any) -> Any:
    body: dict[str, Any] = {
        "endpoint": ENDPOINT,
        "key": KEY,
        "bot_type": "chatbot",
        "purpose": "A support bot for a bank.",
        "must_never": all_rules("chatbot"),
    }
    body.update(changes)
    return client.post("/quick-scans", json=body, headers=OWNER)


def test_a_quick_scan_sets_the_bot_up_and_runs_the_whole_pack_without_a_select_step() -> None:
    with run_client() as (client, judge, endpoint):
        started = quick(client)
        assert started.status_code == 202
        info = started.json()
        scan = wait_for_scan(client, info["scan_id"], timeout=60)
        setup = client.get(f"/setups/{info['setup_id']}", headers=OWNER).json()
        sent = len(requests_seen(endpoint))
    assert info["version"] == 1 and info["test_count"] == 31
    assert scan["scan"]["status"] == "completed" and len(scan["results"]) == 31
    assert sent == 31 and len(judge.calls) == 31
    assert setup["fields"]["purpose"]["value"] == "A support bot for a bank."
    assert {r["text"] for r in setup["fields"]["rules"]} == set(all_rules("chatbot"))
    assert all(
        r["status"] == "stated" and r["kind"] == "forbidden" for r in setup["fields"]["rules"]
    )
    assert scan["scan"]["settings"]["setup"]["version"] == 1


def test_the_judge_is_told_the_purpose_and_the_rules_and_never_the_key() -> None:
    with run_client() as (client, judge, _):
        info = quick(client).json()
        wait_for_scan(client, info["scan_id"], timeout=60)
    prompt = judge.calls[0].messages[1].content
    assert "A support bot for a bank." in prompt
    assert CHATBOT_RULES["system_prompt"] in prompt
    assert KEY not in str(judge.calls[0].messages)


def test_the_key_is_used_for_the_run_and_saved_nowhere() -> None:
    with run_client() as (client, _, endpoint):
        info = quick(client).json()
        scan = wait_for_scan(client, info["scan_id"], timeout=60)
        assert requests_seen(endpoint)[0].headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in json.dumps(scan)
        assert KEY not in client.get(f"/setups/{info['setup_id']}", headers=OWNER).text


def test_an_agent_scan_needs_the_sandbox_box_ticked_and_gets_the_action_tests() -> None:
    with run_client() as (client, _, _):
        refused = quick(client, bot_type="agent", must_never=all_rules("agent"))
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "sandbox_required"
        assert client.get("/setups", headers=OWNER).json()["setups"] == []
        started = quick(
            client, bot_type="agent", must_never=all_rules("agent"), sandbox_confirmed=True
        )
        assert started.status_code == 202 and started.json()["test_count"] == 43
        wait_for_scan(client, started.json()["scan_id"], timeout=90)


# --- production: the OWASP tests the owner picks from --------------------------------------------


def offered(client: TestClient, bot_type: str = "chatbot") -> list[dict[str, Any]]:
    response = client.post(
        "/quick-scans/production-tests",
        json={"bot_type": bot_type, "must_never": all_rules(bot_type)},
    )
    assert response.status_code == 200, response.text
    return response.json()["tests"]


def test_the_production_list_is_only_attacks_and_never_makes_an_agent_act() -> None:
    for bot_type in ("chatbot", "agent"):
        tests = production_tests(bot_type, all_rules(bot_type), [])
        assert tests and all(t["kind"] == "negative" and not t["real_action"] for t in tests)
    agent = production_tests("agent", all_rules("agent"), [])
    assert not any(t["risk"] == "LLM06" for t in agent)
    full = {t["id"]: t for t in starter_tests("agent", all_rules("agent"), [])}
    assert all(full[t["id"]] == t for t in agent)  # the same tests, the same ids


def test_the_production_list_names_each_test_by_its_owasp_risk_and_runs_nothing() -> None:
    with run_client() as (client, _, endpoint):
        tests = offered(client)
        assert tests[0].keys() == {"id", "title", "goal", "risk", "risk_name", "severity"}
        assert {t["risk"] for t in tests} <= CATALOG_IDS
        assert all(t["risk_name"] and t["risk_name"] != t["risk"] for t in tests)
        assert endpoint.requests == []
        assert client.get("/setups", headers=OWNER).json()["setups"] == []


def test_the_production_list_refuses_a_bad_bot_type_and_no_rules() -> None:
    with run_client() as (client, _, _):
        bad = client.post(
            "/quick-scans/production-tests", json={"bot_type": "x", "must_never": ["a"]}
        )
        none = client.post(
            "/quick-scans/production-tests", json={"bot_type": "chatbot", "must_never": [" "]}
        )
        assert bad.json()["error"]["kind"] == "bad_bot_type"
        assert none.json()["error"]["kind"] == "rules_required"


def test_a_production_scan_runs_only_the_tests_picked_and_an_agent_needs_no_sandbox_tick() -> None:
    with run_client() as (client, _, _):
        tests = offered(client, "agent")
        picked = [tests[0]["id"], tests[2]["id"]]
        started = quick(
            client,
            bot_type="agent",
            must_never=all_rules("agent"),
            environment="production",
            test_ids=picked,
        )
        assert started.status_code == 202 and started.json()["test_count"] == 2
        scan = wait_for_scan(client, started.json()["scan_id"], timeout=90)
        assert {r["test_id"] for r in scan["results"]} == set(picked)


def test_a_production_scan_needs_a_pick_and_refuses_a_test_that_was_not_offered() -> None:
    with run_client() as (client, _, _):
        none = quick(client, environment="production")
        empty = quick(client, environment="production", test_ids=[])
        # g-99 is not offered, and neither is a real-action test of the full pack
        action = next(
            t["id"] for t in starter_tests("agent", all_rules("agent"), []) if t["real_action"]
        )
        unknown = quick(client, environment="production", test_ids=["g-99"])
        acting = quick(
            client,
            bot_type="agent",
            must_never=all_rules("agent"),
            environment="production",
            test_ids=[action],
        )
        for refused, kind in ((none, "no_tests_selected"), (empty, "no_tests_selected")):
            assert refused.status_code == 422 and refused.json()["error"]["kind"] == kind
        for refused in (unknown, acting):
            assert refused.status_code == 422 and refused.json()["error"]["kind"] == "unknown_test"
        assert client.get("/setups", headers=OWNER).json()["setups"] == []


def test_staging_is_the_default_and_still_runs_the_full_pack_and_asks_agents_for_the_tick() -> None:
    with run_client() as (client, _, _):
        refused = quick(
            client, bot_type="agent", must_never=all_rules("agent"), environment="staging"
        )
        assert refused.json()["error"]["kind"] == "sandbox_required"


def test_the_users_own_rules_are_added_and_unticked_defaults_are_left_out() -> None:
    mine = "It must never promise a delivery date."
    rules = [r for r in all_rules("chatbot") if r != CHATBOT_RULES["invented_facts"]] + [mine]
    with run_client() as (client, _, _):
        info = quick(client, must_never=rules).json()
        scan = wait_for_scan(client, info["scan_id"], timeout=60)
        setup = client.get(f"/setups/{info['setup_id']}", headers=OWNER).json()
    texts = {r["text"] for r in setup["fields"]["rules"]}
    assert mine in texts and CHATBOT_RULES["invented_facts"] not in texts
    assert any(r["rule"] == mine for r in scan["results"])


def test_bad_requests_are_refused_and_create_nothing() -> None:
    with run_client() as (client, _, endpoint):
        assert quick(client, purpose="  ").json()["error"]["kind"] == "purpose_required"
        assert quick(client, bot_type="robot").json()["error"]["kind"] == "bad_bot_type"
        assert quick(client, must_never=[]).json()["error"]["kind"] == "rules_required"
        assert client.post("/quick-scans", json={}).status_code == 422
        assert client.get("/setups", headers=OWNER).json()["setups"] == []
        assert requests_seen(endpoint) == []


def test_a_bot_that_cannot_be_reached_is_refused_with_the_reason_and_creates_nothing() -> None:
    server = StandIn(lambda request: httpx.Response(401, text="nope"))
    with run_client(stand_in=server) as (client, _, _):
        refused = quick(client)
        assert refused.status_code == 422 and refused.json()["error"]["kind"] == "connection_failed"
        assert "401" in refused.json()["error"]["message"]
        assert client.get("/setups", headers=OWNER).json()["setups"] == []


def test_a_quick_scan_cannot_start_while_another_scan_is_running() -> None:
    from tests.test_setup_runs import SlowEndpoint

    with run_client(stand_in=SlowEndpoint()) as (client, _, _):
        first = quick(client)
        assert first.status_code == 202
        blocked = quick(client)
        assert blocked.status_code == 409 and blocked.json()["error"]["kind"] == "scan_running"
        wait_for_scan(client, first.json()["scan_id"], timeout=120)


def test_the_setup_it_made_can_be_resumed_tailored_and_run_again() -> None:
    with run_client() as (client, _, _):
        info = quick(client).json()
        first = wait_for_scan(client, info["scan_id"], timeout=60)
        listing = client.get("/setups", headers=OWNER).json()["setups"]
        assert listing[0]["setup_id"] == info["setup_id"] and listing[0]["versions"] == 1
        again = client.post(f"/scans/{first['scan']['id']}/rerun", json={"key": KEY}, headers=OWNER)
        assert again.status_code == 202
        second = wait_for_scan(client, again.json()["scan_id"], timeout=60)
    assert second["scan"]["previous_scan_id"] == first["scan"]["id"]


def test_a_quick_scan_judges_with_the_ai_judge_alone_like_any_real_bot_scan() -> None:
    judge = TitleJudge(garbage={"What are your standard details?"})
    with run_client(judge) as (client, _, _):
        info = quick(client).json()
        scan = wait_for_scan(client, info["scan_id"], timeout=60)
    assert all(r["rule_status"] is None for r in scan["results"])
    assert all(r["judge_status"] is not None for r in scan["results"])


def test_the_default_rules_are_served_so_the_page_never_keeps_its_own_copy() -> None:
    with run_client() as (client, _, _):
        body = client.get("/quick-scans/rules", headers=OWNER).json()
        assert body["rules"]["chatbot"] == DEFAULT_RULES["chatbot"]
        assert body["rules"]["agent"] == DEFAULT_RULES["agent"]
        assert client.get("/quick-scans/rules").status_code == 200  # no password needed
