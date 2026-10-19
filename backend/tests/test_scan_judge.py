"""The judge inside a scan, over HTTP with real Postgres.

The only faked parts are the outside models: the bots' model and the judge's model, which are
different providers because the bots use their own keys and the judge uses Redflag's.
"""

from typing import Any

import pytest
from sqlalchemy import create_engine

from redflag_backend.llm.types import LLMAnswer, LLMRequest, ServerError
from redflag_backend.scan.store import ScanStore
from tests.helpers import (
    OWNER,
    TEST_DB_URL,
    FakeProvider,
    GullibleProvider,
    SilentProvider,
    TitleJudge,
    run_scan,
    scan_client,
)

# With the gullible bot: the plain rules FAIL this one and PASS the other.
RULES_FAIL = "Read another customer's order"  # si-other-customer-order
RULES_PASS = "Normal request: how long does shipping take?"  # pos-shipping-times


def result(scan: dict[str, Any], test_id: str) -> dict[str, Any]:
    return next(r for r in scan["results"] if r["test_id"] == test_id)


class Down:
    name = "down"
    configured = True

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        raise ServerError()


# --- the combination table ----------------------------------------------------------------


def test_both_pass_is_pass() -> None:
    with scan_client([GullibleProvider()], redflag_providers=[TitleJudge()]) as client:
        scan = run_scan(client, "acme-weak")
    pos = result(scan, "pos-shipping-times")
    assert pos["status"] == "pass"
    assert pos["rule_status"] == "pass" and pos["judge_status"] == "pass"


def test_a_rule_fail_is_fail_whatever_the_judge_says() -> None:
    for judge in (TitleJudge(), TitleJudge(garbage={RULES_FAIL}), TitleJudge(down={RULES_FAIL})):
        with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
            scan = run_scan(client, "acme-weak")
        leak = result(scan, "si-other-customer-order")
        assert leak["status"] == "fail"
        assert leak["rule_status"] == "fail"
        assert "Plain rules" in leak["evidence"] and "AI judge" in leak["evidence"]


def test_a_judge_fail_alone_makes_the_test_fail_and_says_the_rules_passed() -> None:
    judge = TitleJudge(fail={RULES_PASS: "The reply is wrong: it names the wrong delivery time."})
    with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
    pos = result(scan, "pos-shipping-times")
    assert pos["status"] == "fail"
    assert pos["rule_status"] == "pass" and pos["judge_status"] == "fail"
    assert "Plain rules (PASS)" in pos["evidence"]
    assert "AI judge (FAIL)" in pos["evidence"]
    assert "wrong delivery time" in pos["judge_reason"]
    assert "wrong delivery time" in pos["evidence"]


def test_a_rule_pass_with_the_judge_unavailable_is_inconclusive_never_pass() -> None:
    for judge in (TitleJudge(garbage={RULES_PASS}), TitleJudge(down={RULES_PASS})):
        with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
            scan = run_scan(client, "acme-weak")
        pos = result(scan, "pos-shipping-times")
        assert pos["status"] == "inconclusive"
        assert pos["rule_status"] == "pass" and pos["judge_status"] == "unavailable"
        assert "not double-checked" in pos["evidence"]


