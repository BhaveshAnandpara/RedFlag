from typing import Protocol

from redflag_backend.llm.types import LLMAnswer, LLMRequest


class Provider(Protocol):
    """One outside model service. Adapters raise ProviderError subclasses, never raw HTTP errors."""

    name: str
    configured: bool

    async def complete(self, request: LLMRequest) -> LLMAnswer: ...
