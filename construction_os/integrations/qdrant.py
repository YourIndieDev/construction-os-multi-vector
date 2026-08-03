"""Optional Qdrant connectivity and configuration for the multi-vector MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx


DEFAULT_MULTIVECTOR_COLLECTION = "construction_os_drawing_multivector_v1"
DEFAULT_MULTIVECTOR_VECTOR_SIZE = 128


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or str(default)).strip()
    try:
        return max(int(raw), minimum)
    except ValueError:
        return default


@dataclass(frozen=True)
class QdrantSettings:
    enabled: bool
    url: str
    timeout_seconds: float
    api_key: Optional[str]
    collection_name: str = DEFAULT_MULTIVECTOR_COLLECTION
    vector_size: int = DEFAULT_MULTIVECTOR_VECTOR_SIZE


def load_qdrant_settings() -> QdrantSettings:
    """Resolve Qdrant settings without requiring Qdrant to be available."""
    raw_timeout = (os.getenv("QDRANT_TIMEOUT_SECONDS") or "5").strip()
    try:
        timeout_seconds = max(float(raw_timeout), 0.1)
    except ValueError:
        timeout_seconds = 5.0

    return QdrantSettings(
        enabled=_env_bool("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", False),
        url=(os.getenv("QDRANT_URL") or "http://qdrant:6333").rstrip("/"),
        timeout_seconds=timeout_seconds,
        api_key=(os.getenv("QDRANT_API_KEY") or "").strip() or None,
        collection_name=(
            os.getenv("QDRANT_MULTIVECTOR_COLLECTION")
            or DEFAULT_MULTIVECTOR_COLLECTION
        ).strip(),
        vector_size=_env_int(
            "QDRANT_MULTIVECTOR_VECTOR_SIZE",
            DEFAULT_MULTIVECTOR_VECTOR_SIZE,
        ),
    )


def qdrant_headers(settings: QdrantSettings) -> Optional[dict[str, str]]:
    """Return authentication headers only when an API key is configured."""
    return {"api-key": settings.api_key} if settings.api_key else None


async def check_qdrant_health(
    settings: Optional[QdrantSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Return health information without raising when Qdrant is unavailable."""
    cfg = settings or load_qdrant_settings()
    if not cfg.enabled:
        return {
            "enabled": False,
            "available": False,
            "status": "disabled",
            "url": cfg.url,
        }

    headers = qdrant_headers(cfg)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=cfg.timeout_seconds)

    try:
        response = await active_client.get(f"{cfg.url}/readyz", headers=headers)
        response.raise_for_status()
        return {
            "enabled": True,
            "available": True,
            "status": "ready",
            "url": cfg.url,
            "detail": response.text.strip() or "ready",
        }
    except httpx.HTTPError as exc:
        return {
            "enabled": True,
            "available": False,
            "status": "unavailable",
            "url": cfg.url,
            "detail": str(exc),
        }
    finally:
        if owns_client:
            await active_client.aclose()
