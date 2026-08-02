"""Conservative capability checks for attaching drawing images to chat models."""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from construction_os.ai.models import Model, model_manager


_VISION_MODEL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "openai": (
        re.compile(r"^(gpt-4(?:o|\.1)|gpt-5|o[134])", re.IGNORECASE),
    ),
    "anthropic": (
        re.compile(r"^claude-(?:3|3\.5|3\.7|4)", re.IGNORECASE),
    ),
    "google": (
        re.compile(r"^(?:gemini|models/gemini)", re.IGNORECASE),
    ),
    "google-generative-ai": (
        re.compile(r"^(?:gemini|models/gemini)", re.IGNORECASE),
    ),
    "mistral": (
        re.compile(r"^(?:pixtral|mistral-(?:small|medium|large)-.*vision)", re.IGNORECASE),
    ),
    "ollama": (
        re.compile(
            r"(?:llava|bakllava|moondream|qwen(?:2|2\.5)?-?vl|gemma3|minicpm-v)",
            re.IGNORECASE,
        ),
    ),
    "groq": (
        re.compile(r"(?:vision|llama-3\.2-.*vision)", re.IGNORECASE),
    ),
}

_TEXT_ONLY_PATTERNS = (
    re.compile(r"embedding", re.IGNORECASE),
    re.compile(r"whisper", re.IGNORECASE),
    re.compile(r"tts", re.IGNORECASE),
)


def _csv_env(name: str) -> set[str]:
    return {
        value.strip()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    }


def _normalized_provider(value: Optional[str]) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _matches(model_name: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(model_name) for pattern in patterns)


async def resolve_chat_vision_capability(
    model_id: Optional[str],
) -> dict[str, Any]:
    """Resolve whether the selected chat model can safely accept image blocks.

    The registry currently has no explicit vision flag, so unknown models are treated
    as unsupported instead of risking a failed chat request. Operators can override
    individual registry IDs through CONSTRUCTION_OS_VISION_MODEL_IDS or
    CONSTRUCTION_OS_TEXT_ONLY_MODEL_IDS.
    """
    resolved_id = str(model_id or "").strip() or None
    if resolved_id is None:
        defaults = await model_manager.get_defaults()
        resolved_id = defaults.default_chat_model

    if not resolved_id:
        return {
            "model_id": None,
            "model_name": None,
            "provider": None,
            "supported": False,
            "reason": "chat_model_unconfigured",
        }

    explicit_vision = _csv_env("CONSTRUCTION_OS_VISION_MODEL_IDS")
    explicit_text_only = _csv_env("CONSTRUCTION_OS_TEXT_ONLY_MODEL_IDS")
    if resolved_id in explicit_text_only:
        return {
            "model_id": resolved_id,
            "model_name": None,
            "provider": None,
            "supported": False,
            "reason": "explicit_text_only_override",
        }
    if resolved_id in explicit_vision:
        return {
            "model_id": resolved_id,
            "model_name": None,
            "provider": None,
            "supported": True,
            "reason": "explicit_vision_override",
        }

    model = await Model.get(resolved_id)
    if not model:
        return {
            "model_id": resolved_id,
            "model_name": None,
            "provider": None,
            "supported": False,
            "reason": "model_record_not_found",
        }

    model_name = str(model.name or "").strip()
    provider = _normalized_provider(model.provider)
    if model.type != "language":
        return {
            "model_id": resolved_id,
            "model_name": model_name,
            "provider": provider,
            "supported": False,
            "reason": "model_is_not_language",
        }
    if _matches(model_name, _TEXT_ONLY_PATTERNS):
        return {
            "model_id": resolved_id,
            "model_name": model_name,
            "provider": provider,
            "supported": False,
            "reason": "known_text_only_model",
        }

    patterns = _VISION_MODEL_PATTERNS.get(provider, ())
    supported = bool(patterns and _matches(model_name, patterns))
    return {
        "model_id": resolved_id,
        "model_name": model_name,
        "provider": provider,
        "supported": supported,
        "reason": "known_vision_model" if supported else "vision_capability_unconfirmed",
    }


def is_multimodal_compatibility_error(exc: BaseException) -> bool:
    """Return True only for failures that plausibly reject image message blocks."""
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "image_url",
        "image input",
        "image content",
        "vision",
        "multimodal",
        "unsupported content",
        "content block",
        "base64 image",
        "does not support images",
    )
    return any(marker in text for marker in markers)
