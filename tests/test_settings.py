"""Settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from radar.core.settings import Settings


def _settings(**overrides: str) -> Settings:
    values: dict[str, str] = {
        "database_url": "postgresql+psycopg://u:p@localhost:5433/radar",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_accepts_a_psycopg_url() -> None:
    assert _settings().database_url.startswith("postgresql+psycopg://")


def test_defaults_are_conservative() -> None:
    settings = _settings()
    assert settings.environment == "local"
    assert settings.log_level == "info"
    assert settings.crawler_contact is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost/radar",  # would silently select psycopg2
        "postgresql+psycopg2://u:p@localhost/radar",
        "sqlite:///radar.db",
        "postgres://u:p@localhost/radar",
    ],
)
def test_rejects_urls_that_would_pick_another_driver(url: str) -> None:
    with pytest.raises(ValidationError, match="psycopg"):
        _settings(database_url=url)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    # The variable is set in any real run, so it has to be cleared for the
    # absence to be what is under test.
    monkeypatch.delenv("RADAR_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_are_immutable() -> None:
    settings = _settings()
    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_rejects_an_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="staging")
