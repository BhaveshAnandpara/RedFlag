"""Provider adapters against sample HTTP replies. No live calls, ever, in these tests."""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from redflag_backend.llm.providers import GeminiProvider, GroqProvider, OpenRouterProvider
from redflag_backend.llm.types import (
    AuthError,
    BadRequest,
    ContentBlocked,
    LLMAnswer,
    LLMRequest,
    Message,
    ModelUnavailable,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    ServerError,
)

REQUEST = LLMRequest(
    messages=(Message("system", "be brief"), Message("user", "hello")),
    temperature=0.0,
    max_output_tokens=64,
)
KEY = "gsk-TEST-KEY"


Handler = Callable[[httpx.Request], httpx.Response]


def groq(handler: Handler) -> GroqProvider:
    return GroqProvider(api_key=KEY, model="llama-x", transport=httpx.MockTransport(handler))


def ask(provider: GroqProvider, request: LLMRequest = REQUEST) -> LLMAnswer:
    return asyncio.run(provider.complete(request))


def chat_reply(content: str | None = "Hi!", **extra: object) -> dict[str, object]:
    return {
        "model": "llama-x",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        **extra,
    }


def test_groq_sends_an_openai_style_request_and_parses_the_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=chat_reply("Hi!"))

    result = ask(groq(handler))

    assert result == LLMAnswer(text="Hi!", model="llama-x", input_tokens=7, output_tokens=3)
    request = seen[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "model": "llama-x",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ],
        "temperature": 0.0,
        "max_completion_tokens": 64,
    }


@pytest.mark.parametrize(
    ("status", "headers", "expected", "retry_after"),
    [
        (429, {"retry-after": "7"}, RateLimited, 7.0),
        (429, {}, RateLimited, None),
        (500, {}, ServerError, None),
        (502, {}, ServerError, None),
        (503, {}, ServerError, None),
        (408, {}, ProviderTimeout, None),
        (504, {}, ProviderTimeout, None),
        (401, {}, AuthError, None),
        (403, {}, AuthError, None),
        (400, {}, BadRequest, None),
        (404, {}, ModelUnavailable, None),
        (402, {}, ModelUnavailable, None),
    ],
)
def test_groq_maps_http_errors_to_typed_errors_that_never_echo_the_reply_body(
    status: int, headers: dict[str, str], expected: type[ProviderError], retry_after: float | None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # A provider's error text could echo a key back, so it must never be passed along.
        return httpx.Response(status, headers=headers, json={"error": {"message": f"{KEY} bad"}})

    with pytest.raises(expected) as caught:
        ask(groq(handler))

    if isinstance(caught.value, RateLimited):
        assert caught.value.retry_after == retry_after
    assert KEY not in str(caught.value)
    assert KEY not in repr(caught.value)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (httpx.ReadTimeout("slow"), ProviderTimeout),
        (httpx.ConnectTimeout("slow"), ProviderTimeout),
        (httpx.ConnectError("unreachable"), ServerError),
    ],
    ids=["read_timeout", "connect_timeout", "connect_error"],
)
def test_groq_maps_network_trouble_to_typed_errors(
    raised: Exception, expected: type[ProviderError]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    with pytest.raises(expected):
        ask(groq(handler))


@pytest.mark.parametrize(
    "reply",
    [{"choices": []}, chat_reply(content=None), chat_reply(content=""), {"unexpected": True}],
    ids=["no_choices", "null_content", "empty_content", "wrong_shape"],
)
def test_groq_never_treats_an_empty_or_odd_reply_as_a_successful_answer(
    reply: dict[str, object],
) -> None:
    with pytest.raises(ServerError):
        ask(groq(lambda request: httpx.Response(200, json=reply)))


def test_a_provider_without_a_key_says_it_is_not_configured() -> None:
    assert GroqProvider(api_key=None, model="m").configured is False
    assert GroqProvider(api_key="", model="m").configured is False
    assert GroqProvider(api_key=KEY, model="m").configured is True


def test_the_key_never_appears_when_a_provider_is_printed() -> None:
    provider = GroqProvider(api_key=KEY, model="m")

    assert KEY not in repr(provider)
    assert KEY not in str(provider.__dict__.get("name", ""))


# ---------- OpenRouter ----------

OR_KEY = "sk-or-TEST-KEY"


def or_provider(
    handler: Handler,
    free: tuple[str, ...] = ("free/one:free", "free/two:free"),
    paid: str | None = None,
) -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key=OR_KEY,
        free_models=free,
        paid_model=paid,
        transport=httpx.MockTransport(handler),
    )


def or_ask(provider: OpenRouterProvider, allow_paid: bool = False) -> LLMAnswer:
    request = LLMRequest(messages=REQUEST.messages, allow_paid=allow_paid)
    return asyncio.run(provider.complete(request))


