"""Source adapter framework.

A small contract (``SourceAdapter``) plus a registry that builds adapters from
``config/sources.json``. Adding a feed is configuration; adding a genuinely new
retrieval mechanism is one class.
"""

from app.sources.base import RawDocument, SourceAdapter, SourceConfig
from app.sources.contacts import (
    ContactPageAdapter,
    ContactSourceAdapter,
    DiscoveredContact,
    extract_contacts_from_html,
)
from app.sources.http import FetchClient, RateLimiter
from app.sources.jsonl import JsonlFileSourceAdapter
from app.sources.registry import (
    ADAPTERS,
    ALL_ADAPTER_NAMES,
    CONTACT_ADAPTERS,
    apply_enabled_allowlist,
    build_adapter,
    build_contact_adapter,
    load_contact_sources,
    load_source_configs,
    load_sources,
)
from app.sources.rss import RssSourceAdapter

__all__ = [
    "ADAPTERS",
    "ALL_ADAPTER_NAMES",
    "CONTACT_ADAPTERS",
    "ContactPageAdapter",
    "ContactSourceAdapter",
    "DiscoveredContact",
    "FetchClient",
    "JsonlFileSourceAdapter",
    "RateLimiter",
    "RawDocument",
    "RssSourceAdapter",
    "SourceAdapter",
    "SourceConfig",
    "apply_enabled_allowlist",
    "build_adapter",
    "build_contact_adapter",
    "extract_contacts_from_html",
    "load_contact_sources",
    "load_source_configs",
    "load_sources",
]
