"""Filtered Qdrant MaxSim search for drawing multi-vectors."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Sequence

import httpx

from construction_os.drawing.multivector_store import AssetKind
from construction_os.integrations.qdrant import (
    QdrantSettings,
    load_qdrant_settings,
    qdrant_headers,
)


class MultiVectorSearchError(RuntimeError):
    """Raised when an explicit multi-vector search cannot be completed."""


@dataclass(frozen=True)
class MultiVectorSearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]


class QdrantMultiVectorSearch:
    """Small query client for the versioned drawing multi-vector collection."""

    def __init__(
        self,
        settings: Optional[QdrantSettings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or load_qdrant_settings()
        self.client = client

    def _require_enabled(self) -> None:
        if not self.settings.enabled:
            raise MultiVectorSearchError("Multi-vector search is disabled")

    @asynccontextmanager
    async def _client_scope(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
            return
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            yield client

    async def search(
        self,
        *,
        query_vectors: Sequence[Sequence[float]],
        project_id: str,
        source_ids: Optional[Sequence[str]] = None,
        asset_kinds: Optional[Sequence[AssetKind]] = None,
        limit: int = 20,
        score_threshold: Optional[float] = None,
    ) -> list[MultiVectorSearchHit]:
        """Query MaxSim points while enforcing project and optional source filters."""
        self._require_enabled()
        if not project_id.strip():
            raise ValueError("project_id is required")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        vectors = [list(vector) for vector in query_vectors]
        if not vectors:
            raise ValueError("query_vectors must contain at least one vector")
        if any(len(vector) != self.settings.vector_size for vector in vectors):
            raise ValueError(
                f"Every query vector must have dimension {self.settings.vector_size}"
            )

        normalized_sources = sorted(
            {source_id.strip() for source_id in (source_ids or []) if source_id.strip()}
        )
        normalized_kinds = sorted(set(asset_kinds or []))

        must: list[dict[str, Any]] = [
            {"key": "project_id", "match": {"value": project_id}}
        ]
        if normalized_sources:
            must.append(
                {"key": "source_id", "match": {"any": normalized_sources}}
            )
        if normalized_kinds:
            must.append(
                {"key": "asset_kind", "match": {"any": normalized_kinds}}
            )

        body: dict[str, Any] = {
            "query": vectors,
            "filter": {"must": must},
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if score_threshold is not None:
            body["score_threshold"] = float(score_threshold)

        async with self._client_scope() as client:
            response = await client.post(
                f"{self._collection_url}/points/query",
                headers=qdrant_headers(self.settings),
                json=body,
            )
            try:
                response.raise_for_status()
                response_body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise MultiVectorSearchError(
                    f"Qdrant multi-vector search failed: {exc}"
                ) from exc

        raw_result = response_body.get("result") or {}
        rows = raw_result.get("points") if isinstance(raw_result, dict) else raw_result
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise MultiVectorSearchError("Qdrant returned an invalid query result")

        hits: list[MultiVectorSearchHit] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            payload = row.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            hits.append(
                MultiVectorSearchHit(
                    point_id=str(row.get("id") or ""),
                    score=float(row.get("score") or 0.0),
                    payload=payload,
                )
            )
        return hits

    @property
    def _collection_url(self) -> str:
        return f"{self.settings.url}/collections/{self.settings.collection_name}"
