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
    def _require_psycopg_driver(cls, value: str | None) -> str | None:
        """Reject URLs that would silently fall back to an unavailable driver.

        SQLAlchemy defaults ``postgresql://`` to psycopg2, which this project does
        not install; the resulting ImportError at connect time is far less clear
        than failing here.
        """
        if value is None:
            return None
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError(
                "database URLs must use the psycopg (v3) driver, "
                f"i.e. start with 'postgresql+psycopg://', got: {value.split('://')[0]}://"
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
