from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Hosts hand out plain postgres:// URLs; SQLAlchemy needs the psycopg driver named.

    Also forgives stray spaces and quotes, which come along when a value is copied from a .env file.
    """
    url = url.strip().strip("\"'").strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(repr=False)  # a secret: it holds the database password
    frontend_origin: str
    app_version: str = "0.1.0"
    commit_sha: str | None = None
    # Saved answers: kept for a week, and capped well inside Neon's 0.5 GB free plan.
    cache_ttl_seconds: float = 7 * 24 * 3600.0
    cache_max_bytes: int = 50 * 1024 * 1024
    # Paid models stay off unless both are set: the switch AND a spending cap above zero.
    allow_paid_models: bool = False
    paid_spend_cap_usd: float = 0.0
    # The attempt log keeps only the most recent rows, so it cannot grow without bound.
    call_log_max_rows: int = 5000
    # Default limits for one session (later: one scan). A request can set lower or higher caps
    # when its session first appears.
    budget_max_requests: int = 50
    budget_max_tokens: int = 100_000
    budget_max_seconds: float = 600.0
    budget_max_concurrency: int = 2
    # Provider keys. A missing key just means that provider is "not configured" and skipped.
    groq_api_key: str | None = Field(default=None, repr=False)
    gemini_api_key: str | None = Field(default=None, repr=False)
    openrouter_api_key: str | None = Field(default=None, repr=False)
    # Free model names change often, so they are settings, not code. Check them against each
    # provider's current model list when keys are added.
    groq_model: str = "llama-3.1-8b-instant"
    gemini_model: str = "gemini-3.5-flash-lite"
    # Tried in this order; the first one that is still available answers.
    openrouter_free_models: str = (
        "google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free"
    )
    # Used only when paid models are switched on and there is room under the spending cap.
    openrouter_paid_model: str | None = None
    provider_timeout_seconds: float = 30.0
    # Unlocks the model-router endpoints. When unset, those endpoints stay locked for everyone.
    owner_token: str | None = Field(default=None, repr=False)
    # Neon can take several seconds to wake from idle; allow for that before saying "degraded".
    db_timeout_seconds: float = 10.0

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        return normalize_database_url(value)
