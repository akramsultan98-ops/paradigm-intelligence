"""Provider selection."""

from __future__ import annotations

import logging

from app.ai.base import AIProvider
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def get_provider(settings: Settings | None = None) -> AIProvider:
    """Build the configured extraction provider.

    ``rule_based`` logs a warning on purpose: it is fine for development and
    tests, and misleading in production, so a production process running on it
    should say so in its logs.
    """
    settings = settings or get_settings()

    if settings.ai_provider == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)

    from app.ai.rule_based import RuleBasedProvider

    logger.warning(
        "using the deterministic rule-based extractor; this is not AI extraction "
        "and should not be used for production ranking",
        extra={"ai_provider": settings.ai_provider},
    )
    return RuleBasedProvider()