def reply_for(model: str, cost: float | None = None) -> httpx.Response:
    usage: dict[str, object] = {"prompt_tokens": 7, "completion_tokens": 3}
    if cost is not None:
        usage["cost"] = cost
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": f"from {model}"}}],
            "usage": usage,
        },
    )


def test_openrouter_sends_the_expected_request_and_parses_the_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply_for("free/one:free")

    result = or_ask(or_provider(handler))

    assert result == LLMAnswer("from free/one:free", "free/one:free", 7, 3)
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {OR_KEY}"
    body = json.loads(seen[0].content)
    assert body["model"] == "free/one:free"
    assert body["max_tokens"] == 512  # OpenRouter's name for the cap
    assert "max_completion_tokens" not in body


def test_openrouter_moves_to_the_next_free_model_when_one_is_gone_or_down() -> None:
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        if model == "free/one:free":
            return httpx.Response(404, json={"error": {"code": 404, "message": "no such model"}})
        return reply_for(model)

    result = or_ask(or_provider(handler))

    assert tried == ["free/one:free", "free/two:free"]
    assert result.model == "free/two:free"


def test_openrouter_tries_the_next_free_model_when_one_is_rate_limited_upstream() -> None:
    # Seen live: one free model was rate limited at its upstream provider while the next
    # free model answered. A free model's 429 says nothing about the others.
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        if model == "free/one:free":
            return httpx.Response(429, json={"error": {"code": 429, "message": "upstream"}})
        return reply_for(model)

    result = or_ask(or_provider(handler))

    assert tried == ["free/one:free", "free/two:free"]
    assert result.model == "free/two:free"


def test_openrouter_reports_a_rate_limit_only_when_every_free_model_is_rate_limited() -> None:
    tried: list[str] = []
    waits = {"free/one:free": "12", "free/two:free": "30"}

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        return httpx.Response(
            429, headers={"retry-after": waits[model]}, json={"error": {"code": 429}}
        )

    with pytest.raises(RateLimited) as caught:
        or_ask(or_provider(handler))

    assert tried == ["free/one:free", "free/two:free"]
    assert caught.value.retry_after == 30.0  # the longest wait, so the router skips us long enough


def test_openrouter_reads_an_error_hidden_inside_a_200_reply() -> None:
    def rate_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 429, "message": "slow down"}})

    with pytest.raises(RateLimited):
        or_ask(or_provider(rate_limited))

    calls: list[str] = []

    def provider_down_then_ok(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if len(calls) == 1:
            return httpx.Response(200, json={"error": {"code": 502, "message": "upstream down"}})
        return reply_for(model)

    assert or_ask(or_provider(provider_down_then_ok)).model == "free/two:free"


def test_openrouter_never_uses_a_paid_model_unless_the_router_allows_it() -> None:
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        return httpx.Response(429, json={"error": {"code": 429}})

    with pytest.raises(RateLimited):
        or_ask(or_provider(handler, paid="paid/model"), allow_paid=False)

    assert "paid/model" not in tried


def test_openrouter_falls_back_to_its_paid_model_only_when_allowed_and_reports_the_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model.endswith(":free"):
            return httpx.Response(429, json={"error": {"code": 429}})
        return reply_for(model, cost=0.0123)

    result = or_ask(or_provider(handler, paid="paid/model"), allow_paid=True)

    assert result.model == "paid/model"
    assert result.estimated_cost_usd == 0.0123


def test_openrouter_with_only_a_paid_model_cannot_help_when_paid_is_not_allowed() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return reply_for("paid/model")

    with pytest.raises(ModelUnavailable):
        or_ask(or_provider(handler, free=(), paid="paid/model"), allow_paid=False)

    assert sent == []  # nothing was even sent


def test_openrouter_out_of_credits_on_the_paid_model_cannot_help_and_leaks_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model.endswith(":free"):
            return httpx.Response(429, json={"error": {"code": 429}})
        return httpx.Response(402, json={"error": {"message": f"{OR_KEY} no credits"}})

    with pytest.raises(ModelUnavailable) as caught:
        or_ask(or_provider(handler, paid="paid/model"), allow_paid=True)

    assert OR_KEY not in str(caught.value) + repr(caught.value)


def test_openrouter_without_any_model_configured_cannot_help() -> None:
    with pytest.raises(ModelUnavailable):
        or_ask(or_provider(lambda request: reply_for("x"), free=(), paid=None))


def test_openrouter_reports_not_configured_without_a_key_and_hides_it_when_printed() -> None:
    unkeyed = OpenRouterProvider(api_key=None, free_models=("a:free",), paid_model=None)
    keyed = OpenRouterProvider(api_key=OR_KEY, free_models=("a:free",), paid_model=None)

    assert unkeyed.configured is False
    assert keyed.configured is True
    assert OR_KEY not in repr(keyed)


# ---------- Gemini ----------

G_KEY = "AIza-TEST-KEY"


def gemini(handler: Handler) -> GeminiProvider:
    return GeminiProvider(
        api_key=G_KEY,
        model="gemini-x",
        transport=httpx.MockTransport(handler),
    )


def gemini_ask(provider: GeminiProvider, request: LLMRequest = REQUEST) -> LLMAnswer:
    return asyncio.run(provider.complete(request))


def gemini_reply(text: str = "Hi!", **usage: int) -> dict[str, object]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, **usage},
        "modelVersion": "gemini-x-001",
    }


