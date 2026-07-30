"""Persisted source opt-in and readiness state for multi-vector drawing indexing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import NAMESPACE_URL, uuid5

import httpx

from construction_os.database.repository import (
    ensure_record_id,
    repo_query,
    repo_upsert,
)
from construction_os.domain.project import Project, Source
from construction_os.drawing.multivector_store import (
    MultiVectorStoreError,
    QdrantMultiVectorStore,
)
from construction_os.drawing.pdf_inspect import compute_file_hash, resolve_source_pdf_path

IndexStatus = Literal[
    "disabled",
    "not_indexed",
    "queued",
    "indexing",
    "ready",
    "stale",
    "error",
]

STATE_TABLE = "drawing_multivector_index"
ACTIVE_STATUSES = {"queued", "indexing"}


class MultiVectorStateError(RuntimeError):
    """Raised for invalid or unavailable source indexing state operations."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def state_record_id(project_id: str, source_id: str) -> str:
    """Return a stable record ID for one project/source indexing relationship."""
    if not project_id.strip() or not source_id.strip():
        raise ValueError("project_id and source_id are required")
    key = f"construction-os-multivector-state:{project_id}:{source_id}"
    return f"{STATE_TABLE}:{uuid5(NAMESPACE_URL, key)}"


def _unwrap_row(result: Any) -> dict[str, Any]:
    if isinstance(result, list):
        if not result:
            raise MultiVectorStateError("State persistence returned no record")
        row = result[0]
    else:
        row = result
    if not isinstance(row, dict):
        raise MultiVectorStateError("State persistence returned an invalid record")
    return row


async def _load_source_for_project(project_id: str, source_id: str) -> Source:
    try:
        source = await Source.get(source_id)
    except Exception as exc:
        raise MultiVectorStateError(f"Source not found: {source_id}") from exc

    rows = await repo_query(
        "SELECT count() AS count FROM reference "
        "WHERE in = $source_id AND out = $project_id GROUP ALL",
        {
            "source_id": ensure_record_id(source_id),
            "project_id": ensure_record_id(project_id),
        },
    )
    if not rows or int(rows[0].get("count") or 0) < 1:
        raise MultiVectorStateError(
            f"Source {source_id} is not linked to project {project_id}"
        )
    return source


