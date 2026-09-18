"""Application settings, loaded from the environment.

Configuration is environment-only by design (docs/07-security-privacy.md): no
secret is ever read from a committed file, and startup fails loudly when a
required value is missing rather than falling back to a default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "production"]
LogLevel = Literal["debug", "info", "warning", "error"]


class Settings(BaseSettings):
    """Runtime configuration.

    Every field is read from a ``RADAR_``-prefixed environment variable, or from
    a local ``.env`` file during development.
    """

    model_config = SettingsConfigDict(
        env_prefix="RADAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: str = Field(
        description="SQLAlchemy URL for the primary PostgreSQL database.",
    )
    test_database_url: str | None = Field(
        default=None,
        description="SQLAlchemy URL used by the test suite. Never the primary database.",
    )
    environment: Environment = "local"
    log_level: LogLevel = "info"
    crawler_contact: str | None = Field(
        default=None,
        description=(
            "Contact address advertised in the User-Agent of outbound fetches. "
            "Required before ingestion runs so source operators can reach us."
        ),
    )

    @field_validator("database_url", "test_database_url")
    @classmethod
    def _normalise_driver(cls, value: str | None) -> str | None:
        """Pin the URL to psycopg (v3), the only PostgreSQL driver installed.

        Hosted PostgreSQL providers (Neon, Render, Supabase, Heroku) all hand out
        ``postgresql://``, which SQLAlchemy resolves to psycopg2 and fails at
        connect time with an ImportError that says nothing useful. Rather than
        making every developer and every deployment secret edit the scheme by
        hand, a bare ``postgresql://`` is upgraded here.

        An explicitly wrong driver is still an error: asking for psycopg2 or a
        different database is a mistake worth surfacing, not guessing at.
        """
        if value is None:
            return None
        if value.startswith("postgresql+psycopg://"):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)

        scheme = value.split("://", 1)[0] if "://" in value else value
        raise ValueError(
            "database URLs must be PostgreSQL over the psycopg (v3) driver: pass "
            f"'postgresql://…' or 'postgresql+psycopg://…', got '{scheme}://'"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
