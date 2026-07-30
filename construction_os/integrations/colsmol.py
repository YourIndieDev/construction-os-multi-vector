"""Optional ColSmol service connectivity for the multi-vector MVP."""

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
class ColSmolSettings:
    enabled: bool
    url: str
    timeout_seconds: float


def load_colsmol_settings() -> ColSmolSettings:
    raw_timeout = (os.getenv("COLSMOL_TIMEOUT_SECONDS") or "10").strip()
    try:
        timeout_seconds = max(float(raw_timeout), 0.1)
    except ValueError:
        timeout_seconds = 10.0

    return ColSmolSettings(
        enabled=_env_bool("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", False),
        url=(os.getenv("COLSMOL_URL") or "http://colsmol:8000").rstrip("/"),
        timeout_seconds=timeout_seconds,
    )


async def check_colsmol_health(
    settings: Optional[ColSmolSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Return model-service health without raising or blocking the existing app."""
    cfg = settings or load_colsmol_settings()
    if not cfg.enabled:
        return {
            "enabled": False,
            "available": False,
            "status": "disabled",
            "url": cfg.url,
        }

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=cfg.timeout_seconds)
    try:
        response = await active_client.get(f"{cfg.url}/health")
        response.raise_for_status()
        detail = response.json()
        ready = bool(detail.get("ready"))
        return {
            "enabled": True,
            "available": ready,
            "status": str(detail.get("status") or ("ready" if ready else "loading")),
            "url": cfg.url,
            "detail": detail,
        }
    except (httpx.HTTPError, ValueError) as exc:
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
