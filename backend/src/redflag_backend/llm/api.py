import hmac
import time
from collections.abc import Callable, Sequence
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from redflag_backend.llm.provider import Provider
from redflag_backend.llm.router import Attempt, Router, RouterFailure, RouterResult
from redflag_backend.llm.types import LLMRequest, Message
from redflag_backend.settings import Settings

# A bad key is a gateway-style problem (502), a bad request is the caller's (400), and a
# run of failures across every provider is a temporary outage (503).
_FAILURE_STATUS = {
    "auth_error": 502,
    "bad_request": 400,
    "all_providers_failed": 503,
    "no_provider_configured": 503,
}


class MessageBody(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatBody(BaseModel):
    messages: list[MessageBody] = Field(min_length=1)
    temperature: float = 0.0
    max_output_tokens: int = Field(default=512, ge=1, le=8192)


class AttemptBody(BaseModel):
    provider: str
    model: str | None
    outcome: str
    latency_ms: int


class UsageBody(BaseModel):
    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    answer: str
    provider: str
    model: str
    cached: bool
    usage: UsageBody
    attempts: list[AttemptBody]


def _attempt_body(attempt: Attempt) -> AttemptBody:
    return AttemptBody(
        provider=attempt.provider,
        model=attempt.model,
        outcome=attempt.outcome,
        latency_ms=attempt.latency_ms,
    )


def _chat_response(result: RouterResult) -> ChatResponse:
    return ChatResponse(
        answer=result.answer.text,
        provider=result.provider,
        model=result.answer.model,
        cached=result.cached,
        usage=UsageBody(
            input_tokens=result.answer.input_tokens, output_tokens=result.answer.output_tokens
        ),
        attempts=[_attempt_body(a) for a in result.attempts],
    )


def build_llm_router(
    settings: Settings,
    providers: Sequence[Provider],
    clock: Callable[[], float] | None = None,
) -> APIRouter:
    router_core = Router(providers, clock=clock or time.monotonic)

    def require_owner(x_owner_token: str | None = Header(default=None)) -> None:
        expected = settings.owner_token
        if not expected or not x_owner_token or not hmac.compare_digest(x_owner_token, expected):
            raise HTTPException(status_code=401, detail="owner token required")

    router = APIRouter(prefix="/llm", dependencies=[Depends(require_owner)])

    @router.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatBody) -> ChatResponse | JSONResponse:
        request = LLMRequest(
            messages=tuple(Message(m.role, m.content) for m in body.messages),
            temperature=body.temperature,
            max_output_tokens=body.max_output_tokens,
        )
        try:
            return _chat_response(await router_core.complete(request))
        except RouterFailure as failure:
            return JSONResponse(
                status_code=_FAILURE_STATUS[failure.kind],
                content={
                    "error": {"kind": failure.kind, "provider": failure.provider},
                    "attempts": [_attempt_body(a).model_dump() for a in failure.attempts],
                },
            )

    return router
