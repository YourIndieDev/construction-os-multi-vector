"""Isolated APIs for drawing retrieval experiments."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, List, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api import ag_ui_agents
from api.routers.chat import (
    GUEST_KEY_HEADER,
    ExecuteChatRequest,
    _assert_session_guest_access,
    _normalize_guest_key,
)
from construction_os.config import DRAWING_EXTRACTION_FOLDER
from construction_os.domain.project import ChatSession, Project
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
from construction_os.exceptions import NotFoundError
from construction_os.graphs import chat as chat_graph_module
from construction_os.integrations.colsmol import ColSmolEmbeddingError
from construction_os.retrieval.types import RetrievalMode
from construction_os.utils.chat_session import (
    get_refers_to_out_id,
    normalize_chat_session_id,
    resolve_artifact_meta,
    resolve_html_template_meta,
    resolve_session_collection_ids,
    resolve_session_html_template_id,
    resolve_session_skill_ids,
)
from construction_os.utils.graph_utils import truncate_messages_from_id

router = APIRouter(prefix="/multivector", tags=["drawing-multivector-search"])
_ALLOWED_EVIDENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


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


def _resolve_evidence_image_path(raw_path: str) -> Path:
    root = Path(DRAWING_EXTRACTION_FOLDER).expanduser().resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid evidence image path") from exc
    if not resolved.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Evidence image path is outside drawing data")
    if resolved.suffix.lower() not in _ALLOWED_EVIDENCE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported evidence image type")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Evidence image not found")
    return resolved


@router.get("/evidence/image")
async def get_multivector_evidence_image(
    path: str = Query(..., min_length=1),
) -> FileResponse:
    """Return one validated crop or parent-page image from drawing extraction data."""
    resolved = _resolve_evidence_image_path(path)
    media_type = mimetypes.guess_type(resolved.name)[0] or "image/png"
    return FileResponse(
        path=resolved,
        media_type=media_type,
        filename=resolved.name,
        content_disposition_type="inline",
    )


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
    try:
        guest_key = _normalize_guest_key(x_guest_key)
        full_session_id = normalize_chat_session_id(body.session_id)
        session = await ChatSession.get(full_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        _assert_session_guest_access(session, guest_key)

        project_id = await get_refers_to_out_id(full_session_id)
        project_meta = None
        if project_id:
            project = await Project.get(project_id)
            if project:
                project_id = getattr(project, "id", None)
                project_meta = {
                    "id": project_id,
                    "name": getattr(project, "name", None),
                    "description": getattr(project, "description", None),
                }

        if guest_key:
            model_override = None
            skill_ids: List[str] = []
            session.skill_ids = []
            collection_ids: List[str] = []
            session.collection_ids = []
            html_template_id = None
            session.html_template_id = None
            html_template_meta = None
            mcp_tool_ids: List[str] = []
            artifact_id = None
            artifact_meta = None
        else:
            model_override = (
                body.model_override
                if body.model_override is not None
                else getattr(session, "model_override", None)
            )
            skill_ids = resolve_session_skill_ids(session, body.skill_ids)
            collection_ids = resolve_session_collection_ids(
                session, body.collection_ids
            )
            html_template_id = resolve_session_html_template_id(
                session, body.html_template_id
            )
            html_template_id, html_template_meta = await resolve_html_template_meta(
                html_template_id,
                session=session,
            )
            mcp_tool_ids = list(body.mcp_tool_ids or [])
            artifact_id, artifact_meta = await resolve_artifact_meta(body.artifact_id)

        if body.edit_message_id:
            try:
                await truncate_messages_from_id(
                    chat_graph_module.graph,
                    full_session_id,
                    body.edit_message_id,
                )
            except NotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        context_config = body.context_config
        if context_config is None and body.drawing_source_ids:
            context_config = {
                "sources": {
                    source_id: "full content"
                    for source_id in body.drawing_source_ids
                }
            }

        await session.save()
        run_input = ag_ui_agents.build_run_input(
            thread_id=full_session_id,
            message=body.message,
            message_id=body.edit_message_id,
            forwarded_props={
                "context": body.context,
                "context_config": context_config,
                "project_id": project_id,
                "project": project_meta,
                "model_override": model_override,
                "skill_ids": skill_ids,
                "collection_ids": collection_ids,
                "mcp_tool_ids": mcp_tool_ids,
                "session_id": full_session_id,
                "artifact_id": artifact_id if artifact_meta else None,
                "artifact": artifact_meta,
                "html_template_id": html_template_id if html_template_meta else None,
                "html_template": html_template_meta,
                "is_guest": bool(guest_key),
                "drawing_retrieval_mode": body.drawing_retrieval_mode,
                "drawing_source_ids": list(body.drawing_source_ids),
                "drawing_result_limit": body.drawing_result_limit,
            },
        )
        return ag_ui_agents.ag_ui_streaming_response(
            ag_ui_agents.project_chat_agent,
            run_input,
            configurable={"model_id": model_override},
        )
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error executing visual project chat: {exc}",
        ) from exc
