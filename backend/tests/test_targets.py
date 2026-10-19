"""The HTTP target adapter: send a prompt to someone's chat endpoint and read the reply.

The only faked parts are the outside server (a stand-in at the HTTP boundary) and name lookup
(a table). The adapter never raises, never leaks the key, and never calls an address it should
not: every failure is an error result with its cause, never a pass.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from redflag_backend.targets.http_target import (
    ConnectionCheck,
    EndpointConfig,
    HttpTarget,
    TargetResult,
)

KEY = "sekret-key-value-123"
PUBLIC_IP = "93.184.216.34"


class StandIn:
    """A stand-in for the user's server. Keeps every request it was sent."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler or (lambda request: openai_reply("hello from the bot"))

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(request)

        return httpx.MockTransport(handle)


def openai_reply(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": text}}]})


def resolver(
    table: dict[str, list[str]] | None = None,
) -> Callable[[str, int], Awaitable[list[str]]]:
    names = table or {}

    async def resolve(host: str, port: int) -> list[str]:
        return names.get(host, [PUBLIC_IP])

    return resolve


def config(**changes: Any) -> EndpointConfig:
    values: dict[str, Any] = {"url": "https://bot.example/v1/chat", "key": KEY}
    values.update(changes)
    return EndpointConfig(**values)


def target(
    stand_in: StandIn | None = None,
    names: dict[str, list[str]] | None = None,
    **changes: Any,
) -> tuple[HttpTarget, StandIn]:
    server = stand_in or StandIn()
    options = {
        k: changes.pop(k) for k in ("blocked_hosts", "timeout", "max_reply_bytes") if k in changes
    }
    return (
        HttpTarget(
            config(**changes), resolver=resolver(names), transport=server.transport(), **options
        ),
        server,
    )


def send(http_target: HttpTarget, prompt: str = "hi") -> TargetResult:
    return asyncio.run(http_target.send(prompt))


# --- the OpenAI-compatible format ----------------------------------------------------------


def test_the_default_format_posts_a_chat_body_and_returns_the_reply_text() -> None:
    http_target, server = target(model="my-model")
    result = send(http_target, "What is my balance?")
    assert result.status == "ok" and result.reply == "hello from the bot"
    body = json.loads(server.requests[0].content)
    assert body["messages"] == [{"role": "user", "content": "What is my balance?"}]
    assert body["model"] == "my-model"
    assert server.requests[0].method == "POST"


def test_the_key_goes_only_in_its_header() -> None:
    http_target, server = target()
    send(http_target)
    request = server.requests[0]
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(request.url) and KEY.encode() not in request.content


def test_the_header_name_and_prefix_can_be_changed() -> None:
    http_target, server = target(header_name="X-Api-Key", header_prefix="")
    send(http_target)
    assert server.requests[0].headers["x-api-key"] == KEY
    assert "authorization" not in server.requests[0].headers


def test_no_key_means_no_auth_header() -> None:
    http_target, server = target(key=None)
    send(http_target)
    assert "authorization" not in server.requests[0].headers


def test_the_key_never_appears_in_an_error_or_a_repr() -> None:
    server = StandIn(lambda request: httpx.Response(500, text=f"boom {KEY}"))
    http_target, _ = target(server)
    result = send(http_target)
    assert result.status == "error" and KEY not in result.error
    assert KEY not in repr(config()) and KEY not in repr(result)


def test_a_key_echoed_in_the_reply_is_replaced_before_anyone_sees_it() -> None:
    server = StandIn(lambda request: openai_reply(f"your key is {KEY}, enjoy"))
    http_target, _ = target(server)
    result = send(http_target)
    assert result.status == "ok"
    assert KEY not in result.reply and "[key removed]" in result.reply


# --- the custom format ---------------------------------------------------------------------


def test_a_custom_template_escapes_the_prompt_so_it_cannot_break_the_json() -> None:
    server = StandIn(lambda request: httpx.Response(200, json={"data": {"answer": "ok"}}))
    http_target, _ = target(
        server,
        format="custom",
        request_template='{"question": "{{prompt}}", "session": "abc"}',
        reply_path="data.answer",
    )
    nasty = 'He said "stop"\nthen {{prompt}} and a \\ backslash, } {'
    result = send(http_target, nasty)
    body = json.loads(server.requests[0].content)
    assert body == {"question": nasty, "session": "abc"}
    assert result.reply == "ok"


def test_a_reply_path_can_use_array_positions() -> None:
    server = StandIn(lambda request: openai_reply("deep"))
    http_target, _ = target(server, format="custom", request_template='{"q": "{{prompt}}"}',
                            reply_path="choices.0.message.content")  # fmt: skip
    assert send(http_target).reply == "deep"


def test_a_template_that_is_not_json_or_has_no_placeholder_is_an_error_not_a_call() -> None:
    for template in ('{"q": "no placeholder"}', "{not json {{prompt}}"):
        http_target, server = target(format="custom", request_template=template, reply_path="a")
        result = send(http_target)
        assert result.status == "error" and "template" in result.error
        assert server.requests == []


# --- every failure is an error result with its cause --------------------------------------


@pytest.mark.parametrize(
    ("response", "words"),
    [
        (httpx.Response(200, text="<html>not json</html>"), "not json"),
        (httpx.Response(200, json={"something": "else"}), "path"),
        (httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}), "empty"),
        (httpx.Response(200, json={"choices": [{"message": {"content": 5}}]}), "text"),
        (
            httpx.Response(200, text="data: hi\n\n", headers={"content-type": "text/event-stream"}),
            "stream",
        ),
        (httpx.Response(401, json={"error": "no"}), "401"),
        (httpx.Response(500, text="oops"), "500"),
        (httpx.Response(302, headers={"location": "http://10.0.0.1/"}), "redirect"),
    ],
)
def test_bad_replies_and_statuses_are_errors_with_the_cause(
    response: httpx.Response, words: str
) -> None:
    http_target, server = target(StandIn(lambda request: response))
    result = send(http_target)
    assert result.status == "error" and result.reply == ""
    assert words in result.error.lower()
    assert len(server.requests) == 1  # a redirect is reported, never followed


