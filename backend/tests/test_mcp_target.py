"""The MCP target adapter: handshake, list tools, call a tool, over HTTP.

The only faked parts are the outside server (a stand-in at the HTTP boundary) and name lookup (a
table). The adapter never raises, never leaks the key, and never calls an address it should not.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx

from redflag_backend.targets.mcp_target import CallResult, McpConfig, McpTarget, ToolsResult
from tests.test_targets import KEY, StandIn, resolver

SESSION = "session-abc"


def rpc(request: httpx.Request) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(request.content)
    return body


def result(request: httpx.Request, payload: dict[str, Any], **headers: str) -> httpx.Response:
    message = {"jsonrpc": "2.0", "id": rpc(request).get("id"), "result": payload}
    return httpx.Response(200, json=message, headers=headers)


def tool(name: str = "read_file", **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Read a file.",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        **extra,
    }


def server(
    tools: list[dict[str, Any]] | None = None,
    call: Callable[[httpx.Request], httpx.Response] | None = None,
) -> StandIn:
    listed = tools if tools is not None else [tool()]

    def handle(request: httpx.Request) -> httpx.Response:
        method = rpc(request)["method"]
        if method == "initialize":
            return result(
                request,
                {"protocolVersion": "2025-03-26", "serverInfo": {"name": "files", "version": "2"}},
                **{"Mcp-Session-Id": SESSION},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return result(request, {"tools": listed})
        if method == "tools/call" and call:
            return call(request)
        return result(request, {"content": [{"type": "text", "text": "ok"}]})

    return StandIn(handle)


def mcp(stand_in: StandIn | None = None, **changes: Any) -> tuple[McpTarget, StandIn]:
    fake = stand_in or server()
    options = {k: changes.pop(k) for k in ("blocked_hosts", "max_reply_bytes") if k in changes}
    values: dict[str, Any] = {"url": "https://mcp.example/mcp", "key": KEY}
    values.update(changes)
    return (
        McpTarget(McpConfig(**values), resolver=resolver(), transport=fake.transport(), **options),
        fake,
    )


def tools_of(target: McpTarget) -> ToolsResult:
    return asyncio.run(target.list_tools())


def call(target: McpTarget, name: str = "read_file", **arguments: Any) -> CallResult:
    return asyncio.run(target.call_tool(name, arguments))


def test_it_does_the_handshake_then_lists_the_tools_and_names_the_server() -> None:
    target, fake = mcp()
    found = tools_of(target)
    assert found.status == "ok"
    assert [t.name for t in found.tools] == ["read_file"]
    assert (found.server_name, found.server_version) == ("files", "2")
    assert [rpc(r)["method"] for r in fake.requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]


def test_the_session_id_the_server_gave_is_sent_on_every_later_request() -> None:
    target, fake = mcp()
    tools_of(target)
    assert "mcp-session-id" not in fake.requests[0].headers
    assert all(r.headers["mcp-session-id"] == SESSION for r in fake.requests[1:])


def test_a_second_call_does_not_do_the_handshake_again() -> None:
    target, fake = mcp()
    tools_of(target)
    call(target, path="a.txt")
    assert [rpc(r)["method"] for r in fake.requests].count("initialize") == 1


def test_the_key_goes_in_its_header_only_and_the_call_goes_to_the_checked_address() -> None:
    target, fake = mcp(header_name="X-Api-Key", header_prefix="")
    tools_of(target)
    for request in fake.requests:
        assert request.headers["x-api-key"] == KEY
        assert request.headers["host"] == "mcp.example"
        assert request.url.host == "93.184.216.34"
        assert KEY not in request.content.decode()


def test_it_follows_the_pages_of_a_long_tool_list() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        message = rpc(request)
        if message["method"] == "initialize":
            return result(request, {"serverInfo": {}})
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        if message["params"].get("cursor") == "p2":
            return result(request, {"tools": [tool("b")]})
        return result(request, {"tools": [tool("a")], "nextCursor": "p2"})

    target, _ = mcp(StandIn(handle))
    assert [t.name for t in tools_of(target).tools] == ["a", "b"]


def test_it_reads_an_answer_sent_as_an_event_stream() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        message = rpc(request)
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        payload = {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [tool()]}}
        if message["method"] == "initialize":
            payload["result"] = {"serverInfo": {"name": "s"}}
        body = f"event: message\ndata: {json.dumps(payload)}\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    target, _ = mcp(StandIn(handle))
    assert [t.name for t in tools_of(target).tools] == ["read_file"]


def test_the_read_only_hint_is_passed_on_only_when_the_server_says_so() -> None:
    target, _ = mcp(
        server(
            [
                tool("safe", annotations={"readOnlyHint": True}),
                tool("unknown"),
                tool("odd", annotations={"readOnlyHint": "yes"}),
            ]
        )
    )
    hints = {t.name: t.read_only_hint for t in tools_of(target).tools}
    assert hints == {"safe": True, "unknown": None, "odd": None}


def test_calling_a_tool_sends_its_arguments_and_returns_the_text() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return result(request, {"content": [{"type": "text", "text": "file says hi"}]})

    target, fake = mcp(server(call=handle))
    answer = call(target, path="notes.txt")
    assert answer == CallResult("ok", text="file says hi", tool_error=False)
    sent = rpc(fake.requests[-1])
    assert sent["params"] == {"name": "read_file", "arguments": {"path": "notes.txt"}}


def test_a_tool_that_reports_an_error_is_an_answer_marked_as_an_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return result(request, {"isError": True, "content": [{"type": "text", "text": "no"}]})

    answer = call(mcp(server(call=handle))[0])
    assert answer.status == "ok" and answer.tool_error and answer.text == "no"


def test_a_protocol_error_for_a_call_is_an_answer_not_a_failure_of_the_run() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        error = {"code": -32602, "message": "Invalid params"}
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": rpc(request)["id"], "error": error}
        )

    answer = call(mcp(server(call=handle))[0])
    assert answer.status == "ok" and answer.tool_error and "Invalid params" in answer.text


def test_a_server_that_echoes_the_key_has_it_removed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return result(request, {"content": [{"type": "text", "text": f"your key is {KEY}"}]})

    answer = call(mcp(server(call=handle))[0])
    assert KEY not in answer.text and "[key removed]" in answer.text


def test_failures_are_error_results_with_a_cause() -> None:
    down, _ = mcp(StandIn(lambda request: httpx.Response(500)))
    assert "status 500" in tools_of(down).error
    odd, _ = mcp(StandIn(lambda request: httpx.Response(200, text="<html>hi</html>")))
    assert tools_of(odd).status == "error"
    redirect, _ = mcp(
        StandIn(lambda request: httpx.Response(302, headers={"location": "http://x"}))
    )
    assert "redirect" in tools_of(redirect).error


def test_an_oversized_reply_is_refused() -> None:
    big, _ = mcp(
        StandIn(lambda request: httpx.Response(200, text="x" * 5000)), max_reply_bytes=1000
    )
    assert "too large" in tools_of(big).error


def test_private_and_own_addresses_are_never_called() -> None:
    for url in ("http://127.0.0.1/mcp", "http://10.0.0.5/mcp", "ftp://mcp.example/mcp"):
        target, fake = mcp(url=url)
        found = tools_of(target)
        assert found.status == "error" and "not allowed" in found.error
        assert fake.requests == []
    own, fake = mcp(blocked_hosts=["mcp.example"])
    assert tools_of(own).status == "error" and fake.requests == []


def test_the_key_is_not_in_the_repr() -> None:
    assert KEY not in repr(McpConfig(url="https://mcp.example/mcp", key=KEY))
