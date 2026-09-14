"""Declarative base and shared column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Predictable constraint names, so migrations can reference them by name
#: instead of relying on whatever the database happened to generate.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_col(enum_cls: type[StrEnum], ck_name: str) -> Enum:
    """A ``VARCHAR`` + ``CHECK`` column for a string enum.

    Native PostgreSQL ``ENUM`` types are avoided deliberately: adding a member
    to one requires ``ALTER TYPE``, which cannot run inside a transactional
    migration. A checked ``VARCHAR`` makes the same change an ordinary
    constraint swap.

    ``ck_name`` must be unique per table, since two columns can share an enum
    (``classification`` and ``previous_classification``, for instance).
    """
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=48,
        name=ck_name,
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
