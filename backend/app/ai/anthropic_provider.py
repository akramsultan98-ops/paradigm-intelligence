"""Claude-backed extraction, over the Messages API.

A tool definition generated from the ``Extraction`` schema is used to force
structured output, so the prompt contract and the validation contract cannot
drift apart.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.ai.base import AIProvider, Extraction, ExtractionRequest
from app.ai.prompt import SYSTEM_PROMPT, build_user_prompt
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
TOOL_NAME = "record_extraction"
#: 529 is Anthropic's "overloaded" status; the rest are ordinary transients.
_RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
_MAX_ATTEMPTS = 3


def build_tool_schema() -> dict[str, Any]:
    """The tool's ``input_schema``, derived from the Pydantic model.

    Generating it keeps the model's output contract identical to what validation
    will accept. ``extractor`` is removed because the system fills it in — asking
    for it would invite the model to claim an identity.
    """
    schema = Extraction.model_json_schema()
    schema.pop("title", None)
    schema.get("properties", {}).pop("extractor", None)
    schema["additionalProperties"] = False
    return schema


class AnthropicProvider(AIProvider):
    """Live extraction through the Claude Messages API."""

    name = "anthropic"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        if not self.settings.anthropic_api_key:
            raise ValueError(
                "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY. "
                "Set it, or use AI_PROVIDER=rule_based for offline work."
            )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.settings.anthropic_base_url,
            timeout=self.settings.ai_timeout_seconds,
            headers={
                "x-api-key": self.settings.anthropic_api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        self._tool_schema = build_tool_schema()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request_body(self, request: ExtractionRequest) -> dict[str, Any]:
        return {
            "model": self.settings.anthropic_model,
            "max_tokens": self.settings.ai_max_output_tokens,
            "system": SYSTEM_PROMPT,
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": (
                        "Record the structured intelligence extracted from one source "
                        "document. Use UNKNOWN or null wherever the document provides "
                        "no evidence."
                    ),
                    "input_schema": self._tool_schema,
                }
            ],
            # Force the tool call: a prose reply would have to be parsed, and
            # parsing prose is how unvalidated data gets in.
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
            "messages": [
                {
                    "role": "user",
                    "content": build_user_prompt(
                        url=request.url,
                        title=request.title,
                        publisher=request.publisher,
                        published_at=(
                            request.published_at.isoformat() if request.published_at else None
                        ),
                        source_type=request.source_type.value,
                        content=request.content,
                    ),
                }
            ],
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any] | None:
        """POST with bounded retries on transient failures."""
        backoff = 1.0
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.post("/v1/messages", json=body)
            except httpx.HTTPError as exc:
                logger.warning(
                    "anthropic request failed", extra={"attempt": attempt, "error": str(exc)}
                )
                if attempt == _MAX_ATTEMPTS:
                    return None
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "anthropic transient error, retrying",
                        extra={"status": response.status_code, "attempt": attempt},
                    )
                else:
                    logger.error(
                        "anthropic request rejected",
                        extra={
                            "status": response.status_code,
                            "body": response.text[:500],
                        },
                    )
                    return None
            time.sleep(backoff)
            backoff *= 2
        return None

    @staticmethod
    def _tool_input(payload: dict[str, Any]) -> dict[str, Any] | None:
        for block in payload.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                tool_input = block.get("input")
                if isinstance(tool_input, dict):
                    return tool_input
        return None

    def extract(self, request: ExtractionRequest) -> Extraction | None:
        """Extract, validate, and return ``None`` on anything unusable.

        A response that does not validate is logged and dropped. It is never
        partially salvaged — a half-understood extraction is how a wrong company
        ends up attached to a real signal.
        """
        payload = self._post(self._request_body(request))
        if payload is None:
            return None

        tool_input = self._tool_input(payload)
        if tool_input is None:
            logger.error(
                "anthropic response contained no tool_use block",
                extra={"url": request.url, "stop_reason": payload.get("stop_reason")},
            )
            return None

        try:
            extraction = Extraction.model_validate(tool_input)
        except Exception as exc:
            logger.error(
                "extraction failed schema validation; discarding",
                extra={"url": request.url, "error": str(exc)[:500]},
            )
            return None

        extraction.extractor = f"{self.name}:{self.settings.anthropic_model}"
        return extraction