def test_a_reply_over_the_size_cap_is_an_error() -> None:
    big = StandIn(lambda request: openai_reply("x" * 5000))
    http_target, _ = target(big, max_reply_bytes=1000)
    result = send(http_target)
    assert result.status == "error" and "too large" in result.error


@pytest.mark.parametrize(
    ("raised", "words"),
    [
        (httpx.ReadTimeout("slow"), "timed out"),
        (httpx.ConnectError("refused"), "connect"),
        (httpx.RemoteProtocolError("bad"), "protocol"),
    ],
)
def test_timeouts_and_connection_failures_are_errors_never_exceptions(
    raised: Exception, words: str
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise raised

    http_target, _ = target(StandIn(fail))
    result = send(http_target)
    assert result.status == "error" and words in result.error.lower()


# --- which addresses may be called ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://127.1.2.3:8080/x",
        "http://[::1]/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.9/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://[fe80::1]/x",
        "http://100.64.0.1/x",
        "ftp://bot.example/x",
        "file:///etc/passwd",
        "https://user:pass@bot.example/x",
        "not a url",
    ],
)
def test_addresses_that_point_inside_or_are_not_web_addresses_are_refused(url: str) -> None:
    http_target, server = target(url=url)
    result = send(http_target)
    assert result.status == "error" and "not allowed" in result.error
    assert server.requests == []


def test_a_name_that_resolves_to_a_private_address_is_refused() -> None:
    http_target, server = target(names={"bot.example": ["10.1.2.3"]})
    result = send(http_target)
    assert result.status == "error" and "not allowed" in result.error
    assert server.requests == []


def test_a_name_with_any_private_answer_among_public_ones_is_refused() -> None:
    http_target, server = target(names={"bot.example": [PUBLIC_IP, "127.0.0.1"]})
    assert send(http_target).status == "error"
    assert server.requests == []


def test_a_name_that_does_not_resolve_is_an_error() -> None:
    http_target, _ = target(names={"bot.example": []})
    result = send(http_target)
    assert result.status == "error" and "resolve" in result.error


@pytest.mark.parametrize(
    "url",
    ["https://bot.example/x", "http://bot.example/x", "https://bot.example:8443/x"],
)
def test_public_addresses_are_allowed_on_https_and_http_and_any_port(url: str) -> None:
    http_target, server = target(url=url)
    assert send(http_target).status == "ok"
    assert len(server.requests) == 1


def test_a_public_ip_written_in_the_url_is_allowed() -> None:
    http_target, _ = target(url=f"https://{PUBLIC_IP}/x")
    assert send(http_target).status == "ok"


def test_redflags_own_address_is_refused() -> None:
    http_target, server = target(
        url="https://redflag-api.example/v1", blocked_hosts=frozenset({"redflag-api.example"})
    )
    result = send(http_target)
    assert result.status == "error" and "not allowed" in result.error
    assert server.requests == []


def test_the_call_goes_to_the_checked_address_with_the_original_name() -> None:
    http_target, server = target(names={"bot.example": ["93.184.216.34"]})
    send(http_target)
    request = server.requests[0]
    assert request.url.host == "93.184.216.34"  # not looked up a second time
    assert request.headers["host"] == "bot.example"
    assert request.extensions["sni_hostname"] == "bot.example"


# --- Test connection -----------------------------------------------------------------------


def check(http_target: HttpTarget) -> ConnectionCheck:
    return asyncio.run(http_target.test_connection())


def test_test_connection_sends_one_harmless_message_and_shows_what_it_saw() -> None:
    http_target, server = target()
    seen = check(http_target)
    assert len(server.requests) == 1
    body = json.loads(server.requests[0].content)
    assert body["messages"][0]["content"] == "Hello"
    assert seen.status == "ok" and seen.http_status == 200
    assert seen.parsed_reply == "hello from the bot"
    assert "choices" in seen.raw_reply


def test_test_connection_trims_a_long_raw_reply_and_never_shows_the_key() -> None:
    server = StandIn(lambda request: httpx.Response(200, text=("a" * 3000) + KEY))
    http_target, _ = target(server)
    seen = check(http_target)
    assert len(seen.raw_reply) <= 500 and KEY not in seen.raw_reply


def test_test_connection_reports_a_failure_instead_of_raising() -> None:
    http_target, _ = target(StandIn(lambda request: httpx.Response(401, text="nope")))
    seen = check(http_target)
    assert seen.status == "error" and seen.http_status == 401 and "401" in seen.error
    assert seen.raw_reply == "nope"
