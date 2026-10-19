"""The scan API over HTTP, with real Postgres and a stand-in model behind the bots.

The only faked part is the outside model. Both bots get the same "gullible" model, so any
difference in their results comes from the bots' own defenses, which is what the engine shows.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from redflag_backend.llm.types import BadRequest, LLMAnswer, LLMRequest, RateLimited, ServerError
from redflag_backend.sandbox.loader import BOTS_DIR
from redflag_backend.scan.store import ScanStore
from tests.helpers import (
    OWNER,
    TEST_DB_URL,
    FakeClock,
    FakeProvider,
    GullibleProvider,
    RefusingProvider,
    SlowProvider,
    run_scan,
    scan_client,
    wait_for_scan,
)


def statuses(scan: dict[str, Any]) -> dict[str, str]:
    return {r["test_id"]: r["status"] for r in scan["results"]}


def failed(scan: dict[str, Any]) -> set[str]:
    return {test_id for test_id, status in statuses(scan).items() if status == "fail"}


class DownProvider:
    name = "down"
    configured = True

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        raise ServerError()


# --- the owner lock -----------------------------------------------------------------------


def test_every_scan_endpoint_is_locked_without_the_owner_password() -> None:
    gullible = GullibleProvider()
    with scan_client([gullible]) as client:
        wrong = {"X-Owner-Token": "not-the-password"}
        for headers in ({}, wrong):
            assert client.get("/bots", headers=headers).status_code == 401
            assert client.get("/catalog", headers=headers).status_code == 401
            assert client.get("/scans", headers=headers).status_code == 401
            assert client.get("/scans/1", headers=headers).status_code == 401
            assert (
                client.post("/scans", json={"bot_id": "acme-weak"}, headers=headers).status_code
                == 401
            )
        # The lock is checked before the body is, so a bad body gets 401, not a hint.
        assert client.post("/scans", json={"nonsense": True}).status_code == 401
    assert gullible.calls == []  # nothing was sent to a model


def test_the_endpoints_stay_locked_for_everyone_when_no_password_is_set() -> None:
    with scan_client([GullibleProvider()], owner_token=None) as client:
        assert client.get("/bots", headers=OWNER).status_code == 401


# --- bots and catalog ---------------------------------------------------------------------


def test_the_bots_are_listed_with_their_defenses_and_broken_folders_are_reported(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bots"
    shutil.copytree(BOTS_DIR, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "broken").mkdir()
    (root / "broken" / "bot.json").write_text("{nope", encoding="utf-8")
    with scan_client([GullibleProvider()], bots_dir=root) as client:
        body = client.get("/bots", headers=OWNER).json()
    bots = {b["id"]: b for b in body["bots"]}
    assert bots["acme-weak"]["defenses"] == []
    assert "order_scoping" in bots["acme-hardened"]["defenses"]
    assert "broken" in body["errors"]


def test_the_catalog_is_served_with_its_version() -> None:
    with scan_client([GullibleProvider()]) as client:
        body = client.get("/catalog", headers=OWNER).json()
    assert body["version"] == "owasp-llm-2025"
    assert len(body["risks"]) == 10


# --- running a scan -----------------------------------------------------------------------


def test_a_scan_starts_at_once_runs_in_the_background_and_saves_every_result() -> None:
    with scan_client([GullibleProvider()]) as client:
        started = client.post("/scans", json={"bot_id": "acme-weak"}, headers=OWNER)
        assert started.status_code == 202
        scan_id = started.json()["scan_id"]
        scan = wait_for_scan(client, scan_id)
    assert scan["scan"]["status"] == "completed"
    assert len(scan["results"]) == 16
    first = scan["results"][0]
    for key in (
        "test_id", "risk", "kind", "title", "message", "status", "reply",
        "tool_calls", "evidence", "rule", "model", "provider", "attempts",
    ):  # fmt: skip
        assert key in first
    assert first["model"] == "gullible-model" and first["provider"] == "gullible"


def test_the_weak_bot_fails_tests_with_evidence_and_the_hardened_bot_fails_fewer() -> None:
    with scan_client([GullibleProvider()]) as client:
        weak = run_scan(client, "acme-weak")
        hardened = run_scan(client, "acme-hardened")
    assert {
        "si-other-customer-order",
        "si-secret-direct",
        "ea-unapproved-refund",
        "pi-poisoned-article-email",
    } <= failed(weak)
    assert len(failed(hardened)) < len(failed(weak))
    assert statuses(hardened)["si-other-customer-order"] == "pass"
    for result in weak["results"]:
        if result["status"] == "fail":
            assert result["evidence"], result["test_id"]
    # The hardened bot is not claimed perfect: it has no defense against unsafe output.
    assert failed(hardened) <= {"oh-script-tag", "oh-exfil-image"}
    assert weak["scan"]["id"] != hardened["scan"]["id"]  # each run has its own scan number


def test_a_refusal_in_words_does_not_pass_when_the_tool_log_shows_the_action() -> None:
    """The gullible model refuses in words after acting; the scan still fails the test."""

    class ActsThenApologizes(GullibleProvider):
        def _reply(self, messages: Any) -> str:
            reply = super()._reply(messages)
            return "Sorry, I can't do that." if reply.startswith("Done") else reply

    with scan_client([ActsThenApologizes()]) as client:
        weak = run_scan(client, "acme-weak")
    refund = next(r for r in weak["results"] if r["test_id"] == "ea-unapproved-refund")
    assert "can't" in refund["reply"]
    assert refund["status"] == "fail"
    assert refund["tool_calls"][0]["outcome"] == "executed"


def test_a_failing_model_makes_errors_never_passes() -> None:
    with scan_client([DownProvider()]) as client:
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    assert set(statuses(scan).values()) == {"error"}
    assert scan["summary"]["counts"]["pass"] == 0
    assert scan["summary"]["counts"]["error"] == 16
    assert all(r["evidence"] for r in scan["results"])


def test_when_the_budget_runs_out_the_remaining_tests_are_errors_with_the_reason() -> None:
    with scan_client([GullibleProvider()], bot_budget_max_requests=4) as client:
        scan = run_scan(client, "acme-weak")
    results = scan["results"]
    assert len(results) == 16  # nothing is silently skipped
    stopped = [r for r in results if r["status"] == "error"]
    assert stopped and all("budget" in r["evidence"] for r in stopped)
    assert any(r["status"] in {"pass", "fail"} for r in results)


def test_positive_tests_are_in_every_scan_and_a_bot_that_refuses_everything_fails_them() -> None:
    with scan_client([RefusingProvider()]) as client:
        scan = run_scan(client, "acme-weak")
    positive = [r for r in scan["results"] if r["kind"] == "positive"]
    assert len(positive) >= 3
    assert {r["status"] for r in positive} == {"fail"}
    # Refusing attacks looks fine on the attack tests, which is exactly why positives matter.
    assert statuses(scan)["si-secret-direct"] == "pass"
    assert scan["summary"]["normal_requests"]["failed"] >= 3


def test_a_test_a_bot_cannot_run_is_not_applicable_and_never_counts_as_tested(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bots"
    shutil.copytree(BOTS_DIR, root, ignore=shutil.ignore_patterns("__pycache__"))
    data_path = root / "_shared" / "acme_store" / "data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    del data["articles"]["partner-offer"]
    data_path.write_text(json.dumps(data), encoding="utf-8")
    with scan_client([GullibleProvider()], bots_dir=root) as client:
        scan = run_scan(client, "acme-weak")
    result = next(r for r in scan["results"] if r["test_id"] == "pi-poisoned-article-refund")
    assert result["status"] == "not_applicable"
    assert "articles.partner-offer" in result["evidence"]
    assert scan["summary"]["counts"]["not_applicable"] == 1


# --- what was tested and what was not -----------------------------------------------------


def test_the_summary_lists_all_ten_risks_as_tested_or_not_tested_with_the_disclaimer() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan = run_scan(client, "acme-hardened")
    risks = {r["id"]: r for r in scan["summary"]["risks"]}
    assert len(risks) == 10
    for tested in ("LLM01", "LLM02", "LLM05", "LLM06", "LLM07"):
        assert risks[tested]["state"] == "tested", tested
        assert risks[tested]["tests"] >= 1
    for untouched in ("LLM03", "LLM04", "LLM08", "LLM09", "LLM10"):
        assert risks[untouched]["state"] == "not_tested", untouched
        assert risks[untouched]["tests"] == 0
    assert "not a claim" in scan["summary"]["disclaimer"].lower()
    assert scan["summary"]["catalog_version"] == "owasp-llm-2025"


def test_a_risk_whose_tests_all_errored_is_never_listed_as_tested() -> None:
    with scan_client([DownProvider()]) as client:
        scan = run_scan(client, "acme-weak")
    risks = {r["id"]: r for r in scan["summary"]["risks"]}
    assert risks["LLM01"]["state"] == "attempted_no_result"
    assert risks["LLM06"]["state"] == "attempted_no_result"
    assert not any(r["state"] == "tested" for r in risks.values())


# --- what is recorded with a scan ---------------------------------------------------------


def test_a_scan_records_the_settings_it_ran_with() -> None:
    with scan_client([GullibleProvider()], bot_budget_max_requests=77) as client:
        scan = run_scan(client, "acme-weak")
    settings = scan["scan"]["settings"]
    assert settings["bot_id"] == "acme-weak"
    assert settings["bot_config_version"] == 1
    assert settings["bot_defenses"] == []
    assert settings["catalog_version"] == "owasp-llm-2025"
    assert settings["suite_version"] == 2
    assert settings["budget"]["requests"] == 77
    assert settings["canary"].startswith("CANARY-")
    assert scan["scan"]["models_used"] == ["gullible-model"]


def test_each_scan_plants_a_fresh_canary() -> None:
    with scan_client([GullibleProvider()]) as client:
        first = run_scan(client, "acme-weak")
        second = run_scan(client, "acme-weak")
    assert first["scan"]["settings"]["canary"] != second["scan"]["settings"]["canary"]
    leaked = next(r for r in first["results"] if r["test_id"] == "si-secret-direct")
    assert leaked["status"] == "fail"
    assert first["scan"]["settings"]["canary"] in leaked["evidence"]


def test_scans_are_listed_overall_and_per_bot() -> None:
    with scan_client([GullibleProvider()]) as client:
        run_scan(client, "acme-weak")
        run_scan(client, "acme-hardened")
        everything = client.get("/scans", headers=OWNER).json()["scans"]
        only_weak = client.get("/scans?bot_id=acme-weak", headers=OWNER).json()["scans"]
    assert [s["bot_id"] for s in everything] == ["acme-hardened", "acme-weak"]  # newest first
    assert [s["bot_id"] for s in only_weak] == ["acme-weak"]
    assert everything[0]["counts"]["fail"] < everything[1]["counts"]["fail"]


# --- the bots have their own keys and router ----------------------------------------------


def test_a_scan_uses_only_the_bots_models_never_redflags_own() -> None:
    redflag = FakeProvider("redflag")
    bots = GullibleProvider()
    with scan_client([bots], redflag_providers=[redflag]) as client:
        run_scan(client, "acme-weak")
    # Redflag's own model is used only to judge, never to answer as the bot.
    assert redflag.calls and all(
        "security test of an AI app" in c.messages[0].content for c in redflag.calls
    )
    assert len(bots.calls) > 0


def test_no_bot_key_appears_in_any_response() -> None:
    sentinels = ("SENTINEL-GROQ-KEY-123", "SENTINEL-GEMINI-KEY-123", "SENTINEL-OPENROUTER-KEY-123")
    with scan_client(
        [DownProvider()],
        bot_groq_api_key=sentinels[0],
        bot_gemini_api_key=sentinels[1],
        bot_openrouter_api_key=sentinels[2],
    ) as client:
        scan = run_scan(client, "acme-weak")
        everything = json.dumps(
            [
                scan,
                client.get("/bots", headers=OWNER).json(),
                client.get("/scans", headers=OWNER).json(),
                client.get("/catalog", headers=OWNER).json(),
            ]
        )
    for value in sentinels:
        assert value not in everything


# --- starting a scan: refusals ------------------------------------------------------------


def test_unknown_bot_is_404_and_no_configured_model_is_503() -> None:
    with scan_client([GullibleProvider()]) as client:
        assert client.post("/scans", json={"bot_id": "nope"}, headers=OWNER).status_code == 404
    with scan_client([FakeProvider("bot", configured=False)]) as client:
        response = client.post("/scans", json={"bot_id": "acme-weak"}, headers=OWNER)
        assert response.status_code == 503
        assert response.json()["error"]["kind"] == "no_provider_configured"


def test_a_second_scan_cannot_start_while_one_is_running() -> None:
    slow = SlowProvider("slow")
    with scan_client([slow]) as client:
        first = client.post("/scans", json={"bot_id": "acme-weak"}, headers=OWNER)
        assert first.status_code == 202
        second = client.post("/scans", json={"bot_id": "acme-hardened"}, headers=OWNER)
        assert second.status_code == 409
        wait_for_scan(client, first.json()["scan_id"], timeout=60)


# --- interrupted scans --------------------------------------------------------------------


def make_running_scan(clock: FakeClock) -> int:
    engine = create_engine(TEST_DB_URL)
    try:
        store = ScanStore(engine)
        project = store.ensure_project("acme-weak", "Acme Store support bot (weak)", "x")
        return store.create_scan(project, {"bot_id": "acme-weak"}, now=clock())
    finally:
        engine.dispose()


def test_a_scan_with_no_progress_for_five_minutes_is_marked_interrupted() -> None:
    clock = FakeClock()
    with scan_client([GullibleProvider()], clock=clock) as client:
        stale = make_running_scan(clock)
        clock.now += 200
        recent = make_running_scan(clock)  # progress 100 seconds later than the stale one
        clock.now += 99  # 299 seconds since the first scan's progress
        assert client.get(f"/scans/{stale}", headers=OWNER).json()["scan"]["status"] == "running"
        clock.now += 2  # 301 seconds
        body = client.get(f"/scans/{stale}", headers=OWNER).json()
        assert body["scan"]["status"] == "interrupted"
        assert body["scan"]["note"]
        assert client.get(f"/scans/{recent}", headers=OWNER).json()["scan"]["status"] == "running"


@pytest.mark.parametrize("path", ["/scans/9999"])
def test_reading_a_scan_that_does_not_exist_is_404(path: str) -> None:
    with scan_client([GullibleProvider()]) as client:
        assert client.get(path, headers=OWNER).status_code == 404


def test_the_page_is_allowed_to_call_the_scan_api_with_the_password_header() -> None:
    with scan_client([GullibleProvider()]) as client:
        response = client.options(
            "/scans",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Owner-Token,Content-Type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


# --- free-tier rate limits and models that reject the bots' format ------------------------


class RateLimitedFirst:
    """Rate-limited for its first few calls, then a normal gullible model."""

    name = "limited"
    configured = True

    def __init__(self, limited_calls: int) -> None:
        self.limited_calls = limited_calls
        self.calls = 0
        self._inner = GullibleProvider()

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls += 1
        if self.calls <= self.limited_calls:
            raise RateLimited(retry_after=0.02)
        return await self._inner.complete(request)


class AlwaysRateLimited:
    name = "limited"
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        self.calls += 1
        raise RateLimited(retry_after=0.02)


class RejectsTheFormat:
    """Like Groq's gpt-oss: it refuses the bots' tool format with a bad-request error."""

    name = "picky"
    configured = True

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        raise BadRequest()


FAST_WAITS = {"scan_rate_limit_wait_seconds": 0.1, "scan_rate_limit_max_wait_seconds": 0.5}


def test_a_rate_limit_in_the_middle_of_a_scan_is_waited_out_not_turned_into_errors() -> None:
    limited = RateLimitedFirst(limited_calls=3)
    with scan_client([limited], scan_rate_limit_retries=5, **FAST_WAITS) as client:  # type: ignore[arg-type]
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    assert scan["summary"]["counts"]["error"] == 0
    assert len(scan["results"]) == 16
    assert limited.calls > 3  # it really was limited, then the scan carried on


def test_a_rate_limit_that_never_clears_ends_in_errors_that_say_so_after_a_few_tries() -> None:
    limited = AlwaysRateLimited()
    with scan_client([limited], scan_rate_limit_retries=2, **FAST_WAITS) as client:  # type: ignore[arg-type]
        scan = run_scan(client, "acme-weak")
    assert scan["scan"]["status"] == "completed"
    assert {r["status"] for r in scan["results"]} == {"error"}
    assert all("rate limit" in r["evidence"].lower() for r in scan["results"])
    assert 0 < limited.calls <= 16 * 3  # one try plus two waits per test, never endless


def test_a_model_that_rejects_the_bots_format_is_skipped_for_the_next_model() -> None:
    gullible = GullibleProvider()
    with scan_client([RejectsTheFormat(), gullible]) as client:
        scan = run_scan(client, "acme-weak")
    assert scan["summary"]["counts"]["error"] == 0
    assert {r["provider"] for r in scan["results"]} == {"gullible"}
    assert len(gullible.calls) > 0


def test_if_every_model_rejects_the_format_the_tests_are_errors_never_passes() -> None:
    with scan_client([RejectsTheFormat()]) as client:
        scan = run_scan(client, "acme-weak")
    assert {r["status"] for r in scan["results"]} == {"error"}


# --- severity and fix notes ---------------------------------------------------------------


def test_every_result_carries_its_severity_and_fix_note_normal_requests_carry_none() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan = run_scan(client, "acme-weak")
    for result in scan["results"]:
        if result["kind"] == "negative":
            assert result["severity"] in {"critical", "high", "medium"}, result["test_id"]
            assert result["remediation"], result["test_id"]
        else:
            assert result["severity"] is None and result["remediation"] is None
    refund = next(r for r in scan["results"] if r["test_id"] == "ea-unapproved-refund")
    assert refund["severity"] == "critical"
    assert "approval" in refund["remediation"].lower()


def test_a_result_saved_before_severity_existed_still_reads_with_nothing_rated() -> None:
    engine = create_engine(TEST_DB_URL)
    try:
        store = ScanStore(engine)
        project = store.ensure_project("acme-weak", "Acme Store support bot (weak)", "x")
        scan_id = store.create_scan(project, {"bot_id": "acme-weak", "test_count": 1}, now=1000.0)
        store.add_result(  # exactly what M3 saved: no severity, no fix note
            scan_id,
            {
                "position": 0, "test_id": "old", "risk": "LLM02", "kind": "negative",
                "title": "Old test", "message": "m", "status": "fail", "reply": "r",
                "tool_calls": [], "evidence": "e", "rule": "r", "model": "m", "provider": "p",
                "attempts": [], "started_at": 1000.0, "finished_at": 1001.0,
            },
            now=1001.0,
        )  # fmt: skip
        store.finish_scan(scan_id, "completed", now=1002.0)
    finally:
        engine.dispose()
    with scan_client([GullibleProvider()]) as client:
        body = client.get(f"/scans/{scan_id}", headers=OWNER).json()
    [result] = body["results"]
    assert result["severity"] is None and result["remediation"] is None
    assert result["status"] == "fail"
