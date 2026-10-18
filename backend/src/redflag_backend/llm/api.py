import asyncio
import hmac
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from redflag_backend.llm.budget import BudgetBook, BudgetCaps
from redflag_backend.llm.cache import SqlCache
from redflag_backend.llm.calls import CallLog
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.router import Attempt, Router, RouterFailure, RouterResult
from redflag_backend.llm.spend import SqlSpend
from redflag_backend.llm.types import LLMRequest, Message
from redflag_backend.settings import Settings

# A bad key is a gateway-style problem (502), a bad request is the caller's (400), a run of
# failures across every provider is a temporary outage (503), and a spent budget is 429.
_FAILURE_STATUS = {
    "auth_error": 502,
    "bad_request": 400,
    "all_providers_failed": 503,
    "no_provider_configured": 503,
    "budget_exceeded": 429,
}

DEFAULT_SESSION = "default"


class MessageBody(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class BudgetOverrides(BaseModel):
    """Caps for a session. Applied only when the session first appears."""

    max_requests: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_seconds: float | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, ge=1)

    def as_caps_changes(self) -> dict[str, float | int]:
        names = {
            "max_requests": "requests",
            "max_tokens": "tokens",
            "max_seconds": "seconds",
            "max_concurrency": "concurrency",
        }
        return {names[k]: v for k, v in self.model_dump().items() if v is not None}


class SimulateFailureBody(BaseModel):
    provider: str
    seconds: float = Field(default=60.0, gt=0, le=3600)


class ChatBody(BaseModel):
    messages: list[MessageBody] = Field(min_length=1)
    temperature: float = 0.0
    max_output_tokens: int = Field(default=512, ge=1, le=8192)
    session_id: str | None = Field(default=None, max_length=100)
    budget: BudgetOverrides | None = None


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
    budget: dict[str, Any]
    paid: bool
    estimated_cost_usd: float


def _attempt_body(attempt: Attempt) -> AttemptBody:
    return AttemptBody(
        provider=attempt.provider,
        model=attempt.model,
        outcome=attempt.outcome,
        latency_ms=attempt.latency_ms,
    )


def _chat_response(result: RouterResult, budget: dict[str, Any]) -> ChatResponse:
    return ChatResponse(
        answer=result.answer.text,
        provider=result.provider,
        model=result.answer.model,
        cached=result.cached,
        usage=UsageBody(
            input_tokens=result.answer.input_tokens, output_tokens=result.answer.output_tokens
        ),
        attempts=[_attempt_body(a) for a in result.attempts],
        budget=budget,
        paid=result.answer.estimated_cost_usd > 0 and not result.cached,
        estimated_cost_usd=0.0 if result.cached else result.answer.estimated_cost_usd,
    )


def build_llm_router(
    settings: Settings,
    providers: Sequence[Provider],
    engine: Engine,
    clock: Callable[[], float] | None = None,
) -> APIRouter:
    now = clock or time.time
    cache = SqlCache(engine, settings.cache_ttl_seconds, settings.cache_max_bytes)
    call_log = CallLog(engine, settings.call_log_max_rows)
    router_core = Router(
        providers,
        clock=now,
        cache=cache,
        spend=SqlSpend(engine),
        allow_paid_models=settings.allow_paid_models,
        paid_spend_cap_usd=settings.paid_spend_cap_usd,
    )
    budgets = BudgetBook(
        BudgetCaps(
            requests=settings.budget_max_requests,
            tokens=settings.budget_max_tokens,
            seconds=settings.budget_max_seconds,
            concurrency=settings.budget_max_concurrency,
        ),
        clock=now,
    )

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
        overrides = body.budget.as_caps_changes() if body.budget else None
        budget = budgets.session(body.session_id or DEFAULT_SESSION, overrides)
        session_id = body.session_id or DEFAULT_SESSION
        try:
            result = await router_core.complete(request, budget)
        except RouterFailure as failure:
            await asyncio.to_thread(
                call_log.record, session_id, failure.attempts, None, False, False, now()
            )
            error: dict[str, Any] = {"kind": failure.kind, "provider": failure.provider}
            if failure.cap is not None:
                error["cap"] = failure.cap
            return JSONResponse(
                status_code=_FAILURE_STATUS[failure.kind],
                content={
                    "error": error,
                    "attempts": [_attempt_body(a).model_dump() for a in failure.attempts],
                    "budget": budget.snapshot(now()),
                },
            )
        usage = (result.answer.input_tokens, result.answer.output_tokens)
        paid = result.answer.estimated_cost_usd > 0 and not result.cached
        await asyncio.to_thread(
            call_log.record, session_id, result.attempts, usage, result.cached, paid, now()
        )
        return _chat_response(result, budget.snapshot(now()))

    @router.get("/providers")
    async def provider_status() -> dict[str, Any]:
        return {"providers": router_core.provider_status()}

    @router.post("/test/fail")
    async def simulate_failure(body: SimulateFailureBody) -> dict[str, Any]:
        """Test tool: pretend a provider is rate-limited for a while. Resets on restart."""
        if not router_core.simulate_rate_limit(body.provider, body.seconds):
            raise HTTPException(status_code=404, detail="unknown provider")
        return {"provider": body.provider, "seconds": body.seconds}

    @router.post("/test/clear-cache")
    async def clear_cache() -> dict[str, bool]:
        await asyncio.to_thread(cache.clear)
        return {"cleared": True}

    @router.get("/calls")
    async def calls(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        return {"calls": await asyncio.to_thread(call_log.recent, limit)}

    return router
