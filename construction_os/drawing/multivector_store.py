"""Qdrant collection and storage primitives for drawing multi-vectors."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal, Optional, Sequence
from uuid import NAMESPACE_URL, uuid5

import httpx

from construction_os.integrations.qdrant import (
    QdrantSettings,
    load_qdrant_settings,
    qdrant_headers,
)


MULTIVECTOR_PAYLOAD_SCHEMA_VERSION = 1
AssetKind = Literal["page", "grid_crop", "region_crop"]

PAYLOAD_INDEXES: dict[str, str] = {
    "project_id": "keyword",
    "source_id": "keyword",
    "run_id": "keyword",
    "asset_kind": "keyword",
    "page_index": "integer",
    "schema_version": "integer",
}


class MultiVectorStoreError(RuntimeError):
    """Base error for explicit multi-vector storage failures."""


class MultiVectorCollectionMismatch(MultiVectorStoreError):
    """Raised when an existing collection does not match the expected schema."""


@dataclass(frozen=True)
class MultiVectorAsset:
    """One page or crop and its ColSmol matrix plus retrieval metadata."""

    project_id: str
    source_id: str
    run_id: str
    asset_kind: AssetKind
    page_index: int
    image_path: str
    vectors: list[list[float]]
    page_id: Optional[str] = None
    crop_id: Optional[str] = None
    crop_index: Optional[int] = None
    bbox_norm: Optional[dict[str, float]] = None
    sheet_number: Optional[str] = None
    sheet_title: Optional[str] = None
    discipline: Optional[str] = None
    source_filename: Optional[str] = None
    file_hash: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    point_id: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("project_id", "source_id", "run_id", "image_path"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.asset_kind not in {"page", "grid_crop", "region_crop"}:
            raise ValueError(f"Unsupported asset_kind: {self.asset_kind}")
        if self.page_index < 0:
            raise ValueError("page_index must be zero or greater")
        if not self.vectors:
            raise ValueError("vectors must contain at least one vector")
        if not all(vector for vector in self.vectors):
            raise ValueError("vectors cannot contain an empty vector")

    @property
    def resolved_point_id(self) -> str:
        """Return a stable UUID for idempotent writes of the same rendered asset."""
        if self.point_id:
            return self.point_id
        asset_identity = self.crop_id or (
            str(self.crop_index) if self.crop_index is not None else self.image_path
        )
        key = (
            f"construction-os-multivector:{self.project_id}:{self.source_id}:"
            f"{self.run_id}:{self.asset_kind}:{self.page_index}:{asset_identity}"
        )
        return str(uuid5(NAMESPACE_URL, key))

    def payload(self) -> dict[str, Any]:
        """Serialize filterable and display metadata without embedding vectors."""
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "schema_version": MULTIVECTOR_PAYLOAD_SCHEMA_VERSION,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "run_id": self.run_id,
            "asset_kind": self.asset_kind,
            "page_index": self.page_index,
            "page_number": self.page_index + 1,
            "image_path": self.image_path,
            "indexed_at": now,
        }
        optional_values = {
            "page_id": self.page_id,
            "crop_id": self.crop_id,
            "crop_index": self.crop_index,
            "bbox_norm": self.bbox_norm,
            "sheet_number": self.sheet_number,
            "sheet_title": self.sheet_title,
            "discipline": self.discipline,
            "source_filename": self.source_filename,
            "file_hash": self.file_hash,
        }
        payload.update(
            {key: value for key, value in optional_values.items() if value is not None}
        )
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload

    def to_qdrant_point(self, vector_size: int) -> dict[str, Any]:
        for vector in self.vectors:
            if len(vector) != vector_size:
                raise ValueError(
                    f"Expected vector size {vector_size}, received {len(vector)}"
                )
        return {
            "id": self.resolved_point_id,
            "vector": self.vectors,
            "payload": self.payload(),
        }


class QdrantMultiVectorStore:
    """Small HTTP storage layer that keeps Qdrant optional and source-scoped."""

    def __init__(
        self,
        settings: Optional[QdrantSettings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.settings = settings or load_qdrant_settings()
        self.client = client

    def _require_enabled(self) -> None:
        if not self.settings.enabled:
            raise MultiVectorStoreError("Multi-vector storage is disabled")

    @asynccontextmanager
    async def _client_scope(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
            return
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            yield client

    async def ensure_collection(self) -> dict[str, Any]:
        """Create or validate the versioned collection and its payload indexes."""
        self._require_enabled()
        created = False
        async with self._client_scope() as client:
            response = await client.get(
                self._collection_url,
                headers=qdrant_headers(self.settings),
            )
            if response.status_code == 404:
                response = await client.put(
                    self._collection_url,
                    headers=qdrant_headers(self.settings),
                    json={
                        "vectors": {
                            "size": self.settings.vector_size,
                            "distance": "Cosine",
                            "multivector_config": {"comparator": "max_sim"},
                        }
                    },
                )
                response.raise_for_status()
                created = True
                collection = {}
            else:
                response.raise_for_status()
                collection = response.json().get("result") or {}
                self._validate_collection(collection)

            payload_schema = collection.get("payload_schema") or {}
            created_indexes: list[str] = []
            for field_name, field_schema in PAYLOAD_INDEXES.items():
                if field_name in payload_schema:
                    continue
                index_response = await client.put(
                    f"{self._collection_url}/index",
                    params={"wait": "true"},
                    headers=qdrant_headers(self.settings),
                    json={
                        "field_name": field_name,
                        "field_schema": field_schema,
                    },
                )
                index_response.raise_for_status()
                created_indexes.append(field_name)

        return {
            "collection": self.settings.collection_name,
            "created": created,
            "vector_size": self.settings.vector_size,
            "comparator": "max_sim",
            "created_indexes": created_indexes,
        }

    async def upsert_assets(
        self,
        assets: Sequence[MultiVectorAsset],
    ) -> dict[str, Any]:
        """Upsert page/crop points using deterministic IDs."""
        self._require_enabled()
        points = [
            asset.to_qdrant_point(self.settings.vector_size) for asset in assets
        ]
        if not points:
            return {"upserted": 0}

        async with self._client_scope() as client:
            response = await client.put(
                f"{self._collection_url}/points",
                params={"wait": "true"},
                headers=qdrant_headers(self.settings),
                json={"points": points},
            )
            response.raise_for_status()
        return {"upserted": len(points)}

    async def delete_source(self, *, project_id: str, source_id: str) -> dict[str, Any]:
        """Delete only points belonging to one project/source pair."""
        self._require_enabled()
        body = {"filter": self._source_filter(project_id, source_id)}
        async with self._client_scope() as client:
            response = await client.post(
                f"{self._collection_url}/points/delete",
                params={"wait": "true"},
                headers=qdrant_headers(self.settings),
                json=body,
            )
            response.raise_for_status()
        return {"deleted": True, "project_id": project_id, "source_id": source_id}

    async def count_source(self, *, project_id: str, source_id: str) -> int:
        """Return the exact point count for one project/source pair."""
        self._require_enabled()
        async with self._client_scope() as client:
            response = await client.post(
                f"{self._collection_url}/points/count",
                headers=qdrant_headers(self.settings),
                json={
                    "filter": self._source_filter(project_id, source_id),
                    "exact": True,
                },
            )
            response.raise_for_status()
            result = response.json().get("result") or {}
        return int(result.get("count") or 0)

    async def replace_source(
        self,
        *,
        project_id: str,
        source_id: str,
        assets: Sequence[MultiVectorAsset],
    ) -> dict[str, Any]:
        """Rebuild one source by deleting its old points before idempotent upsert."""
        for asset in assets:
            if asset.project_id != project_id or asset.source_id != source_id:
                raise ValueError("All assets must match the rebuilt project and source")

        await self.delete_source(project_id=project_id, source_id=source_id)
        result = await self.upsert_assets(assets)
        return {
            "project_id": project_id,
            "source_id": source_id,
            "deleted_existing": True,
            "upserted": result["upserted"],
        }

    @property
    def _collection_url(self) -> str:
        return f"{self.settings.url}/collections/{self.settings.collection_name}"

    @staticmethod
    def _source_filter(project_id: str, source_id: str) -> dict[str, Any]:
        if not project_id.strip() or not source_id.strip():
            raise ValueError("project_id and source_id are required")
        return {
            "must": [
                {"key": "project_id", "match": {"value": project_id}},
                {"key": "source_id", "match": {"value": source_id}},
            ]
        }

    def _validate_collection(self, collection: dict[str, Any]) -> None:
        vectors = collection.get("config", {}).get("params", {}).get("vectors", {})
        if "size" not in vectors and self.settings.collection_name in vectors:
            vectors = vectors[self.settings.collection_name]

        size = vectors.get("size")
        comparator = vectors.get("multivector_config", {}).get("comparator")
        distance = str(vectors.get("distance") or "").lower()
        if (
            int(size or 0) != self.settings.vector_size
            or str(comparator or "").lower() != "max_sim"
            or distance != "cosine"
        ):
            raise MultiVectorCollectionMismatch(
                "Existing Qdrant collection does not match "
                f"size={self.settings.vector_size}, distance=Cosine, "
                "comparator=max_sim"
            )
