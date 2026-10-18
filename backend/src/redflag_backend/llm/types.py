"""Provider-neutral request, answer and error types shared by every provider adapter."""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: tuple[Message, ...]
    temperature: float = 0.0
    max_output_tokens: int = 512
    # Set by the router, never by callers. Adapters must not use a paid model unless True.
    allow_paid: bool = False


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    # Estimated dollars spent on this answer. Zero for free models.
    estimated_cost_usd: float = 0.0


class ProviderError(Exception):
    """Base class. `kind` is the stable name shown in attempt logs and API errors."""

    kind = "provider_error"


class RateLimited(ProviderError):
    kind = "rate_limited"

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class ServerError(ProviderError):
    kind = "server_error"


class ProviderTimeout(ProviderError):
    kind = "timeout"


class ModelUnavailable(ProviderError):
    kind = "model_unavailable"


class ContentBlocked(ProviderError):
    """The provider declined to answer (a safety filter), not an outage or a mistake of ours.

    Recorded as its own outcome so a blocked answer is never mistaken for a real one. Another
    provider may still answer, so the router treats it as a reason to try the next provider.
    """

    kind = "content_blocked"


class AuthError(ProviderError):
    kind = "auth_error"


class BadRequest(ProviderError):
    kind = "bad_request"


# Errors that mean "this provider cannot help right now", so trying the next one is sensible.
# AuthError and BadRequest are the owner's configuration problems and must surface instead.
FALLBACK_ERRORS = (RateLimited, ServerError, ProviderTimeout, ModelUnavailable, ContentBlocked)
