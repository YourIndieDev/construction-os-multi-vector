"""Minimal optional Qdrant connectivity for the multi-vector MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class QdrantSettings:
    enabled: bool
    url: str
    timeout_seconds: float
    api_key: Optional[str]


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
    )


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

    headers = {"api-key": cfg.api_key} if cfg.api_key else None
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
