"""Turn provider HTTP outcomes into the router's typed errors.

Error text from a provider is never copied into our errors: it could echo a key or a prompt.
"""

from redflag_backend.llm.types import (
    AuthError,
    BadRequest,
    ModelUnavailable,
    ProviderError,
    ProviderTimeout,
    RateLimited,
    ServerError,
)


def seconds_from_header(value: str | None) -> float | None:
    """Parse a Retry-After value given in seconds. Anything else means "no hint"."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def error_for_status(status: int, retry_after: str | None = None) -> ProviderError:
    if status == 429:
        return RateLimited(seconds_from_header(retry_after))
    if status in (408, 504):
        return ProviderTimeout()
    if status in (401, 403):
        return AuthError()
    # 402 is OpenRouter's "out of credits": this provider cannot help right now.
    if status in (402, 404):
        return ModelUnavailable()
    if status >= 500:
        return ServerError()
    return BadRequest()
