"""Test fixtures.

The suite runs against a real PostgreSQL with pgvector, and builds its schema by
running the Alembic migrations rather than ``metadata.create_all``. That way the
migrations themselves are what is under test: a model change that never made it
into a migration fails here instead of in production.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from radar.core.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str | None:
    """The test database URL, from the environment or from .env.

    Read through Settings rather than os.environ. Reading the environment
    directly meant a developer with a perfectly good .env saw every database
    test skip in silence, and a green "86 passed" that had never touched a
    database — the idempotency guarantee included.
    """
    try:
        return Settings().test_database_url  # type: ignore[call-arg]
    except ValidationError:
        return None


def pytest_report_header() -> str:
    """Say up front whether the database tests will actually run.

    A skip is invisible under -q, so without this line a misconfigured
    environment looks exactly like a passing one.
    """
    url = _test_database_url()
    if not url:
        return (
            "database tests: SKIPPED - set RADAR_TEST_DATABASE_URL in .env or the "
            "environment to run them"
        )
    target = url.rsplit("@", 1)[-1]  # never print credentials
    return f"database tests: enabled against {target}"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    if not url:
        pytest.skip("RADAR_TEST_DATABASE_URL is not set; skipping database tests")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    """A migrated, empty database for the whole test session."""
    eng = create_engine(database_url, pool_pre_ping=True, future=True)

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)

    # Start from a known-empty schema so a half-migrated database from an
    # interrupted run cannot make the suite pass or fail spuriously.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    Tests therefore share one migrated database without leaking rows into one
    another, and no test needs to clean up after itself.
    """
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False, future=True)
    try:
        yield sess
    finally:
        sess.close()
        # A test that asserts on an IntegrityError leaves the transaction already
        # deassociated; rolling it back again only produces a warning.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def vector_available(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
        )


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve any hostname to a public address.

    Tests that exercise fetchers should not depend on the network: real lookups
    make the suite slow, and make it fail in sandboxes with no DNS. Tests that
    are *about* address safety do their own resolution instead.
    """

    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
