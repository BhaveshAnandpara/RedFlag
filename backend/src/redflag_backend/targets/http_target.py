"""Talk to someone else's chat endpoint over HTTP.

Rules this file keeps: it never raises (every failure is an error result with its cause, never
a pass); the key goes only in its header and never appears in a result, an error or a repr; an
address that points inside or is not a web address is never called; the call goes to the
address that was checked, not to a second name lookup; redirects are not followed; and a reply
that echoes the key has it replaced before anyone sees it.
"""

import asyncio
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]

PLACEHOLDER = "{{prompt}}"
KEY_REPLACEMENT = "[key removed]"
RAW_LIMIT = 500
DEFAULT_REPLY_PATH = "choices.0.message.content"


@dataclass(frozen=True)
class EndpointConfig:
    url: str
    format: Literal["openai", "custom"] = "openai"
    model: str = "default"
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    request_template: str | None = None
    reply_path: str | None = None
    key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class TargetResult:
    status: Literal["ok", "error"]
    reply: str = ""
    error: str = ""
    http_status: int | None = None


@dataclass(frozen=True)
class ConnectionCheck:
    status: Literal["ok", "error"]
    http_status: int | None = None
    raw_reply: str = ""
    parsed_reply: str = ""
    error: str = ""


@dataclass(frozen=True)
class _Exchange:
    """What came back from one call, before the reply is read out of it."""

    http_status: int | None
    body: str
    error: str = ""


class _Refused(Exception):
    """An address that may not be called. The message is shown to the user."""


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return sorted({str(info[4][0]) for info in infos})


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