def source_file_hash(source: Source) -> str:
    """Resolve and hash the current uploaded PDF backing a source."""
    if not source.asset or not source.asset.file_path:
        raise MultiVectorStateError("Source has no uploaded file")
    try:
        path = resolve_source_pdf_path(source.asset.file_path)
        return compute_file_hash(path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise MultiVectorStateError(str(exc)) from exc


async def get_persisted_state(project_id: str, source_id: str) -> dict[str, Any]:
    record_id = state_record_id(project_id, source_id)
    rows = await repo_query(f"SELECT * FROM {record_id} LIMIT 1")
    if rows:
        return rows[0]
    return {
        "id": record_id,
        "project_id": project_id,
        "source_id": source_id,
        "enabled": False,
        "status": "disabled",
        "point_count": 0,
        "indexed_file_hash": None,
        "indexed_run_id": None,
        "indexed_at": None,
        "last_error": None,
    }


async def _persist_state(
    project_id: str,
    source_id: str,
    **fields: Any,
) -> dict[str, Any]:
    record_id = state_record_id(project_id, source_id)
    current = await get_persisted_state(project_id, source_id)
    created = current.get("created") or _now()
    payload = {
        "project_id": project_id,
        "source_id": source_id,
        "created": created,
        **fields,
    }
    result = await repo_upsert(STATE_TABLE, record_id, payload, add_timestamp=True)
    return _unwrap_row(result)


def _derived_status(
    state: dict[str, Any],
    *,
    current_file_hash: Optional[str],
    point_count: Optional[int],
) -> IndexStatus:
    if not bool(state.get("enabled")):
        return "disabled"

    persisted_status = str(state.get("status") or "not_indexed")
    if persisted_status in ACTIVE_STATUSES:
        return persisted_status  # type: ignore[return-value]
    if persisted_status == "error" and state.get("last_error"):
        return "error"

    indexed_hash = state.get("indexed_file_hash")
    if not indexed_hash:
        return "not_indexed"
    if current_file_hash and indexed_hash != current_file_hash:
        return "stale"
    if point_count is not None and point_count < 1:
        return "not_indexed"
    return "ready"


async def get_source_index_status(
    project_id: str,
    source_id: str,
    *,
    include_qdrant_count: bool = True,
    store: Optional[QdrantMultiVectorStore] = None,
) -> dict[str, Any]:
    source = await _load_source_for_project(project_id, source_id)
    state = await get_persisted_state(project_id, source_id)

    current_hash: Optional[str] = None
    file_error: Optional[str] = None
    try:
        current_hash = source_file_hash(source)
    except MultiVectorStateError as exc:
        file_error = str(exc)

    point_count: Optional[int] = None
    qdrant_available: Optional[bool] = None
    qdrant_error: Optional[str] = None
    if include_qdrant_count and bool(state.get("enabled")):
        active_store = store or QdrantMultiVectorStore()
        try:
            point_count = await active_store.count_source(
                project_id=project_id,
                source_id=source_id,
            )
            qdrant_available = True
        except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
            qdrant_available = False
            qdrant_error = str(exc)

    derived = _derived_status(
        state,
        current_file_hash=current_hash,
        point_count=point_count,
    )
    indexed_hash = state.get("indexed_file_hash")
    stale = bool(indexed_hash and current_hash and indexed_hash != current_hash)

    return {
        "project_id": project_id,
        "source_id": source_id,
        "source_title": source.title,
        "enabled": bool(state.get("enabled")),
        "status": derived,
        "persisted_status": state.get("status") or "disabled",
        "current_file_hash": current_hash,
        "indexed_file_hash": indexed_hash,
        "stale": stale,
        "point_count": point_count
        if point_count is not None
        else int(state.get("point_count") or 0),
        "indexed_run_id": state.get("indexed_run_id"),
        "indexed_at": state.get("indexed_at"),
        "rebuild_requested_at": state.get("rebuild_requested_at"),
        "last_error": state.get("last_error"),
        "file_error": file_error,
        "qdrant_available": qdrant_available,
        "qdrant_error": qdrant_error,
        "state_id": state.get("id") or state_record_id(project_id, source_id),
    }


async def set_source_index_enabled(
    project_id: str,
    source_id: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    source = await _load_source_for_project(project_id, source_id)
    current = await get_persisted_state(project_id, source_id)

    if not enabled:
        await _persist_state(
            project_id,
            source_id,
            enabled=False,
            status="disabled",
            point_count=int(current.get("point_count") or 0),
            indexed_file_hash=current.get("indexed_file_hash"),
            indexed_run_id=current.get("indexed_run_id"),
            indexed_at=current.get("indexed_at"),
            last_error=current.get("last_error"),
            disabled_at=_now(),
        )
        return await get_source_index_status(
            project_id,
            source_id,
            include_qdrant_count=False,
        )

    current_hash = source_file_hash(source)
    indexed_hash = current.get("indexed_file_hash")
    status: IndexStatus
    if not indexed_hash:
        status = "not_indexed"
    elif indexed_hash != current_hash:
        status = "stale"
    else:
        status = "ready"

    await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status=status,
        point_count=int(current.get("point_count") or 0),
        indexed_file_hash=indexed_hash,
        indexed_run_id=current.get("indexed_run_id"),
        indexed_at=current.get("indexed_at"),
        last_error=None,
        enabled_at=_now(),
    )
    return await get_source_index_status(
        project_id,
        source_id,
        include_qdrant_count=False,
    )


async def request_source_rebuild(
    project_id: str,
    source_id: str,
    *,
    store: Optional[QdrantMultiVectorStore] = None,
) -> dict[str, Any]:
    source = await _load_source_for_project(project_id, source_id)
    current_hash = source_file_hash(source)
    active_store = store or QdrantMultiVectorStore()
    try:
        await active_store.delete_source(project_id=project_id, source_id=source_id)
    except (MultiVectorStoreError, httpx.HTTPError, ValueError) as exc:
        raise MultiVectorStateError(f"Unable to reset Qdrant source points: {exc}") from exc

    await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="queued",
        point_count=0,
        current_file_hash=current_hash,
        indexed_file_hash=None,
        indexed_run_id=None,
        indexed_at=None,
        last_error=None,
        rebuild_requested_at=_now(),
    )
    return await get_source_index_status(
        project_id,
        source_id,
        include_qdrant_count=False,
    )


async def mark_source_indexing(
    project_id: str,
    source_id: str,
    *,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    current = await get_persisted_state(project_id, source_id)
    return await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="indexing",
        point_count=int(current.get("point_count") or 0),
        indexed_file_hash=current.get("indexed_file_hash"),
        indexed_run_id=run_id or current.get("indexed_run_id"),
        indexed_at=current.get("indexed_at"),
        last_error=None,
        indexing_started_at=_now(),
    )


async def mark_source_index_ready(
    project_id: str,
    source_id: str,
    *,
    file_hash: str,
    run_id: str,
    point_count: int,
) -> dict[str, Any]:
    return await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="ready",
        point_count=max(point_count, 0),
        indexed_file_hash=file_hash,
        indexed_run_id=run_id,
        indexed_at=_now(),
        last_error=None,
        rebuild_requested_at=None,
    )


async def mark_source_index_error(
    project_id: str,
    source_id: str,
    *,
    error: str,
) -> dict[str, Any]:
    current = await get_persisted_state(project_id, source_id)
    return await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="error",
        point_count=int(current.get("point_count") or 0),
        indexed_file_hash=current.get("indexed_file_hash"),
        indexed_run_id=current.get("indexed_run_id"),
        indexed_at=current.get("indexed_at"),
        last_error=error[:4000],
        failed_at=_now(),
    )


async def list_project_source_statuses(project_id: str) -> list[dict[str, Any]]:
    try:
        project = await Project.get(project_id)
    except Exception as exc:
        raise MultiVectorStateError(f"Project not found: {project_id}") from exc

    sources = await project.get_sources()
    results: list[dict[str, Any]] = []
    for source in sources:
        if not source.id:
            continue
        results.append(
            await get_source_index_status(
                project_id,
                source.id,
                include_qdrant_count=False,
            )
        )
    return results
