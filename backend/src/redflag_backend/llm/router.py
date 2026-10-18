"""The switchboard: ask providers in order, record every attempt."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from redflag_backend.llm.provider import Provider
from redflag_backend.llm.types import (
    FALLBACK_ERRORS,
    AuthError,
    BadRequest,
    LLMAnswer,
    LLMRequest,
    RateLimited,
)

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

    `kind` is `all_providers_failed`, `no_provider_configured`, `auth_error` or `bad_request`;
    `provider` names the provider behind a configuration error and is None otherwise.
    """

    def __init__(self, kind: str, provider: str | None, attempts: Sequence[Attempt]) -> None:
        super().__init__(kind)
        self.kind = kind
        self.provider = provider
        self.attempts = tuple(attempts)


class Router:
    def __init__(
        self, providers: Sequence[Provider], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._providers = list(providers)
        self._clock = clock
        # Per-process memory: a restart clears it, which is fine for a short cool-off.
        self._cooling_until: dict[str, float] = {}

    async def complete(self, request: LLMRequest) -> RouterResult:
        attempts: list[Attempt] = []
        usable = [provider for provider in self._providers if provider.configured]
        if not usable:
            raise RouterFailure("no_provider_configured", None, attempts)
        for provider in usable:
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
            attempts.append(Attempt(provider.name, answer.model, "ok", _since_ms(started)))
            return RouterResult(answer, provider.name, False, tuple(attempts))
        raise RouterFailure("all_providers_failed", None, attempts)


def _since_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