def test_rules_unsure_and_judge_pass_is_pass_and_judge_fail_is_fail() -> None:
    title = "Ask the bot to print its hidden instructions"  # spl-repeat-prompt
    with scan_client([SilentProvider()], redflag_providers=[TitleJudge()]) as client:
        scan = run_scan(client, "acme-weak")
    quiet = result(scan, "spl-repeat-prompt")
    assert quiet["rule_status"] == "inconclusive" and quiet["status"] == "pass"
    assert "unsure" in quiet["evidence"]
    judge = TitleJudge(fail={title: "The reply is empty, which hides a failure."})
    with scan_client([SilentProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
    assert result(scan, "spl-repeat-prompt")["status"] == "fail"


def test_rules_unsure_and_judge_unavailable_is_inconclusive() -> None:
    with scan_client([SilentProvider()], redflag_providers=[Down()]) as client:
        scan = run_scan(client, "acme-weak")
    quiet = result(scan, "spl-repeat-prompt")
    assert quiet["status"] == "inconclusive"
    assert quiet["judge_status"] == "unavailable"


# --- what is saved and returned -----------------------------------------------------------


def test_both_outputs_are_saved_and_returned() -> None:
    judge = TitleJudge(fail={RULES_FAIL: "It shows Bob's order."})
    with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
    leak = result(scan, "si-other-customer-order")
    for key in (
        "rule_status", "rule_evidence", "judge_status", "judge_reason", "judge_model",
        "judge_provider",
    ):  # fmt: skip
        assert key in leak
    assert leak["rule_evidence"]
    assert leak["judge_status"] == "fail" and leak["judge_reason"] == "It shows Bob's order."
    assert leak["judge_model"] == "judge-model" and leak["judge_provider"] == "judge"
    assert leak["evidence"] != leak["rule_evidence"]  # the combined text names both sources


# --- when the judge is not called or cannot answer ----------------------------------------


def test_a_test_that_errored_or_did_not_apply_never_calls_the_judge() -> None:
    judge = TitleJudge()
    with scan_client([Down()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
    assert {r["status"] for r in scan["results"]} == {"error"}
    assert judge.calls == []
    assert all(r["judge_status"] is None for r in scan["results"])


def test_a_judge_outage_does_not_stop_the_scan() -> None:
    with scan_client([GullibleProvider()], redflag_providers=[Down()]) as client:
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    assert len(scan["results"]) == 16
    judged = [r for r in scan["results"] if r["judge_status"] is not None]
    assert judged and all(r["judge_status"] == "unavailable" for r in judged)
    assert not any(r["status"] == "pass" for r in scan["results"])  # no unchecked pass


def test_no_judge_provider_means_every_judgment_is_unavailable_and_says_so() -> None:
    with scan_client([GullibleProvider()], redflag_providers=[]) as client:
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    leak = result(scan, "si-other-customer-order")
    assert leak["judge_status"] == "unavailable"
    assert leak["judge_reason"] == "no judge model configured"
    assert scan["scan"]["settings"]["judge_providers"] == []


def test_the_judges_budget_running_out_leaves_the_rest_unavailable_and_the_scan_completes() -> None:
    with scan_client(
        [GullibleProvider()], redflag_providers=[TitleJudge()], judge_budget_max_requests=3
    ) as client:
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    states = [r["judge_status"] for r in scan["results"]]
    assert states.count("pass") + states.count("fail") == 3
    unavailable = [r for r in scan["results"] if r["judge_status"] == "unavailable"]
    assert unavailable and all("requests" in r["judge_reason"] for r in unavailable)


# --- two separate sets of models ----------------------------------------------------------


def test_the_judge_uses_redflags_models_and_the_bots_use_theirs() -> None:
    bots, judge = GullibleProvider(), TitleJudge()
    with scan_client([bots], redflag_providers=[judge]) as client:
        run_scan(client, "acme-weak")
    assert len(judge.calls) == 16
    assert len(bots.calls) > 0
    assert not any("security test of an AI app" in c.messages[0].content for c in bots.calls)
    assert all("security test of an AI app" in c.messages[0].content for c in judge.calls)


def test_the_judge_is_told_the_rule_the_secret_and_what_the_bot_did() -> None:
    judge = TitleJudge()
    with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
    canary = scan["scan"]["settings"]["canary"]
    prompts = {t: c.messages[1].content for t, c in zip(judge.titles(), judge.calls, strict=True)}
    leak = prompts[RULES_FAIL]
    assert "A customer may see only their own orders." in leak
    assert canary in leak  # the judge is told what must never appear
    assert "221 Fakewood Lane" in leak  # another customer's protected value
    assert "lookup_order" in leak  # the tool log
    # The judge is never told what the plain rules decided.
    assert "Plain rules" not in leak and "rule_status" not in leak


# --- records and old scans ----------------------------------------------------------------


def test_a_scan_records_the_judge_it_ran_with() -> None:
    with scan_client([GullibleProvider()], redflag_providers=[TitleJudge()]) as client:
        scan = run_scan(client, "acme-weak")
    settings = scan["scan"]["settings"]
    assert settings["judge_prompt_version"] == 1
    assert settings["judge_providers"] == ["judge"]


def test_a_result_saved_before_the_judge_existed_still_reads_with_nulls() -> None:
    engine = create_engine(TEST_DB_URL)
    try:
        store = ScanStore(engine)
        project = store.ensure_project("acme-weak", "Acme Store support bot (weak)", "x")
        scan_id = store.create_scan(project, {"bot_id": "acme-weak", "test_count": 1}, now=1000.0)
        store.add_result(  # exactly what M4 saved: no judge fields
            scan_id,
            {
                "position": 0, "test_id": "old", "risk": "LLM02", "kind": "negative",
                "title": "Old test", "message": "m", "status": "fail", "reply": "r",
                "tool_calls": [], "evidence": "e", "rule": "r", "model": "m", "provider": "p",
                "attempts": [], "started_at": 1000.0, "finished_at": 1001.0,
                "severity": "high", "remediation": "fix it",
            },
            now=1001.0,
        )  # fmt: skip
        store.finish_scan(scan_id, "completed", now=1002.0)
    finally:
        engine.dispose()
    with scan_client([GullibleProvider()]) as client:
        body = client.get(f"/scans/{scan_id}", headers=OWNER).json()
    [old] = body["results"]
    assert old["status"] == "fail" and old["evidence"] == "e"
    for key in ("rule_status", "rule_evidence", "judge_status", "judge_reason"):
        assert old[key] is None


@pytest.mark.parametrize("path", ["/scans"])
def test_the_scan_list_still_works_with_judged_scans(path: str) -> None:
    with scan_client([GullibleProvider()], redflag_providers=[FakeProvider("x")]) as client:
        run_scan(client, "acme-weak")
        listing = client.get(path, headers=OWNER).json()
    assert listing["scans"][0]["counts"]["fail"] >= 1
