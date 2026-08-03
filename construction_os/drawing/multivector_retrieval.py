"""ColSmol query embedding and Qdrant visual evidence retrieval."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from construction_os.drawing.multivector_project_status import (
    ready_project_source_ids,
)
from construction_os.drawing.multivector_search import (
    MultiVectorSearchHit,
    QdrantMultiVectorSearch,
)
from construction_os.domain.project import Source
from construction_os.integrations.colsmol_query import embed_colsmol_query
from construction_os.retrieval.types import EvidenceItem

QueryEmbedder = Callable[[str], Awaitable[dict]]
SourceNameResolver = Callable[[str], Awaitable[Optional[str]]]


def _page_key(hit: MultiVectorSearchHit) -> tuple[str, int | str]:
    payload = hit.payload
    source_id = str(payload.get("source_id") or "")
    page_index = payload.get("page_index")
    if isinstance(page_index, int):
        return source_id, page_index
    return source_id, str(payload.get("page_id") or hit.point_id)


def deduplicate_overlapping_hits(
    hits: Sequence[MultiVectorSearchHit],
    *,
    limit: int,
) -> list[MultiVectorSearchHit]:
    """Keep the highest-scoring page/crop hit for each source page."""
    selected: list[MultiVectorSearchHit] = []
    seen_pages: set[tuple[str, int | str]] = set()
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        key = _page_key(hit)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        selected.append(hit)
        if len(selected) >= limit:
            break
    return selected


async def _resolve_source_filename(source_id: str) -> Optional[str]:
    """Resolve the original source name without failing visual retrieval."""
    try:
        source = await Source.get(source_id)
    except Exception:
        return None
    if not source:
        return None

    title = str(source.title or "").strip()
    if title:
        return title

    file_path = source.asset.file_path if source.asset else None
    if file_path:
        return Path(file_path).name
    return None


def _has_document_filename(payload: dict) -> bool:
    filename = str(payload.get("source_filename") or "").strip().lower()
    return filename.endswith(".pdf")


async def _enrich_source_filenames(
    hits: Sequence[MultiVectorSearchHit],
    *,
    resolver: SourceNameResolver,
) -> list[MultiVectorSearchHit]:
    """Replace legacy crop filenames with the original uploaded source title."""
    unresolved_ids = sorted(
        {
            str(hit.payload.get("source_id") or "").strip()
            for hit in hits
            if not _has_document_filename(hit.payload)
            and str(hit.payload.get("source_id") or "").strip()
        }
    )
    if not unresolved_ids:
        return list(hits)

    resolved_values = await asyncio.gather(
        *(resolver(source_id) for source_id in unresolved_ids),
        return_exceptions=True,
    )
    resolved_names = {
        source_id: value
        for source_id, value in zip(unresolved_ids, resolved_values)
        if isinstance(value, str) and value.strip()
    }

    enriched: list[MultiVectorSearchHit] = []
    for hit in hits:
        payload = dict(hit.payload)
        source_id = str(payload.get("source_id") or "").strip()
        resolved_name = resolved_names.get(source_id)
        if resolved_name:
            legacy_name = str(payload.get("source_filename") or "").strip()
            if legacy_name and legacy_name != resolved_name:
                payload.setdefault("visual_asset_filename", legacy_name)
            payload["source_filename"] = resolved_name
        enriched.append(
            MultiVectorSearchHit(
                point_id=hit.point_id,
                score=hit.score,
                payload=payload,
            )
        )
    return enriched


def _evidence_title(payload: dict) -> str:
    sheet_number = str(payload.get("sheet_number") or "").strip()
    sheet_title = str(payload.get("sheet_title") or "").strip()
    if sheet_number or sheet_title:
        return " - ".join(part for part in (sheet_number, sheet_title) if part)
    page_number = int(payload.get("page_number") or int(payload.get("page_index") or 0) + 1)
    source_name = str(payload.get("source_filename") or "Drawing").strip()
    return f"{source_name} - Page {page_number}"


def visual_hit_to_evidence(hit: MultiVectorSearchHit) -> EvidenceItem:
    """Convert one Qdrant visual hit into the existing evidence contract."""
    payload = dict(hit.payload)
    image_path = str(payload.get("image_path") or "")
    page_number = int(payload.get("page_number") or int(payload.get("page_index") or 0) + 1)
    source_id = str(payload.get("source_id") or "")
    source_name = str(payload.get("source_filename") or source_id or "drawing")

    raw = dict(payload)
    raw.update(
        {
            "drawing": True,
            "multi_vector": True,
            "retrieval_backend": "qdrant_maxsim",
            "qdrant_point_id": hit.point_id,
            "evidence_crop": image_path or None,
            "similarity": hit.score,
        }
    )
    content = f"Visual evidence from {source_name}, page {page_number}."
    return EvidenceItem(
        id=hit.point_id,
        parent_id=source_id or None,
        title=_evidence_title(payload),
        score=hit.score,
        matches=[image_path] if image_path else [],
        content=content,
        source="drawing",
        raw=raw,
    )


async def retrieve_multivector_evidence(
    query: str,
    *,
    project_id: str,
    source_ids: Optional[Sequence[str]] = None,
    limit: int = 10,
    minimum_score: Optional[float] = None,
    candidate_multiplier: int = 4,
    searcher: Optional[QdrantMultiVectorSearch] = None,
    query_embedder: QueryEmbedder = embed_colsmol_query,
    source_name_resolver: SourceNameResolver = _resolve_source_filename,
) -> list[EvidenceItem]:
    """Embed a question, query ready sources with MaxSim, and deduplicate pages."""
    text = query.strip()
    if not text or not project_id.strip():
        return []
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")

    ready_source_ids = await ready_project_source_ids(
        project_id,
        requested_source_ids=list(source_ids or []),
    )
    if not ready_source_ids:
        return []

    embedding = await query_embedder(text)
    vectors = embedding.get("vectors") or []
    candidate_limit = min(100, max(limit, limit * max(candidate_multiplier, 1)))
    active_searcher = searcher or QdrantMultiVectorSearch()
    hits = await active_searcher.search(
        query_vectors=vectors,
        project_id=project_id,
        source_ids=ready_source_ids,
        limit=candidate_limit,
        score_threshold=minimum_score,
    )
    deduplicated = deduplicate_overlapping_hits(hits, limit=limit)
    enriched = await _enrich_source_filenames(
        deduplicated,
        resolver=source_name_resolver,
    )
    return [visual_hit_to_evidence(hit) for hit in enriched]
