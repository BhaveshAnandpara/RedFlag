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
    groq_model: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-3.5-flash-lite"
    # Tried in this order; the first one that is still available answers.
    openrouter_free_models: str = (
        "google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free"
    )
    # Used only when paid models are switched on and there is room under the spending cap.
    openrouter_paid_model: str | None = None
    provider_timeout_seconds: float = 30.0
    # The demo bots' own model keys, kept apart from the router's keys above so the bots'
    # free-tier quota and Redflag's never compete. Keys from the same account would share one
    # quota, so these should come from other accounts or projects.
    bot_groq_api_key: str | None = Field(default=None, repr=False)
    bot_gemini_api_key: str | None = Field(default=None, repr=False)
    bot_openrouter_api_key: str | None = Field(default=None, repr=False)
    bot_groq_model: str = "openai/gpt-oss-20b"
    bot_gemini_model: str = "gemini-3.5-flash-lite"
    bot_openrouter_free_models: str = (
        "google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free"
    )
    # The order the bots' models are tried in. Gemini first: Groq's gpt-oss mistakes the bots'
    # tool format for its own tool calling, and OpenRouter's free models are rate-limited.
    bot_provider_order: str = "gemini,groq,openrouter"
    # Hard limits for one scan, so a scan cannot run away with the bots' quota.
    bot_budget_max_requests: int = 150
    bot_budget_max_tokens: int = 300_000
    bot_budget_max_seconds: float = 1800.0
    bot_budget_max_concurrency: int = 1
    # Hard limits for the AI judge in one scan. The judge runs on Redflag's own keys and models
    # (the ones above), so it never draws on the bots' quota.
    judge_budget_max_requests: int = 200
    # Below this many labeled results, accuracy numbers are called a small sample.
    judge_accuracy_min_sample: int = 20
    judge_budget_max_tokens: int = 200_000
    judge_budget_max_seconds: float = 1800.0
    # The setup chat, the supervisor and the test generator: how much of Redflag's own model
    # quota one setup may use, and how long the interview and the uploads may be.
    setup_budget_max_requests: int = 60
    setup_budget_max_tokens: int = 150_000
    setup_budget_max_seconds: float = 3600.0
    setup_chat_max_messages: int = 30
    setup_max_followups: int = 8
    setup_file_max_bytes: int = 20_000
    setup_file_max_count: int = 5
    # Multi-turn attacks: the most turns in one conversation, and the attacker AI's own limits
    # for one run (it uses Redflag's own model keys, apart from the judge's budget).
    multi_turn_max_turns: int = 4
    attacker_budget_max_requests: int = 100
    attacker_budget_max_tokens: int = 200_000
    attacker_budget_max_seconds: float = 1800.0
    # The quick scan's hello check: how many one owner may make in a window, so it cannot be
    # used to hammer someone's server.
    quick_checks_per_window: int = 20
    quick_check_window_seconds: float = 600.0
    # The most tests one setup version may hold (generated tests plus attack variations).
    setup_max_tests: int = 200
    # The most requests one run may send to the user's own endpoint.
    run_max_endpoint_requests: int = 150
    # Redflag's own public host name (for example redflag-xyz.onrender.com). A bot endpoint that
    # points at it is refused, so Redflag cannot be aimed at itself.
    public_backend_host: str | None = None
    # A running scan with no progress for this long is treated as interrupted.
    scan_stale_seconds: float = 300.0
    # Free tiers allow only a few requests a minute. When every model is rate-limited, a scan
    # pauses (at least this long, at most the max) and tries again, a few times, before it gives
    # up on that test and records an error that says why.
    scan_rate_limit_wait_seconds: float = 20.0
    scan_rate_limit_max_wait_seconds: float = 70.0
    scan_rate_limit_retries: int = 3
    # Unlocks the model-router endpoints. When unset, those endpoints stay locked for everyone.
    owner_token: str | None = Field(default=None, repr=False)
    # Neon can take several seconds to wake from idle; allow for that before saying "degraded".
    db_timeout_seconds: float = 10.0

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        return normalize_database_url(value)
