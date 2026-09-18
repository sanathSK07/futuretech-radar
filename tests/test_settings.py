"""Settings validation."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from radar.core.settings import Settings


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the process environment from every test in this module.

    These tests assert on what Settings does with its own inputs: defaults,
    validation, immutability. Any RADAR_ variable in the shell quietly becomes
    one of those inputs, and the assertion stops testing what it says it tests.
    CI sets RADAR_ENVIRONMENT=ci in the workflow env, so the defaults test
    failed there while passing on every developer machine — the same shape of
    bug as the database URL test that an ambient variable used to mask.
    """
    for name in list(os.environ):
        if name.startswith("RADAR_"):
            monkeypatch.delenv(name, raising=False)


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
        "postgresql+psycopg2://u:p@localhost/radar",
        "sqlite:///radar.db",
        "mysql://u:p@localhost/radar",
        "postgres://u:p@localhost/radar",  # the old Heroku alias, not a driver we have
    ],
)
def test_rejects_an_explicitly_wrong_driver(url: str) -> None:
    with pytest.raises(ValidationError, match="psycopg"):
        _settings(database_url=url)


def test_a_bare_postgresql_url_is_upgraded_to_psycopg() -> None:
    """Neon, Render and Supabase all hand out bare postgresql:// URLs."""
    settings = _settings(
        database_url="postgresql://user:pw@ep-cool-name.aws.neon.tech/radar?sslmode=require"
    )
    assert settings.database_url == (
        "postgresql+psycopg://user:pw@ep-cool-name.aws.neon.tech/radar?sslmode=require"
    )


def test_query_parameters_survive_the_upgrade() -> None:
    settings = _settings(
        database_url="postgresql://u:p@host/db?sslmode=require&channel_binding=require"
    )
    assert settings.database_url.endswith("?sslmode=require&channel_binding=require")


def test_database_url_is_required() -> None:
    """The autouse fixture above is what makes the absence real."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_are_immutable() -> None:
    settings = _settings()
    with pytest.raises(ValidationError):
        settings.environment = "production"  # type: ignore[misc]


def test_rejects_an_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        _settings(environment="staging")
