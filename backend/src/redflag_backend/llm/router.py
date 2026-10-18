"""The switchboard: ask providers in order, record every attempt."""

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from redflag_backend.llm.budget import SessionBudget
from redflag_backend.llm.cache import SqlCache, cache_key
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.spend import SqlSpend
from redflag_backend.llm.types import (
    FALLBACK_ERRORS,
    AuthError,
    BadRequest,
    LLMAnswer,
    LLMRequest,
    RateLimited,
)

logger = logging.getLogger(__name__)

# How long to skip a provider after a rate limit that did not say when to come back.
DEFAULT_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class Attempt:
    provider: str
    model: str | None
    outcome: str
    latency_ms: int


@dataclass(frozen=True)
class RouterResult:
    answer: LLMAnswer
    provider: str
    cached: bool
    attempts: tuple[Attempt, ...]


class RouterFailure(Exception):
    """The router could not produce an answer. This is never reported as a success.

    `kind` is `all_providers_failed`, `no_provider_configured`, `auth_error`, `bad_request`
    or `budget_exceeded`. `provider` names the provider behind a configuration error, and
    `cap` names the budget cap that was hit; both are None otherwise.
    """

    def __init__(
        self,
        kind: str,
        provider: str | None,
        attempts: Sequence[Attempt],
        cap: str | None = None,
    ) -> None:
        super().__init__(kind)
        self.kind = kind
        self.provider = provider
        self.attempts = tuple(attempts)
        self.cap = cap


class Router:
    def __init__(
        self,
        providers: Sequence[Provider],
        clock: Callable[[], float] = time.time,
        cache: SqlCache | None = None,
        spend: SqlSpend | None = None,
        allow_paid_models: bool = False,
        paid_spend_cap_usd: float = 0.0,
    ) -> None:
        self._providers = list(providers)
        # Epoch seconds, so cache expiry means something across restarts.
        self._clock = clock
        self._cache = cache
        self._spend = spend
        self._allow_paid_models = allow_paid_models
        self._paid_spend_cap = paid_spend_cap_usd
        # Per-process memory: a restart clears it, which is fine for a short cool-off.
        self._cooling_until: dict[str, float] = {}
        # Owner-requested "pretend this provider is out of quota" switches, also in memory.
        self._simulated_until: dict[str, float] = {}

    def simulate_rate_limit(self, provider_name: str, seconds: float) -> bool:
        """Make a provider look rate-limited for a while. False if there is no such provider."""
        if provider_name not in {p.name for p in self._providers}:
            return False
        self._simulated_until[provider_name] = self._clock() + seconds
        return True

    def provider_status(self) -> list[dict[str, object]]:
        """Who is configured and who is cooling down. Never includes keys."""
        now = self._clock()
        status: list[dict[str, object]] = []
        for provider in self._providers:
            left = max(0.0, self._cooling_until.get(provider.name, 0.0) - now)
            status.append(
                {
                    "name": provider.name,
                    "configured": provider.configured,
                    "cooling_down": left > 0,
                    "cooldown_seconds_left": round(left, 1) if left > 0 else 0,
                }
            )
        return status

    async def complete(
        self, request: LLMRequest, budget: SessionBudget | None = None
    ) -> RouterResult:
        cache = self._cache if request.temperature == 0 else None
        key = cache_key(request)
        if cache is not None:
            hit = await asyncio.to_thread(cache.get, key, self._clock())
            if hit is not None:
                # Saved answers cost nothing, so they never count against the budget.
                attempt = Attempt(hit.provider, hit.answer.model, "cache_hit", 0)
                return RouterResult(hit.answer, hit.provider, True, (attempt,))

        if budget is None:
            return await self._ask_providers(request, key, cache)

        cap = budget.exceeded(self._clock())
        if cap is not None:
            raise RouterFailure("budget_exceeded", None, [], cap=cap)
        budget.requests_used += 1
        async with budget.slots:
            result = await self._ask_providers(request, key, cache)
        budget.tokens_used += result.answer.input_tokens + result.answer.output_tokens
        return result

    async def _ask_providers(
        self, request: LLMRequest, key: str, cache: SqlCache | None
    ) -> RouterResult:
        attempts: list[Attempt] = []
        usable = [provider for provider in self._providers if provider.configured]
        if not usable:
            raise RouterFailure("no_provider_configured", None, attempts)
        request = replace(request, allow_paid=await self._paid_allowed())
        for provider in usable:
            if self._clock() < self._simulated_until.get(provider.name, 0.0):
                # Labeled as a simulation so it can never be mistaken for a real outage.
                attempts.append(Attempt(provider.name, None, "simulated_rate_limit", 0))
                continue
            if self._clock() < self._cooling_until.get(provider.name, 0.0):
                attempts.append(Attempt(provider.name, None, "cooling_down", 0))
                continue
            started = time.monotonic()
            try:
                answer = await provider.complete(request)
            except FALLBACK_ERRORS as error:
                if isinstance(error, RateLimited):
                    wait = error.retry_after or DEFAULT_COOLDOWN_SECONDS
                    self._cooling_until[provider.name] = self._clock() + wait
                attempts.append(Attempt(provider.name, None, error.kind, _since_ms(started)))
                continue
            except (AuthError, BadRequest) as error:
                # The owner's configuration or request is wrong. Another provider would hide it.
                attempts.append(Attempt(provider.name, None, error.kind, _since_ms(started)))
                raise RouterFailure(error.kind, provider.name, attempts) from error
            except Exception as error:
                # A bug in an adapter must not take the request down or leak what it says: the
                # message could contain a key. Log only the kind of error, never its text.
                logger.warning(
                    "provider %s raised an unexpected %s", provider.name, type(error).__name__
                )
                attempts.append(
                    Attempt(provider.name, None, "unexpected_error", _since_ms(started))
                )
                continue
            attempts.append(Attempt(provider.name, answer.model, "ok", _since_ms(started)))
            if answer.estimated_cost_usd > 0 and self._spend is not None:
                await asyncio.to_thread(self._spend.add, answer.estimated_cost_usd)
            if cache is not None:
                await asyncio.to_thread(cache.put, key, provider.name, answer, self._clock())
            return RouterResult(answer, provider.name, False, tuple(attempts))
        raise RouterFailure("all_providers_failed", None, attempts)

    async def _paid_allowed(self) -> bool:
        """Paid models need the switch on, a cap above zero, and room left under that cap."""
        if not self._allow_paid_models or self._paid_spend_cap <= 0 or self._spend is None:
            return False
        spent = await asyncio.to_thread(self._spend.total)
        return spent < self._paid_spend_cap


def _since_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
