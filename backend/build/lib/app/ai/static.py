"""A provider that returns an extraction it was given.

This is how an analyst-verified signal enters the system. The point is that it
reuses the *entire* pipeline — relevance gate, source deduplication, company
resolution, signal deduplication, deterministic scoring — rather than a parallel
code path that would drift from it.

It is not a fake AI provider: it performs no extraction and claims none. The
``extractor`` field records who supplied the structure, so an analyst-entered
signal is never mistaken for an automated one.
"""

from __future__ import annotations

from app.ai.base import AIProvider, Extraction, ExtractionRequest


class StaticExtractionProvider(AIProvider):
    """Yields a pre-built, already-validated ``Extraction``."""

    name = "static"

    def __init__(self, extraction: Extraction, *, extractor: str = "analyst"):
        self.extraction = extraction.model_copy(update={"extractor": extractor})

    def extract(self, request: ExtractionRequest) -> Extraction | None:
        return self.extraction
