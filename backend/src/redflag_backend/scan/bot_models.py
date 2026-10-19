"""The demo bots' model access: their own keys, their own router and their own budget.

This is separate from Redflag's own router (M1): different keys, no answer cache (every scan is
a fresh run) and no spend tracking. Nothing here touches the M1 router's settings or tables.
"""

from collections.abc import Callable, Sequence

from redflag_backend.llm.budget import BudgetCaps
from redflag_backend.llm.provider import Provider
from redflag_backend.llm.providers.gemini import GeminiProvider
from redflag_backend.llm.providers.groq import GroqProvider
from redflag_backend.llm.providers.openrouter import OpenRouterProvider
from redflag_backend.llm.router import Router
from redflag_backend.llm.types import BadRequest, LLMAnswer, LLMRequest, ModelUnavailable
from redflag_backend.settings import Settings


def build_bot_providers(settings: Settings) -> list[Provider]:
    """The bots' providers from the BOT_ settings, in the configured order."""
    timeout = settings.provider_timeout_seconds
    available: dict[str, Provider] = {
        "groq": GroqProvider(settings.bot_groq_api_key, settings.bot_groq_model, timeout),
        "gemini": GeminiProvider(settings.bot_gemini_api_key, settings.bot_gemini_model, timeout),
        "openrouter": OpenRouterProvider(
            settings.bot_openrouter_api_key,
            free_models=[m.strip() for m in settings.bot_openrouter_free_models.split(",")],
            paid_model=None,
            timeout=timeout,
        ),
    }
    order = [name.strip() for name in settings.bot_provider_order.split(",") if name.strip()]
    return [available[name] for name in order if name in available]


class FallsThroughOnRejection:
    """Wraps a bot model so a request it rejects moves on to the next model.

    Some free models reject the bots' plain-text tool format (Groq's gpt-oss reads it as its own
    tool calling and answers with a bad-request error). For a bot, that means "this model cannot
    do this job", not "the owner's request is wrong". A bad key is a different error and still
    stops the scan visibly.
    """

    def __init__(self, inner: Provider) -> None:
        self._inner = inner
        self.name = inner.name

    @property
    def configured(self) -> bool:
        return self._inner.configured

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        try:
            return await self._inner.complete(request)
        except BadRequest as error:
            raise ModelUnavailable() from error


def build_bot_router(providers: Sequence[Provider], clock: Callable[[], float]) -> Router:
    wrapped = [FallsThroughOnRejection(p) for p in providers]
    return Router(wrapped, clock=clock, cache=None, spend=None, allow_paid_models=False)


def bot_budget_caps(settings: Settings) -> BudgetCaps:
    return BudgetCaps(
        requests=settings.bot_budget_max_requests,
        tokens=settings.bot_budget_max_tokens,
        seconds=settings.bot_budget_max_seconds,
        concurrency=settings.bot_budget_max_concurrency,
    )
