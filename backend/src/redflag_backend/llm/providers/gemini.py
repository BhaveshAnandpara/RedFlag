"""Google Gemini over its generateContent REST endpoint."""

import json
from typing import Any

import httpx

from redflag_backend.llm.providers.errors import error_for_status, seconds_from_header
from redflag_backend.llm.types import (
    AuthError,
    ContentBlocked,
    LLMAnswer,
    LLMRequest,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    ServerError,
)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# finishReason values that mean "a safety system stopped the answer".
_BLOCKED_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key or None
        self._model = model
        self._timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def __repr__(self) -> str:
        # Leaves out the key, so printing or logging a provider is always safe.
        return f"GeminiProvider(model={self._model!r}, configured={self.configured})"

    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        system = [m.content for m in request.messages if m.role == "system"]
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return payload

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        url = f"{GEMINI_BASE}/{self._model}:generateContent"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                # The key goes in a header: URLs get logged, headers do not.
                response = await client.post(
                    url,
                    json=self._payload(request),
                    headers={"x-goog-api-key": str(self._api_key)},
                )
        except httpx.TimeoutException:
            raise ProviderTimeout() from None
        except httpx.TransportError:
            raise ServerError() from None
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> LLMAnswer:
        if response.status_code != 200:
            raise _error_for_failed_reply(response)
        try:
            data = response.json()
        except ValueError:
            raise ServerError() from None
        if not isinstance(data, dict):
            raise ServerError()
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = data.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                raise ContentBlocked()
            raise ServerError()
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        text = _text_of(candidate)
        if not text.strip():
            if candidate.get("finishReason") in _BLOCKED_FINISH:
                raise ContentBlocked()
            raise ServerError()
        raw_usage = data.get("usageMetadata")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        return LLMAnswer(
            text=text,
            model=str(data.get("modelVersion") or self._model),
            input_tokens=int(usage.get("promptTokenCount") or 0),
            # Thinking tokens are billed as output, so they count toward budgets too.
            output_tokens=int(usage.get("candidatesTokenCount") or 0)
            + int(usage.get("thoughtsTokenCount") or 0),
        )


def _text_of(candidate: dict[str, Any]) -> str:
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    return "".join(
        p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
    )


def _error_for_failed_reply(response: httpx.Response) -> ProviderError:
    body = _json_or_none(response)
    if response.status_code == 400 and "API_KEY_INVALID" in json.dumps(body):
        # Gemini reports a bad key as a 400, but it is a configuration problem, not a bad request.
        return AuthError()
    if response.status_code == 429:
        hint = _retry_delay_seconds(body) or seconds_from_header(
            response.headers.get("retry-after")
        )
        return RateLimited(hint)
    return error_for_status(response.status_code, response.headers.get("retry-after"))


def _json_or_none(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None


def _retry_delay_seconds(body: object) -> float | None:
    """Google errors can carry a RetryInfo detail such as {"retryDelay": "37s"}."""
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if not isinstance(details, list):
        return None
    for detail in details:
        delay = detail.get("retryDelay") if isinstance(detail, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            return seconds_from_header(delay[:-1])
    return None
