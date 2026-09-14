"""Database engine and session plumbing."""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@functools.lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-wide engine.

    ``pool_pre_ping`` matters here: the ingestion CLI holds a connection across
    slow network fetches, and a managed PostgreSQL will happily close it.
    """
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        future=True,
    )


@functools.lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency.

    Read paths do not need a transaction; write paths commit explicitly in the
    service layer, so this only guarantees the session is closed.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> bool:
    """Cheap readiness probe."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
