"""The adapter contract.

Deliberately tiny. Everything an adapter must do is: yield documents. Persistence,
deduplication, extraction and scoring are the pipeline's job, so a new adapter
never has to know about any of them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.enums import SourceType


@dataclass(slots=True)
class RawDocument:
    """One retrieved document, before any interpretation."""

    url: str
    title: str | None
    content: str
    source_type: SourceType
    publisher: str | None = None
    published_at: datetime | None = None
    #: Set when the adapter already knows which company this is about — a company
    #: newsroom, for instance. Passed to the extractor so it need not guess.
    company_hint: str | None = None
    #: Confidence in the *source*, not the content. Configured per feed.
    confidence: float = 0.5
    adapter_key: str | None = None

    def __post_init__(self) -> None:
        self.url = self.url.strip()
        if not self.url:
            raise ValueError("RawDocument requires a url")
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass(slots=True)
class SourceConfig:
    """One entry from ``config/sources.json``."""

    key: str
    adapter: str
    source_type: SourceType
    publisher: str | None = None
    enabled: bool = True
    confidence: float = 0.5
    company_hint: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Fetches documents from one configured source."""

    def __init__(self, config: SourceConfig):
        self.config = config

    @property
    def key(self) -> str:
        return self.config.key

    @property
    def source_type(self) -> SourceType:
        return self.config.source_type

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> Iterator[RawDocument]:
        """Yield documents published at or after ``since``.

        Implementations should yield lazily and must not raise for a single bad
        entry — skip it and carry on, so one malformed item cannot lose a whole
        feed.
        """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.key!r} {self.source_type}>"
