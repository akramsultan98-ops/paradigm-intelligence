"""AI extraction behind a provider abstraction.

AI turns source prose into structured evidence. It does **not** decide the
ranking — that is ``app.scoring``. See ``docs/ARCHITECTURE.md``.
"""

from app.ai.base import AIProvider, Extraction, ExtractionFactors, ExtractionRequest
from app.ai.factory import get_provider

__all__ = [
    "AIProvider",
    "Extraction",
    "ExtractionFactors",
    "ExtractionRequest",
    "get_provider",
]
