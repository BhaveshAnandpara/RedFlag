"""Talk to someone else's MCP server over HTTP (the streamable HTTP transport).

Rules this file keeps, the same as the chat target: it never raises (every failure is an error
result with its cause, never a pass); the key goes only in its header and never appears in a
result, an error or a repr; an address that points inside or is not a web address is never
called; the call goes to the address that was checked; redirects are not followed; and a reply
that echoes the key has it replaced. A server may answer with plain JSON or with a short event
stream holding one message; both are read. It sends only initialize, tools/list and tools/call.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from redflag_backend.targets.http_target import (
    KEY_REPLACEMENT,
    EndpointConfig,
    HttpTarget,
    Resolver,
    _Refused,
    system_resolver,
)

PROTOCOL_VERSION = "2025-03-26"
MAX_PAGES = 5
MAX_TOOLS = 100


@dataclass(frozen=True)
class McpConfig:
    url: str
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    # From the server's own annotations: True only if it says the tool does not change anything.
    read_only_hint: bool | None = None


@dataclass(frozen=True)
class ToolsResult:
    status: Literal["ok", "error"]
    tools: list[McpTool] = field(default_factory=list)
    server_name: str = ""
    server_version: str = ""
    error: str = ""


@dataclass(frozen=True)
class CallResult:
    # "refused" is an HTTP-level 4xx: the server did not run the call at all. That may be the
    # server correctly rejecting it, or an unrelated problem (a stale session, a bad request
    # shape) — Redflag cannot tell which, so it is reported as inconclusive, not folded in with
    # a connection failure ("error") or treated as a pass.
    status: Literal["ok", "error", "refused"]
    # The text the tool sent back (or the server's error text for a tool that failed).
    text: str = ""
    # True when the server said the call failed (isError, or a protocol error message).
    tool_error: bool = False
    error: str = ""


class _Failed(Exception):
    """A problem to report as an error result. The message is shown to the user."""


class _ServerRefused(_Failed):
    """The server answered with a 4xx status: it did not run the call. A subclass of _Failed so
    a plain `except _Failed` still catches it (connecting still treats this as an error), but
    call_tool catches it separately to report it as inconclusive, not a crash."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"The server answered with status {status} and did not run the call.")


