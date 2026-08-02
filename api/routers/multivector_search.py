"""Isolated APIs for drawing retrieval experiments."""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from api.routers.chat import (
    GUEST_KEY_HEADER,
    ExecuteChatRequest,
    execute_chat,
)
from construction_os.drawing.multivector_retrieval import (
    retrieve_multivector_evidence,
)
from construction_os.drawing.multivector_search import MultiVectorSearchError
from construction_os.drawing.multivector_state import MultiVectorStateError
from construction_os.drawing.retrieval_modes import (
    DrawingRetrievalMode,
    RetrievalModeExecutionError,
    retrieve_with_modes,
)
from construction_os.integrations.colsmol import ColSmolEmbeddingError
from construction_os.retrieval.types import RetrievalMode

router = APIRouter(prefix="/multivector", tags=["drawing-multivector-search"])


class MultiVectorSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    project_id: str = Field(..., min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
    minimum_score: Optional[float] = None


class DrawingRetrievalModeRequest(BaseModel):
    """Request for existing, multi-vector, or side-by-side retrieval."""

    query: str = Field(..., min_length=1, max_length=4000)
    project_id: str = Field(..., min_length=1)
    mode: DrawingRetrievalMode = "existing"
    source_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
    existing_mode: RetrievalMode = "auto"
    search_sources: bool = True
    search_notes: bool = True
    existing_minimum_score: float = 0.2
    multi_vector_minimum_score: Optional[float] = None


class VisualChatExecuteRequest(ExecuteChatRequest):
    """Existing project-chat request plus request-scoped drawing retrieval options."""

    drawing_retrieval_mode: DrawingRetrievalMode = "existing"
    drawing_source_ids: list[str] = Field(default_factory=list)
    drawing_result_limit: int = Field(default=3, ge=1, le=3)


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


@router.post("/retrieve")
async def retrieve_drawings_by_mode(
    body: DrawingRetrievalModeRequest,
) -> dict[str, Any]:
    """Run existing retrieval, visual retrieval, or separate comparison rankings."""
    try:
        return await retrieve_with_modes(
            body.query,
            project_id=body.project_id,
            mode=body.mode,
            source_ids=body.source_ids,
            limit=body.limit,
            existing_mode=body.existing_mode,
            search_sources=body.search_sources,
            search_notes=body.search_notes,
            existing_minimum_score=body.existing_minimum_score,
            multi_vector_minimum_score=body.multi_vector_minimum_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RetrievalModeExecutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/chat/execute")
async def execute_visual_project_chat(
    body: VisualChatExecuteRequest,
    x_guest_key: Optional[str] = Header(None, alias=GUEST_KEY_HEADER),
):
    """Stream the existing project-chat agent with experimental visual retrieval."""
    context_config = dict(body.context_config or {})
    context_config["drawing_retrieval_mode"] = body.drawing_retrieval_mode
    context_config["drawing_source_ids"] = list(body.drawing_source_ids)
    context_config["drawing_result_limit"] = body.drawing_result_limit

    base_data = body.model_dump(
        exclude={
            "drawing_retrieval_mode",
            "drawing_source_ids",
            "drawing_result_limit",
        }
    )
    base_data["context_config"] = context_config
    return await execute_chat(
        ExecuteChatRequest(**base_data),
        x_guest_key=x_guest_key,
    )
