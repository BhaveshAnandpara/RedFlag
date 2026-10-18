"""OpenRouter: an OpenAI-style service that fronts many models, free and paid.

Free models rotate without warning, so the adapter takes an ordered list and moves to the next
when one is gone, down or rate limited. A paid model is only ever used when the router says
paid use is allowed (the owner switched it on and there is room under the spending cap).
"""

from collections.abc import Sequence

import httpx

from redflag_backend.llm.providers.openai_compat import OpenAICompatProvider, parse_chat_reply
from redflag_backend.llm.types import (
    LLMAnswer,
    LLMRequest,
    ModelUnavailable,
    ProviderError,
    RateLimited,
    ServerError,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(OpenAICompatProvider):
    def __init__(
        self,
        api_key: str | None,
        free_models: Sequence[str],
        paid_model: str | None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            name="openrouter",
            url=OPENROUTER_URL,
            api_key=api_key,
            model="",
            token_field="max_tokens",
            timeout=timeout,
            transport=transport,
        )
        self._free_models = [m for m in free_models if m]
        self._paid_model = paid_model or None

    async def complete(self, request: LLMRequest) -> LLMAnswer:
        last_error: ProviderError = ModelUnavailable()
        rate_limited = False
        longest_wait: float | None = None
        for model in self._free_models:
            try:
                return await self._ask(request, model)
            except RateLimited as error:
                # Seen live: one free model can be rate limited at its upstream provider while
                # the next answers fine, so a free model's 429 says nothing about the others.
                rate_limited = True
                if error.retry_after and (longest_wait is None or error.retry_after > longest_wait):
                    longest_wait = error.retry_after
            except (ModelUnavailable, ServerError) as error:
                # This one model is gone or its upstream is down; the next free model may be fine.
                last_error = error
        if request.allow_paid and self._paid_model:
            return await self._ask(request, self._paid_model)
        if rate_limited:
            # Report the longest wait, so the router skips this provider for long enough.
            raise RateLimited(longest_wait)
        raise last_error

    async def _ask(self, request: LLMRequest, model: str) -> LLMAnswer:
        response = await self._post(self._payload(request, model))
        return parse_chat_reply(response, model)
