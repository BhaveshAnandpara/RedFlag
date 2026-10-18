import pytest

from redflag_backend.llm.types import (
    AuthError,
    BadRequest,
    ModelUnavailable,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    ServerError,
)
from tests.helpers import CHAT, OWNER, FakeClock, FakeProvider, answer, chat_body, llm_client


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
