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


@dataclass(frozen=True)
class LLMAnswer:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


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


class AuthError(ProviderError):
    kind = "auth_error"


class BadRequest(ProviderError):
    kind = "bad_request"


# Errors that mean "this provider cannot help right now", so trying the next one is sensible.
# AuthError and BadRequest are the owner's configuration problems and must surface instead.
FALLBACK_ERRORS = (RateLimited, ServerError, ProviderTimeout, ModelUnavailable)
