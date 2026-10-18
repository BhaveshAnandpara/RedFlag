"""Adapter for services that speak the OpenAI chat-completions format (Groq, OpenRouter)."""

from typing import Any

import httpx

from redflag_backend.llm.providers.errors import error_for_status
from redflag_backend.llm.types import (
    LLMAnswer,
    LLMRequest,
    ProviderError,
    ProviderTimeout,
    ServerError,
)


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        name: str,
        url: str,
        api_key: str | None,
        model: str,
        token_field: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._api_key = api_key or None
        self._model = model
        self._token_field = token_field
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def __repr__(self) -> str:
        # Deliberately leaves out the key, so printing or logging a provider is always safe.
        return f"{type(self).__name__}(name={self.name!r}, configured={self.configured})"

    def _payload(self, request: LLMRequest, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            self._token_field: request.max_output_tokens,
        }

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                return await client.post(
                    self._url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException:
            raise ProviderTimeout() from None
        except httpx.TransportError:
            raise ServerError() from None

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        response = await self._post(self._payload(request, self._model))
        return parse_chat_reply(response, self._model)


def parse_chat_reply(response: httpx.Response, default_model: str) -> LLMAnswer:
    """Read a chat-completions reply, or raise the typed error it deserves."""
    if response.status_code != 200:
        raise error_for_status(response.status_code, response.headers.get("retry-after"))
    try:
        data = response.json()
    except ValueError:
        raise ServerError() from None
    if not isinstance(data, dict):
        raise ServerError()
    if data.get("error") is not None:
        raise _error_inside_ok_reply(data["error"])
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ServerError()
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ServerError()
    raw_usage = data.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    return LLMAnswer(
        text=content,
        model=str(data.get("model") or default_model),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        estimated_cost_usd=float(usage.get("cost") or 0.0),
    )


def _error_inside_ok_reply(error: object) -> ProviderError:
    """Some services answer 200 and put the failure in the body (OpenRouter does)."""
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, int):
        return error_for_status(code)
    return ServerError()
