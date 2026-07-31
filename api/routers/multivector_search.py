"""Isolated API for ColSmol + Qdrant drawing retrieval."""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from construction_os.drawing.multivector_retrieval import (
    retrieve_multivector_evidence,
)
from construction_os.drawing.multivector_search import MultiVectorSearchError
from construction_os.drawing.multivector_state import MultiVectorStateError
from construction_os.integrations.colsmol import ColSmolEmbeddingError

router = APIRouter(prefix="/multivector", tags=["drawing-multivector-search"])


class MultiVectorSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    project_id: str = Field(..., min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
    minimum_score: Optional[float] = None


@router.post("/search")
async def search_multivector_drawings(
    body: MultiVectorSearchRequest,
) -> dict[str, Any]:
    """Search only enabled, current, ready visual-index sources."""
    try:
        items = await retrieve_multivector_evidence(
            body.query,
            project_id=body.project_id,
            source_ids=body.source_ids,
            limit=body.limit,
            minimum_score=body.minimum_score,
        )
        return {
            "mode": "multi_vector",
            "project_id": body.project_id,
            "source_ids": body.source_ids,
            "result_count": len(items),
            "results": [item.to_search_result() for item in items],
        }
    except MultiVectorStateError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (
        ColSmolEmbeddingError,
        MultiVectorSearchError,
        httpx.HTTPError,
    ) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
