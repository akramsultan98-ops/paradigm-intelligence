"""Shared response pieces."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for models read directly off SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """A page of results."""

    items: list[T]
    total: int | None = Field(
        default=None, description="Total matching rows, when it was counted."
    )
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: bool
    ai_provider: str
    #: True when the configured extractor is the deterministic non-AI one, so a
    #: monitoring check can notice a production box running in fallback mode.
    rule_based_fallback: bool


class MessageResponse(BaseModel):
    message: str
    detail: str | None = None


class TimestampedResponse(BaseModel):
    generated_at: datetime
