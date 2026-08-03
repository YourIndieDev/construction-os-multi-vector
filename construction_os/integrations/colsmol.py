"""Optional ColSmol service connectivity for the multi-vector MVP."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
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
    embedding_timeout_seconds: float = 180.0


class ColSmolEmbeddingError(RuntimeError):
    """Raised when the optional ColSmol service cannot produce an embedding."""


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = (os.getenv(name) or str(default)).strip()
    try:
        return max(float(raw), minimum)
    except ValueError:
        return default


def load_colsmol_settings() -> ColSmolSettings:
    return ColSmolSettings(
        enabled=_env_bool("CONSTRUCTION_OS_MULTIVECTOR_ENABLED", False),
        url=(os.getenv("COLSMOL_URL") or "http://colsmol:8000").rstrip("/"),
        timeout_seconds=_env_float("COLSMOL_TIMEOUT_SECONDS", 10.0),
        embedding_timeout_seconds=_env_float(
            "COLSMOL_EMBED_TIMEOUT_SECONDS",
            180.0,
        ),
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


async def embed_colsmol_image(
    image_path: str | Path,
    *,
    settings: Optional[ColSmolSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Upload one image to ColSmol and return its validated multi-vector matrix."""
    cfg = settings or load_colsmol_settings()
    if not cfg.enabled:
        raise ColSmolEmbeddingError("Multi-vector image embedding is disabled")

    path = Path(image_path)
    if not path.is_file():
        raise ColSmolEmbeddingError(f"Image file does not exist: {path}")

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(cfg.embedding_timeout_seconds)
    )
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    try:
        with path.open("rb") as image_file:
            response = await active_client.post(
                f"{cfg.url}/embed/image",
                files={"file": (path.name, image_file, media_type)},
            )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise ColSmolEmbeddingError(
            f"ColSmol image embedding failed for {path.name}: {exc}"
        ) from exc
    finally:
        if owns_client:
            await active_client.aclose()

    vectors = body.get("vectors")
    dimension = int(body.get("dimension") or 0)
    vector_count = int(body.get("vector_count") or 0)
    if (
        not isinstance(vectors, list)
        or not vectors
        or vector_count != len(vectors)
        or dimension < 1
        or any(not isinstance(vector, list) or len(vector) != dimension for vector in vectors)
    ):
        raise ColSmolEmbeddingError(
            f"ColSmol returned an invalid multi-vector payload for {path.name}"
        )

    return body
