"""Test fixtures.

Unit tests need no database. Integration tests need a real PostgreSQL, because
the schema leans on ``JSONB``, ``CHECK`` constraints and partial-index behaviour
that SQLite does not share — testing against SQLite would prove the wrong thing.

Set ``TEST_DATABASE_URL`` to enable them. Without it they skip cleanly, so
``pytest`` is always runnable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# This must happen before any app module reads settings, and conftest is imported
# before the test modules are.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_DATABASE_URL to a PostgreSQL database to run integration tests",
)


@pytest.fixture(scope="session")
def db_engine():
    """Create the schema once for the whole session."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")

    from app.db import get_engine
    from app.models import Base

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_db(request) -> Iterator[None]:
    """Truncate between tests.

    Truncation rather than a rolled-back transaction: the pipeline opens its own
    sessions and commits them, so a test-owned transaction would not contain it.
    """
    if "db_engine" not in request.fixturenames:
        yield
        return

    from sqlalchemy import text

    from app.models import Base

    engine = request.getfixturevalue("db_engine")
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def session(db_engine) -> Iterator:
    from app.db import get_sessionmaker

    db_session = get_sessionmaker()()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture
def client(db_engine):
    """A TestClient against the real app and the test database."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def rule_based_provider():
    from app.ai.rule_based import RuleBasedProvider

    return RuleBasedProvider()