def test_gemini_sends_its_own_request_shape_with_the_key_in_a_header_not_the_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=gemini_reply("Hi!"))

    result = gemini_ask(gemini(handler))

    assert result == LLMAnswer("Hi!", "gemini-x-001", 7, 3)
    request = seen[0]
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    )
    assert request.headers["x-goog-api-key"] == G_KEY
    assert G_KEY not in str(request.url)  # URLs end up in logs; keys must not
    assert json.loads(request.content) == {
        "systemInstruction": {"parts": [{"text": "be brief"}]},
        "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 64},
    }


def test_gemini_names_the_assistant_role_model_and_joins_system_messages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=gemini_reply())

    request = LLMRequest(
        messages=(
            Message("system", "rule one"),
            Message("system", "rule two"),
            Message("user", "hi"),
            Message("assistant", "hello"),
            Message("user", "again"),
        )
    )
    gemini_ask(gemini(handler), request)

    body = json.loads(seen[0].content)
    assert body["systemInstruction"] == {"parts": [{"text": "rule one\n\nrule two"}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]


def test_gemini_counts_thinking_tokens_as_output_because_they_are_billed() -> None:
    handler = lambda request: httpx.Response(200, json=gemini_reply(thoughtsTokenCount=40))  # noqa: E731

    assert gemini_ask(gemini(handler)).output_tokens == 43


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, RateLimited),
        (503, {"error": {"status": "UNAVAILABLE"}}, ServerError),
        (500, {"error": {"status": "INTERNAL"}}, ServerError),
        (504, {"error": {"status": "DEADLINE_EXCEEDED"}}, ProviderTimeout),
        (403, {"error": {"status": "PERMISSION_DENIED"}}, AuthError),
        (404, {"error": {"status": "NOT_FOUND"}}, ModelUnavailable),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, BadRequest),
        # Gemini reports a bad key as a 400, so the reason has to be read.
        (
            400,
            {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}},
            AuthError,
        ),
    ],
    ids=["429", "503", "500", "504", "403", "404", "400", "400_bad_key"],
)
def test_gemini_maps_errors_to_typed_errors_that_never_echo_the_reply_body(
    status: int, body: dict[str, object], expected: type[ProviderError]
) -> None:
    body = {**body, "echo": f"{G_KEY} leaked"}

    with pytest.raises(expected) as caught:
        gemini_ask(gemini(lambda request: httpx.Response(status, json=body)))

    assert G_KEY not in str(caught.value) + repr(caught.value)


def test_gemini_uses_the_retry_hint_in_a_rate_limit_reply_when_there_is_one() -> None:
    body = {
        "error": {
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}],
        }
    }

    with pytest.raises(RateLimited) as caught:
        gemini_ask(gemini(lambda request: httpx.Response(429, json=body)))

    assert caught.value.retry_after == 37.0


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, ContentBlocked),
        ({"candidates": [{"finishReason": "SAFETY"}]}, ContentBlocked),
        ({"candidates": [{"finishReason": "PROHIBITED_CONTENT"}]}, ContentBlocked),
        ({"candidates": []}, ServerError),
        ({"unexpected": True}, ServerError),
        (gemini_reply(text=""), ServerError),
        ({"candidates": [{"content": {"parts": [{}]}, "finishReason": "STOP"}]}, ServerError),
    ],
    ids=[
        "prompt_blocked",
        "answer_blocked",
        "prohibited",
        "no_candidates",
        "wrong_shape",
        "empty_text",
        "part_without_text",
    ],
)
def test_gemini_never_treats_a_blocked_or_empty_reply_as_a_successful_answer(
    reply: dict[str, object], expected: type[ProviderError]
) -> None:
    with pytest.raises(expected):
        gemini_ask(gemini(lambda request: httpx.Response(200, json=reply)))


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(httpx.ReadTimeout("slow"), ProviderTimeout), (httpx.ConnectError("down"), ServerError)],
    ids=["timeout", "connect_error"],
)
def test_gemini_maps_network_trouble_to_typed_errors(
    raised: Exception, expected: type[ProviderError]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    with pytest.raises(expected):
        gemini_ask(gemini(handler))


def test_gemini_reports_not_configured_without_a_key_and_hides_it_when_printed() -> None:
    assert GeminiProvider(api_key=None, model="m").configured is False
    assert GeminiProvider(api_key="", model="m").configured is False
    keyed = GeminiProvider(api_key=G_KEY, model="m")
    assert keyed.configured is True
    assert G_KEY not in repr(keyed)
