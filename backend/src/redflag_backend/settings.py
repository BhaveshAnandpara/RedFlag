from pydantic import field_validator
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

    database_url: str
    frontend_origin: str
    app_version: str = "0.1.0"
    commit_sha: str | None = None
    # Unlocks the model-router endpoints. When unset, those endpoints stay locked for everyone.
    owner_token: str | None = None
    # Neon can take several seconds to wake from idle; allow for that before saying "degraded".
    db_timeout_seconds: float = 10.0

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        return normalize_database_url(value)
