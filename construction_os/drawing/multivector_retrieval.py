"""ColSmol query embedding and Qdrant visual evidence retrieval."""

from __future__ import annotations

from typing import Awaitable, Callable, Optional, Sequence

from construction_os.drawing.multivector_project_status import (
    ready_project_source_ids,
)
from construction_os.drawing.multivector_search import (
    MultiVectorSearchHit,
    QdrantMultiVectorSearch,
)
from construction_os.integrations.colsmol_query import embed_colsmol_query
from construction_os.retrieval.types import EvidenceItem

QueryEmbedder = Callable[[str], Awaitable[dict]]


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


def _evidence_title(payload: dict) -> str:
    sheet_number = str(payload.get("sheet_number") or "").strip()
    sheet_title = str(payload.get("sheet_title") or "").strip()
    if sheet_number or sheet_title:
        return " — ".join(part for part in (sheet_number, sheet_title) if part)
    page_number = int(payload.get("page_number") or int(payload.get("page_index") or 0) + 1)
    source_name = str(payload.get("source_filename") or "Drawing").strip()
    return f"{source_name} — Page {page_number}"


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
    return [visual_hit_to_evidence(hit) for hit in deduplicated]
