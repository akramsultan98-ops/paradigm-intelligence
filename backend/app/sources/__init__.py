"""Source adapter framework.

A small contract (``SourceAdapter``) plus a registry that builds adapters from
``config/sources.json``. Adding a feed is configuration; adding a genuinely new
retrieval mechanism is one class.
"""

from app.sources.base import RawDocument, SourceAdapter, SourceConfig
from app.sources.jsonl import JsonlFileSourceAdapter
from app.sources.registry import (
    ADAPTERS,
    build_adapter,
    load_source_configs,
    load_sources,
)
from app.sources.rss import RssSourceAdapter

__all__ = [
    "ADAPTERS",
    "JsonlFileSourceAdapter",
    "RawDocument",
    "RssSourceAdapter",
    "SourceAdapter",
    "SourceConfig",
    "build_adapter",
    "load_source_configs",
    "load_sources",
]
