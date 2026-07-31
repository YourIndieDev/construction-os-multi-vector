"""Query embedding client for the optional ColSmol service."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from construction_os.integrations.colsmol import (
    ColSmolEmbeddingError,
    ColSmolSettings,
    load_colsmol_settings,
)


async def embed_colsmol_query(
    text: str,
    *,
    settings: Optional[ColSmolSettings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Embed one text query and validate its multi-vector matrix."""
    query = text.strip()
    if not query:
        raise ColSmolEmbeddingError("Query text is required")

    cfg = settings or load_colsmol_settings()
    if not cfg.enabled:
        raise ColSmolEmbeddingError("Multi-vector query embedding is disabled")

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(cfg.embedding_timeout_seconds)
    )
    try:
        response = await active_client.post(
            f"{cfg.url}/embed/query",
            json={"text": query},
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ColSmolEmbeddingError(
            f"ColSmol query embedding failed: {exc}"
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
        or any(
            not isinstance(vector, list) or len(vector) != dimension
            for vector in vectors
        )
    ):
        raise ColSmolEmbeddingError(
            "ColSmol returned an invalid query multi-vector payload"
        )
    return body