class McpTarget:
    def __init__(
        self,
        config: McpConfig,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        blocked_hosts: Iterable[str] = (),
        timeout: float = 20.0,
        max_reply_bytes: int = 262_144,
    ) -> None:
        self._config = config
        self._transport = transport
        self._timeout = timeout
        self._max_bytes = max_reply_bytes
        # The address checks are the chat target's, so both keep the same rules.
        self._checker = HttpTarget(
            EndpointConfig(url=config.url),
            resolver=resolver,
            transport=transport,
            blocked_hosts=blocked_hosts,
        )
        self._session: str | None = None
        self._next_id = 0
        self._ready = False

    # --- what the owner of a page can ask for -------------------------------------------------

    async def list_tools(self) -> ToolsResult:
        try:
            info = await self._connect()
            tools: list[McpTool] = []
            cursor: str | None = None
            for _ in range(MAX_PAGES):
                params = {"cursor": cursor} if cursor else {}
                result = await self._request("tools/list", params)
                for raw in result.get("tools", []):
                    tools.append(_tool(raw))
                cursor = result.get("nextCursor")
                if not cursor or len(tools) >= MAX_TOOLS:
                    break
        except _Failed as failed:
            return ToolsResult("error", error=str(failed))
        server = info.get("serverInfo") or {}
        return ToolsResult(
            "ok",
            tools[:MAX_TOOLS],
            server_name=self._clean(str(server.get("name", ""))),
            server_version=self._clean(str(server.get("version", ""))),
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallResult:
        try:
            await self._connect()
            result = await self._request("tools/call", {"name": name, "arguments": arguments})
        except _ServerRefused as refused:
            return CallResult("refused", error=str(refused))
        except _Failed as failed:
            return CallResult("error", error=str(failed))
        except _ToolRefused as refused:
            # The server answered with a protocol-level error for this call: it did not run it.
            return CallResult("ok", text=self._clean(str(refused)), tool_error=True)
        parts = [
            str(part.get("text", ""))
            for part in result.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if not parts and "structuredContent" in result:
            parts = [json.dumps(result["structuredContent"])]
        return CallResult(
            "ok", text=self._clean("\n".join(parts)), tool_error=bool(result.get("isError"))
        )

    # --- the protocol -------------------------------------------------------------------------

    async def _connect(self) -> dict[str, Any]:
        if self._ready:
            return {}
        info = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "redflag", "version": "1"},
            },
        )
        await self._notify("notifications/initialized")
        self._ready = True
        return info

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        body = {"jsonrpc": "2.0", "id": message_id, "method": method, "params": params}
        text, content_type = await self._post(body)
        message = self._find_message(text, content_type, message_id)
        if "error" in message:
            error = message["error"] if isinstance(message["error"], dict) else {}
            if method == "tools/call":
                raise _ToolRefused(str(error.get("message", "The server refused the call.")))
            raise _Failed(f"The server returned an error: {error.get('message', 'unknown')}.")
        result = message.get("result")
        if not isinstance(result, dict):
            raise _Failed("The server's answer had no result.")
        return result

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method}, expect_body=False)

    def _find_message(self, text: str, content_type: str, message_id: int) -> dict[str, Any]:
        candidates: list[str]
        if "text/event-stream" in content_type:
            candidates = [
                line.removeprefix("data:").strip()
                for line in text.splitlines()
                if line.startswith("data:")
            ]
        else:
            candidates = [text]
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("id") == message_id:
                return data
        raise _Failed("The server did not answer as an MCP server does.")

    async def _post(self, body: dict[str, Any], expect_body: bool = True) -> tuple[str, str]:
        config = self._config
        try:
            scheme, host, port, ip = await self._checker.check_address()
        except _Refused as refused:
            raise _Failed(str(refused)) from refused
        parts = urlsplit(config.url)
        ip_host = f"[{ip}]" if ":" in ip else ip
        url = f"{scheme}://{ip_host}:{port}{parts.path or '/'}"
        if parts.query:
            url += f"?{parts.query}"
        default_port = 443 if scheme == "https" else 80
        headers = {
            "Host": host if port == default_port else f"{host}:{port}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        if config.key:
            headers[config.header_name] = f"{config.header_prefix}{config.key}"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=self._timeout,
                trust_env=False,
            ) as client:
                request = client.build_request(
                    "POST",
                    url,
                    headers=headers,
                    content=json.dumps(body),
                    extensions={"sni_hostname": host},
                )
                response = await client.send(request, stream=True)
                try:
                    text = await self._read(response)
                finally:
                    await response.aclose()
        except httpx.TimeoutException as problem:
            raise _Failed("The server timed out.") from problem
        except httpx.ConnectError as problem:
            raise _Failed("Could not connect to the server.") from problem
        except httpx.HTTPError as problem:
            raise _Failed(f"The request failed ({type(problem).__name__}).") from problem
        status = response.status_code
        if 300 <= status < 400:
            raise _Failed(f"The server answered with a redirect ({status}), which is not followed.")
        if 400 <= status < 500:
            raise _ServerRefused(status)
        if status >= 500:
            raise _Failed(f"The server answered with status {status}.")
        session = response.headers.get("mcp-session-id")
        if session:
            self._session = session
        if not expect_body:
            return "", ""
        return text, response.headers.get("content-type", "").lower()

    async def _read(self, response: httpx.Response) -> str:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                raise _Failed("The reply was too large to read.")
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _clean(self, text: str) -> str:
        key = self._config.key
        return text.replace(key, KEY_REPLACEMENT) if key else text


class _ToolRefused(Exception):
    """The server answered a tool call with a protocol error instead of running it."""


def _tool(raw: Any) -> McpTool:
    if not isinstance(raw, dict):
        raise _Failed("The server listed a tool in a way that could not be read.")
    schema = raw.get("inputSchema")
    annotations = raw.get("annotations")
    hint = annotations.get("readOnlyHint") if isinstance(annotations, dict) else None
    return McpTool(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        input_schema=schema if isinstance(schema, dict) else {},
        read_only_hint=hint if isinstance(hint, bool) else None,
    )
