import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response

from redflag_backend.app import create_app
from redflag_backend.llm.types import (
    AuthError,
    BadRequest,
    ModelUnavailable,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    ServerError,
)
from redflag_backend.settings import Settings
from tests.helpers import (
    CHAT,
    OWNER,
    OWNER_TOKEN,
    TEST_DB_URL,
    FakeClock,
    FakeProvider,
    PaidProvider,
    SlowProvider,
    answer,
    chat_body,
    llm_client,
)


def test_chat_rejects_a_missing_or_wrong_owner_token_and_calls_no_provider() -> None:
    provider = FakeProvider("groq")
    client = llm_client([provider])

    missing = client.post("/llm/chat", json=CHAT)
    wrong = client.post("/llm/chat", json=CHAT, headers={"X-Owner-Token": "nope"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert provider.calls == []


def test_chat_is_locked_for_everyone_when_no_owner_token_is_configured() -> None:
    provider = FakeProvider("groq")
    client = llm_client([provider], owner_token=None)

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 401
    assert provider.calls == []


def test_chat_returns_the_first_providers_answer_with_a_full_record() -> None:
    groq = FakeProvider("groq", [answer("Hello there", "llama-x")])
    gemini = FakeProvider("gemini")
    client = llm_client([groq, gemini])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hello there"
    assert body["provider"] == "groq"
    assert body["model"] == "llama-x"
    assert body["cached"] is False
    assert body["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert [(a["provider"], a["model"], a["outcome"]) for a in body["attempts"]] == [
        ("groq", "llama-x", "ok")
    ]
    assert len(groq.calls) == 1
    assert gemini.calls == []


@pytest.mark.parametrize(
    "failure",
    [RateLimited(retry_after=30), ServerError(), ProviderTimeout(), ModelUnavailable()],
    ids=["rate_limited", "server_error", "timeout", "model_unavailable"],
)
def test_chat_falls_back_to_the_next_provider_and_records_both_attempts(
    failure: ProviderError,
) -> None:
    groq = FakeProvider("groq", [failure])
    gemini = FakeProvider("gemini", [answer("from gemini", "gemini-x")])
    client = llm_client([groq, gemini])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "from gemini"
    assert body["provider"] == "gemini"
    assert [(a["provider"], a["outcome"]) for a in body["attempts"]] == [
        ("groq", failure.kind),
        ("gemini", "ok"),
    ]


@pytest.mark.parametrize(
    ("failure", "status", "kind"),
    [(AuthError(), 502, "auth_error"), (BadRequest(), 400, "bad_request")],
    ids=["auth_error", "bad_request"],
)
def test_chat_surfaces_configuration_errors_without_trying_other_providers(
    failure: ProviderError, status: int, kind: str
) -> None:
    groq = FakeProvider("groq", [failure])
    gemini = FakeProvider("gemini")
    client = llm_client([groq, gemini])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == status
    body = response.json()
    assert body["error"] == {"kind": kind, "provider": "groq"}
    assert "answer" not in body
    assert gemini.calls == []


def test_chat_reports_all_providers_failed_and_never_a_success() -> None:
    groq = FakeProvider("groq", [RateLimited()])
    gemini = FakeProvider("gemini", [ServerError()])
    client = llm_client([groq, gemini])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == {"kind": "all_providers_failed", "provider": None}
    assert "answer" not in body
    assert [(a["provider"], a["outcome"]) for a in body["attempts"]] == [
        ("groq", "rate_limited"),
        ("gemini", "server_error"),
    ]


def test_chat_skips_providers_that_have_no_key() -> None:
    groq = FakeProvider("groq", configured=False)
    gemini = FakeProvider("gemini", [answer("from gemini", "gemini-x")])
    client = llm_client([groq, gemini])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "gemini"
    assert [a["provider"] for a in body["attempts"]] == ["gemini"]
    assert groq.calls == []


def test_chat_says_so_when_no_provider_is_configured() -> None:
    client = llm_client([FakeProvider("groq", configured=False)])

    response = client.post("/llm/chat", json=CHAT, headers=OWNER)

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == {"kind": "no_provider_configured", "provider": None}
    assert body["attempts"] == []


@pytest.mark.parametrize(
    ("retry_after", "still_cooling_at", "available_again_at"),
    [(30.0, 10.0, 35.0), (None, 59.0, 61.0)],
    ids=["retry_after_given", "default_cooldown"],
)
def test_a_rate_limited_provider_is_skipped_until_its_cooldown_passes(
    retry_after: float | None, still_cooling_at: float, available_again_at: float
) -> None:
    clock = FakeClock()
    groq = FakeProvider("groq", [RateLimited(retry_after=retry_after), answer("groq", "g")])
    gemini = FakeProvider("gemini", [answer("gemini", "m")])
    client = llm_client([groq, gemini], clock=clock)

    first = client.post("/llm/chat", json=chat_body("one"), headers=OWNER).json()
    clock.now += still_cooling_at
    second = client.post("/llm/chat", json=chat_body("two"), headers=OWNER).json()
    clock.now += available_again_at - still_cooling_at
    third = client.post("/llm/chat", json=chat_body("three"), headers=OWNER).json()

    assert [a["outcome"] for a in first["attempts"]] == ["rate_limited", "ok"]
    assert [(a["provider"], a["outcome"]) for a in second["attempts"]] == [
        ("groq", "cooling_down"),
        ("gemini", "ok"),
    ]
    assert len(groq.calls) == 2  # not called while cooling, called again afterwards
    assert third["provider"] == "groq"


def test_an_identical_repeated_request_is_answered_from_the_cache_without_a_provider_call() -> None:
    groq = FakeProvider("groq", [answer("first answer", "llama-x")])
    client = llm_client([groq])

    first = client.post("/llm/chat", json=chat_body("same question"), headers=OWNER).json()
    second = client.post("/llm/chat", json=chat_body("same question"), headers=OWNER).json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["answer"] == "first answer"
    # A cached answer still says who originally produced it.
    assert (second["provider"], second["model"]) == ("groq", "llama-x")
    assert [a["outcome"] for a in second["attempts"]] == ["cache_hit"]
    assert len(groq.calls) == 1


def test_requests_with_randomness_are_never_cached() -> None:
    groq = FakeProvider("groq", [answer("a random-ish answer", "llama-x")])
    client = llm_client([groq])
    body = {**chat_body("tell me a story"), "temperature": 0.7}

    first = client.post("/llm/chat", json=body, headers=OWNER).json()
    second = client.post("/llm/chat", json=body, headers=OWNER).json()

    assert first["cached"] is False
    assert second["cached"] is False
    assert len(groq.calls) == 2


def test_a_cached_answer_expires_after_its_time_is_up() -> None:
    clock = FakeClock()
    groq = FakeProvider("groq", [answer("fresh", "llama-x")])
    client = llm_client([groq], clock=clock, cache_ttl_seconds=100)

    client.post("/llm/chat", json=chat_body("q"), headers=OWNER)
    clock.now += 99
    still_cached = client.post("/llm/chat", json=chat_body("q"), headers=OWNER).json()
    clock.now += 2
    expired = client.post("/llm/chat", json=chat_body("q"), headers=OWNER).json()

    assert still_cached["cached"] is True
    assert expired["cached"] is False
    assert len(groq.calls) == 2


def test_the_cache_stays_under_its_size_cap_by_dropping_the_oldest_answers() -> None:
    clock = FakeClock()
    groq = FakeProvider("groq", [answer("x" * 100, "m")])
    client = llm_client([groq], clock=clock, cache_max_bytes=400)  # room for two entries

    for question in ("q1", "q2", "q3"):
        client.post("/llm/chat", json=chat_body(question), headers=OWNER)
        clock.now += 1
    newest = client.post("/llm/chat", json=chat_body("q3"), headers=OWNER).json()
    oldest = client.post("/llm/chat", json=chat_body("q1"), headers=OWNER).json()

    assert newest["cached"] is True
    assert oldest["cached"] is False


def _post(client: TestClient, text: str, **extra: object) -> Response:
    response: Response = client.post("/llm/chat", json={**chat_body(text), **extra}, headers=OWNER)
    return response


def test_the_request_cap_stops_a_session_cleanly() -> None:
    groq = FakeProvider("groq")
    client = llm_client([groq])
    session = {"session_id": "s1", "budget": {"max_requests": 2}}

    first = _post(client, "a", **session)
    second = _post(client, "b", **session)
    blocked = _post(client, "c", **session)

    assert first.status_code == second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["error"] == {
        "kind": "budget_exceeded",
        "provider": None,
        "cap": "requests",
    }
    assert "answer" not in blocked.json()
    assert len(groq.calls) == 2


def test_the_token_cap_stops_a_session_once_enough_text_has_been_used() -> None:
    groq = FakeProvider("groq")  # every answer uses 10 + 5 tokens
    client = llm_client([groq])
    session = {"session_id": "s1", "budget": {"max_tokens": 20}}

    results = [_post(client, text, **session) for text in ("a", "b", "c")]

    assert [r.status_code for r in results] == [200, 200, 429]
    assert results[2].json()["error"]["cap"] == "tokens"


def test_the_time_cap_stops_a_session_that_has_run_too_long() -> None:
    clock = FakeClock()
    groq = FakeProvider("groq")
    client = llm_client([groq], clock=clock)
    session = {"session_id": "s1", "budget": {"max_seconds": 60}}

    before = _post(client, "a", **session)
    clock.now += 61
    after = _post(client, "b", **session)

    assert before.status_code == 200
    assert after.status_code == 429
    assert after.json()["error"]["cap"] == "seconds"


def test_cached_answers_do_not_use_up_the_request_budget() -> None:
    groq = FakeProvider("groq")
    client = llm_client([groq])
    session = {"session_id": "s1", "budget": {"max_requests": 1}}

    first = _post(client, "same", **session)
    repeat = _post(client, "same", **session)
    different = _post(client, "new", **session)

    assert first.status_code == 200
    assert repeat.status_code == 200 and repeat.json()["cached"] is True
    assert different.status_code == 429


def test_each_session_has_its_own_budget() -> None:
    groq = FakeProvider("groq")
    client = llm_client([groq])
    tiny = {"max_requests": 1}

    _post(client, "a", session_id="one", budget=tiny)
    exhausted = _post(client, "b", session_id="one", budget=tiny)
    fresh = _post(client, "b", session_id="two", budget=tiny)

    assert exhausted.status_code == 429
    assert fresh.status_code == 200


def test_every_answer_reports_how_much_budget_is_left() -> None:
    client = llm_client([FakeProvider("groq")])

    body = _post(client, "a", session_id="s1", budget={"max_requests": 5}).json()

    assert body["budget"]["requests"] == {"used": 1, "limit": 5}
    assert body["budget"]["tokens"]["used"] == 15


@pytest.mark.parametrize(
    ("cap", "expect_parallel"), [(1, False), (4, True)], ids=["cap_1_serializes", "cap_4_allows"]
)
def test_the_concurrency_cap_makes_extra_calls_wait_their_turn(
    cap: int, expect_parallel: bool
) -> None:
    provider = SlowProvider()
    app = create_app(
        Settings(
            database_url=TEST_DB_URL,
            frontend_origin="http://localhost:3000",
            owner_token=OWNER_TOKEN,
        ),
        providers=[provider],
    )

    async def four_at_once() -> list[Response]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                *[
                    client.post(
                        "/llm/chat",
                        json={
                            **chat_body(f"q{i}"),
                            "session_id": "s",
                            "budget": {"max_concurrency": cap},
                        },
                        headers=OWNER,
                    )
                    for i in range(4)
                ]
            )

    responses = asyncio.run(four_at_once())

    assert [r.status_code for r in responses] == [200, 200, 200, 200]  # none rejected, all served
    assert (provider.max_in_flight > 1) is expect_parallel
    if not expect_parallel:
        assert provider.max_in_flight == 1


def test_every_attempt_is_logged_and_readable_by_the_owner_only() -> None:
    groq = FakeProvider("groq", [RateLimited()])
    gemini = FakeProvider("gemini", [answer("hi", "gemini-x")])
    client = llm_client([groq, gemini])

    _post(client, "same", session_id="s1")  # groq is rate limited, gemini answers
    _post(client, "same", session_id="s1")  # answered from the cache

    calls = client.get("/llm/calls", headers=OWNER).json()["calls"]

    assert [(c["provider"], c["outcome"], c["cached"]) for c in calls] == [
        ("gemini", "cache_hit", True),
        ("gemini", "ok", False),
        ("groq", "rate_limited", False),
    ]
    assert {c["session_id"] for c in calls} == {"s1"}
    assert client.get("/llm/calls").status_code == 401


def test_the_owner_can_pretend_a_provider_is_out_of_quota_for_a_while() -> None:
    clock = FakeClock()
    groq = FakeProvider("groq")
    gemini = FakeProvider("gemini", [answer("from gemini", "gemini-x")])
    client = llm_client([groq, gemini], clock=clock)

    pretend = client.post("/llm/test/fail", json={"provider": "groq", "seconds": 60}, headers=OWNER)
    during = _post(client, "one").json()
    clock.now += 61
    after = _post(client, "two").json()

    assert pretend.status_code == 200
    assert [(a["provider"], a["outcome"]) for a in during["attempts"]] == [
        ("groq", "simulated_rate_limit"),  # clearly labeled, never mistaken for a real outage
        ("gemini", "ok"),
    ]
    assert after["provider"] == "groq"
    assert len(groq.calls) == 1  # the pretend failure never reached the real provider


def test_pretending_about_an_unknown_provider_is_rejected() -> None:
    client = llm_client([FakeProvider("groq")])

    response = client.post("/llm/test/fail", json={"provider": "nope", "seconds": 5}, headers=OWNER)

    assert response.status_code == 404


def test_the_owner_can_clear_the_cache() -> None:
    groq = FakeProvider("groq")
    client = llm_client([groq])

    _post(client, "same")
    cleared = client.post("/llm/test/clear-cache", headers=OWNER)
    again = _post(client, "same").json()

    assert cleared.status_code == 200
    assert again["cached"] is False
    assert len(groq.calls) == 2


def test_the_test_tools_are_locked_to_the_owner() -> None:
    client = llm_client([FakeProvider("groq")])

    assert client.post("/llm/test/fail", json={"provider": "groq", "seconds": 5}).status_code == 401
    assert client.post("/llm/test/clear-cache").status_code == 401
    assert client.get("/llm/providers").status_code == 401


def test_provider_status_shows_who_is_configured_and_who_is_cooling_down_without_keys() -> None:
    clock = FakeClock()
    groq = FakeProvider("groq", [RateLimited(retry_after=30)])
    gemini = FakeProvider("gemini")
    unkeyed = FakeProvider("openrouter", configured=False)
    client = llm_client([groq, gemini, unkeyed], clock=clock)
    _post(client, "trip the rate limit")
    clock.now += 10

    providers = client.get("/llm/providers", headers=OWNER).json()["providers"]

    assert providers == [
        {"name": "groq", "configured": True, "cooling_down": True, "cooldown_seconds_left": 20.0},
        {"name": "gemini", "configured": True, "cooling_down": False, "cooldown_seconds_left": 0},
        {
            "name": "openrouter",
            "configured": False,
            "cooling_down": False,
            "cooldown_seconds_left": 0,
        },
    ]


def test_paid_models_are_never_used_by_default() -> None:
    paid = PaidProvider()
    client = llm_client([paid])

    response = _post(client, "hello")

    assert response.status_code == 503  # nothing free could answer, and nothing paid was allowed
    assert paid.calls[0].allow_paid is False


def test_paid_use_must_be_switched_on_and_is_then_clearly_labeled() -> None:
    paid = PaidProvider(cost=0.01)
    client = llm_client([paid], allow_paid_models=True, paid_spend_cap_usd=1.0)

    body = _post(client, "hello").json()
    logged = client.get("/llm/calls", headers=OWNER).json()["calls"][0]

    assert body["paid"] is True
    assert body["estimated_cost_usd"] == 0.01
    assert logged["paid"] is True


def test_switching_paid_on_without_a_spending_cap_still_spends_nothing() -> None:
    paid = PaidProvider()
    client = llm_client([paid], allow_paid_models=True)  # cap defaults to zero

    response = _post(client, "hello")

    assert response.status_code == 503
    assert paid.calls[0].allow_paid is False


def test_free_answers_are_not_labeled_paid() -> None:
    body = _post(llm_client([FakeProvider("groq")]), "hello").json()

    assert body["paid"] is False
    assert body["estimated_cost_usd"] == 0.0


def test_the_paid_cap_stops_spending_once_it_is_reached() -> None:
    paid = PaidProvider(cost=0.01)
    client = llm_client([paid], allow_paid_models=True, paid_spend_cap_usd=0.025)

    statuses = [_post(client, f"q{i}").status_code for i in range(4)]

    assert statuses == [200, 200, 200, 503]  # 0.01, 0.02, 0.03 (over the cap), then refused
    assert paid.calls[3].allow_paid is False


def test_the_paid_cap_still_holds_after_a_restart() -> None:
    before_restart = llm_client(
        [PaidProvider(cost=0.01)], allow_paid_models=True, paid_spend_cap_usd=0.015
    )
    assert _post(before_restart, "a").status_code == 200
    assert _post(before_restart, "b").status_code == 200  # total 0.02, past the cap

    paid_after = PaidProvider(cost=0.01)
    after_restart = llm_client(  # a new app on the same database
        [paid_after], allow_paid_models=True, paid_spend_cap_usd=0.015
    )
    response = _post(after_restart, "c")

    assert response.status_code == 503
    assert paid_after.calls[0].allow_paid is False


def test_an_unexpected_provider_crash_never_leaks_its_message_or_counts_as_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-SECRET-123"
    groq = FakeProvider("groq", [RuntimeError(f"boom with {secret}")])
    gemini = FakeProvider("gemini", [answer("from gemini", "gemini-x")])
    client = llm_client([groq, gemini])

    recovered = _post(client, "one")
    only_crash = llm_client([FakeProvider("groq", [RuntimeError(secret)])])
    failed = _post(only_crash, "two")
    log_text = client.get("/llm/calls", headers=OWNER).text

    assert recovered.status_code == 200
    assert [a["outcome"] for a in recovered.json()["attempts"]] == ["unexpected_error", "ok"]
    assert failed.status_code == 503
    assert failed.json()["error"]["kind"] == "all_providers_failed"
    for place in (recovered.text, failed.text, log_text, caplog.text):
        assert secret not in place
