"""API routes for opt-in architectural drawing extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.routers.multivector_search import router as multivector_search_router
from construction_os.drawing import repository as drawing_repo
from construction_os.drawing.config import (
    get_drawing_retrieval_mode,
    load_drawing_extraction_config,
)
from construction_os.drawing.multivector_indexer import (
    cancel_source_multivector_index,
    queue_source_multivector_index,
)
from construction_os.drawing.multivector_project_status import (
    list_project_source_statuses,
)
from construction_os.drawing.multivector_state import (
    MultiVectorStateError,
    get_source_index_status,
    set_source_index_enabled,
)
from construction_os.drawing.multivector_store import (
    MultiVectorCollectionMismatch,
    MultiVectorStoreError,
    QdrantMultiVectorStore,
)
from construction_os.drawing.pdf_inspect import resolve_source_pdf_path
from construction_os.drawing.pipeline import queue_drawing_extraction_jobs
from construction_os.drawing.retrieval import retrieve_drawing_evidence
from construction_os.domain.project import Source
from construction_os.integrations.colsmol import check_colsmol_health
from construction_os.integrations.qdrant import check_qdrant_health

router = APIRouter(prefix="/drawing-extractions", tags=["drawing-extractions"])
router.include_router(multivector_search_router)


class DrawingExtractRequest(BaseModel):
    source_ids: List[str] = Field(..., min_length=1)
    project_id: Optional[str] = None
    force: bool = False


class DrawingSearchRequest(BaseModel):
    query: str
    project_id: str
    limit: int = 10
    minimum_score: float = 0.15


def _is_pdf_source(source: Source) -> tuple[bool, Optional[str]]:
    if not source.asset or not source.asset.file_path:
        return False, "Source has no original uploaded file"
    try:
        resolve_source_pdf_path(source.asset.file_path)
        return True, None
    except (ValueError, FileNotFoundError) as exc:
        return False, str(exc)


def _state_http_error(exc: MultiVectorStateError) -> HTTPException:
    detail = str(exc)
    lowered = detail.lower()
    if "not found" in lowered or "not linked" in lowered:
        status_code = 404
    elif "qdrant" in lowered or "colsmol" in lowered:
        status_code = 503
    else:
        status_code = 400
    return HTTPException(status_code=status_code, detail=detail)


@router.post("/extract")
async def extract_drawings(body: DrawingExtractRequest) -> Dict[str, Any]:
    """Queue architectural drawing extraction for one or more PDF sources."""
    eligible: List[str] = []
    rejected: List[Dict[str, str]] = []

    for source_id in body.source_ids:
        source = await Source.get(source_id)
        if not source:
            rejected.append({"source_id": source_id, "error": "Source not found"})
            continue
        ok, err = _is_pdf_source(source)
        if not ok:
            rejected.append({"source_id": source_id, "error": err or "Not eligible"})
            continue
        eligible.append(source_id)

    if not eligible:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No eligible PDF sources with accessible original files",
                "rejected": rejected,
            },
        )

    jobs = await queue_drawing_extraction_jobs(
        source_ids=eligible,
        project_id=body.project_id,
        force=body.force,
    )
    return {"jobs": jobs, "rejected": rejected}


@router.get("/sources/{source_id}/runs")
async def list_source_runs(source_id: str) -> Dict[str, Any]:
    runs = await drawing_repo.list_runs_for_source(source_id)
    return {"source_id": source_id, "runs": runs}


@router.get("/projects/{project_id}/runs")
async def list_project_runs(project_id: str) -> Dict[str, Any]:
    runs = await drawing_repo.list_runs_for_project(project_id)
    return {"project_id": project_id, "runs": runs}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str) -> Dict[str, Any]:
    detail = await drawing_repo.get_run_detail(run_id)
    if not detail or not detail.get("run"):
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return detail


@router.post("/runs/{run_id}/activate")
async def activate_run(run_id: str) -> Dict[str, Any]:
    run = await drawing_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    source_id = str(run.get("source_id"))
    updated = await drawing_repo.activate_run(run_id, source_id)
    return {"run": updated}


@router.post("/runs/{run_id}/deactivate")
async def deactivate_run(run_id: str) -> Dict[str, Any]:
    run = await drawing_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    updated = await drawing_repo.update_run(run_id, active=False)
    return {"run": updated}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str, force: bool = True) -> Dict[str, Any]:
    run = await drawing_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    source_id = str(run.get("source_id"))
    project_id = str(run.get("project_id")) if run.get("project_id") else None
    jobs = await queue_drawing_extraction_jobs(
        source_ids=[source_id],
        project_id=project_id,
        force=force,
    )
    return {"jobs": jobs}


@router.get("/runs/{run_id}/pages/{page_id}/image")
async def get_page_image(run_id: str, page_id: str, kind: str = "render") -> FileResponse:
    detail = await drawing_repo.get_run_detail(run_id)
    pages = detail.get("pages") or []
    page = next((p for p in pages if str(p.get("id")) == page_id), None)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    path = page.get("thumbnail_path") if kind == "thumb" else page.get("render_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")


@router.post("/search")
async def search_drawings(body: DrawingSearchRequest) -> Dict[str, Any]:
    """Isolated drawing search API."""
    items = await retrieve_drawing_evidence(
        body.query,
        project_id=body.project_id,
        limit=body.limit,
        minimum_score=body.minimum_score,
    )
    return {
        "mode": get_drawing_retrieval_mode(),
        "results": [i.to_search_result() for i in items],
    }


@router.get("/multivector/health")
async def multivector_health() -> Dict[str, Any]:
    """Report optional Qdrant and model readiness without affecting the app."""
    return {
        "qdrant": await check_qdrant_health(),
        "colsmol": await check_colsmol_health(),
    }


@router.post("/multivector/collection/ensure")
async def ensure_multivector_collection() -> Dict[str, Any]:
    """Idempotently create or validate the experimental Qdrant collection."""
    try:
        result = await QdrantMultiVectorStore().ensure_collection()
        return {"status": "ready", **result}
    except MultiVectorCollectionMismatch as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/multivector/projects/{project_id}/sources")
async def list_multivector_project_sources(project_id: str) -> Dict[str, Any]:
    """List persisted opt-in and readiness state for all project sources."""
    try:
        sources = await list_project_source_statuses(project_id)
        return {"project_id": project_id, "sources": sources}
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc


@router.get("/multivector/projects/{project_id}/sources/{source_id}")
async def get_multivector_source_status(
    project_id: str,
    source_id: str,
) -> Dict[str, Any]:
    """Return live source readiness, stale-file state, and Qdrant point count."""
    try:
        return await get_source_index_status(project_id, source_id)
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc


@router.post("/multivector/projects/{project_id}/sources/{source_id}/enable")
async def enable_multivector_source(
    project_id: str,
    source_id: str,
) -> Dict[str, Any]:
    """Enable a source and immediately start its first visual index when needed."""
    try:
        return await queue_source_multivector_index(
            project_id,
            source_id,
            force=False,
        )
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc
    except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/multivector/projects/{project_id}/sources/{source_id}/index")
async def index_multivector_source(
    project_id: str,
    source_id: str,
) -> Dict[str, Any]:
    """Enable and start actual ColSmol/Qdrant indexing for one source."""
    try:
        return await queue_source_multivector_index(
            project_id,
            source_id,
            force=False,
        )
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc
    except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/multivector/projects/{project_id}/sources/{source_id}/disable")
async def disable_multivector_source(
    project_id: str,
    source_id: str,
) -> Dict[str, Any]:
    """Cancel active indexing and disable this source for visual retrieval."""
    try:
        cancel_source_multivector_index(project_id, source_id)
        return await set_source_index_enabled(
            project_id,
            source_id,
            enabled=False,
        )
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc


@router.post("/multivector/projects/{project_id}/sources/{source_id}/rebuild")
async def rebuild_multivector_source(
    project_id: str,
    source_id: str,
) -> Dict[str, Any]:
    """Start a clean source rebuild and replace its Qdrant points."""
    try:
        return await queue_source_multivector_index(
            project_id,
            source_id,
            force=True,
        )
    except MultiVectorStateError as exc:
        raise _state_http_error(exc) from exc
    except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/config")
async def drawing_config() -> Dict[str, Any]:
    cfg = load_drawing_extraction_config()
    return {
        "extraction_provider": cfg.extraction_provider,
        "extraction_model": cfg.extraction_model,
        "verification_provider": cfg.verification_provider,
        "verification_model": cfg.verification_model,
        "embedding_model_hint": cfg.embedding_model_hint,
        "retrieval_mode": get_drawing_retrieval_mode(),
        "use_vision": cfg.use_vision,
    }