class HttpTarget:
    def __init__(
        self,
        config: EndpointConfig,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        blocked_hosts: Iterable[str] = (),
        timeout: float = 20.0,
        max_reply_bytes: int = 65_536,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._transport = transport
        self._blocked = {host.lower() for host in blocked_hosts}
        self._timeout = timeout
        self._max_bytes = max_reply_bytes

    async def send(self, prompt: str) -> TargetResult:
        exchange = await self._exchange(prompt)
        if exchange.error:
            return TargetResult("error", error=exchange.error, http_status=exchange.http_status)
        try:
            reply = self._read_reply(exchange.body)
        except ValueError as problem:
            return TargetResult("error", error=str(problem), http_status=exchange.http_status)
        return TargetResult("ok", reply=self._clean(reply), http_status=exchange.http_status)

    async def send_conversation(self, messages: list[dict[str, str]]) -> TargetResult:
        """Send a whole conversation (user and assistant turns, oldest first). Only the
        OpenAI-compatible format can hold one: a custom template has a single prompt slot."""
        exchange = await self._exchange("", messages)
        if exchange.error:
            return TargetResult("error", error=exchange.error, http_status=exchange.http_status)
        try:
            reply = self._read_reply(exchange.body)
        except ValueError as problem:
            return TargetResult("error", error=str(problem), http_status=exchange.http_status)
        return TargetResult("ok", reply=self._clean(reply), http_status=exchange.http_status)

    async def test_connection(self) -> ConnectionCheck:
        """One harmless message, and what came back, so the user can see if the setup is right."""
        exchange = await self._exchange("Hello")
        raw = self._clean(exchange.body)[:RAW_LIMIT]
        if exchange.error:
            return ConnectionCheck(
                "error", exchange.http_status, raw_reply=raw, error=exchange.error
            )
        try:
            parsed = self._read_reply(exchange.body)
        except ValueError as problem:
            return ConnectionCheck("error", exchange.http_status, raw_reply=raw, error=str(problem))
        return ConnectionCheck(
            "ok", exchange.http_status, raw_reply=raw, parsed_reply=self._clean(parsed)
        )

    # --- building and sending the request -------------------------------------------------

    def _body(self, prompt: str, messages: list[dict[str, str]] | None = None) -> str:
        config = self._config
        if messages is not None and config.format != "openai":
            raise ValueError("A conversation needs the OpenAI-compatible format.")
        if config.format == "openai":
            turns = messages if messages is not None else [{"role": "user", "content": prompt}]
            return json.dumps({"model": config.model, "messages": turns})
        template = config.request_template or ""
        if PLACEHOLDER not in template:
            raise ValueError(
                f"The request template must contain {PLACEHOLDER} where the prompt goes."
            )
        try:
            json.loads(template.replace(PLACEHOLDER, "x"))
        except ValueError as problem:
            raise ValueError("The request template is not valid JSON.") from problem
        # One pass, so a prompt that itself contains the placeholder is not substituted again.
        return template.replace(PLACEHOLDER, json.dumps(prompt)[1:-1])

    async def _check_address(self) -> tuple[str, str, int, str]:
        """The checked address to call: (scheme, host name, port, ip). Raises _Refused."""
        try:
            parts = urlsplit(self._config.url)
            host = (parts.hostname or "").lower()
            port = parts.port
        except ValueError as problem:
            raise _Refused("That address is not allowed.") from problem
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            raise _Refused("That address is not allowed: it must be a plain http or https address.")
        if host in self._blocked:
            raise _Refused("That address is not allowed: it is Redflag's own.")
        port = port or (443 if parts.scheme == "https" else 80)
        addresses = await self._addresses(host, port)
        if not addresses:
            raise _Refused("Could not resolve that address.")
        if not all(_is_public(address) for address in addresses):
            raise _Refused(
                "That address is not allowed: it points to a private or internal address."
            )
        return parts.scheme, host, port, addresses[0]

    async def _addresses(self, host: str, port: int) -> list[str]:
        """The addresses a host name points to, or the address itself if it is already one."""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return [host]
        try:
            return await self._resolver(host, port)
        except OSError as problem:
            raise _Refused("Could not resolve that address.") from problem

    async def _exchange(
        self, prompt: str, messages: list[dict[str, str]] | None = None
    ) -> _Exchange:
        config = self._config
        try:
            body = self._body(prompt, messages)
        except ValueError as problem:
            return _Exchange(None, "", str(problem))
        try:
            scheme, host, port, ip = await self._check_address()
        except _Refused as refused:
            return _Exchange(None, "", str(refused))

        parts = urlsplit(config.url)
        ip_host = f"[{ip}]" if ":" in ip else ip
        url = f"{scheme}://{ip_host}:{port}{parts.path or '/'}"
        if parts.query:
            url += f"?{parts.query}"
        default_port = 443 if scheme == "https" else 80
        host_header = host if port == default_port else f"{host}:{port}"
        headers = {"Host": host_header, "Content-Type": "application/json"}
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
                    "POST", url, headers=headers, content=body, extensions={"sni_hostname": host}
                )
                response = await client.send(request, stream=True)
                try:
                    return await self._read_response(response)
                finally:
                    await response.aclose()
        except httpx.TimeoutException:
            return _Exchange(None, "", "The server timed out.")
        except httpx.ConnectError:
            return _Exchange(None, "", "Could not connect to the server.")
        except httpx.RemoteProtocolError:
            return _Exchange(None, "", "The server broke the HTTP protocol.")
        except httpx.HTTPError as problem:
            return _Exchange(None, "", f"The request failed ({type(problem).__name__}).")

    async def _read_response(self, response: httpx.Response) -> _Exchange:
        status = response.status_code
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                return _Exchange(status, "", "The reply was too large to read.")
            chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if 300 <= status < 400:
            return _Exchange(
                status,
                text,
                f"The server answered with a redirect ({status}), which is not followed.",
            )
        if status >= 400:
            return _Exchange(status, text, f"The server answered with status {status}.")
        if "text/event-stream" in response.headers.get("content-type", "").lower():
            return _Exchange(status, text, "The server sent a stream, which is not supported.")
        return _Exchange(status, text)

    # --- reading the reply ----------------------------------------------------------------

    def _read_reply(self, body: str) -> str:
        try:
            data: Any = json.loads(body)
        except ValueError as problem:
            raise ValueError("The reply was not JSON.") from problem
        path = self._config.reply_path or (
            DEFAULT_REPLY_PATH if self._config.format == "openai" else None
        )
        if not path:
            raise ValueError("A custom format needs a reply path, such as data.answer.")
        node = data
        for part in path.split("."):
            try:
                node = node[int(part)] if isinstance(node, list) else node[part]
            except (KeyError, IndexError, TypeError, ValueError) as problem:
                raise ValueError(
                    f"The reply path '{path}' was not found in the reply."
                ) from problem
        if not isinstance(node, str):
            raise ValueError("The value at the reply path is not text.")
        if not node.strip():
            raise ValueError("The reply was empty.")
        return node

    def _clean(self, text: str) -> str:
        key = self._config.key
        return text.replace(key, KEY_REPLACEMENT) if key else text
