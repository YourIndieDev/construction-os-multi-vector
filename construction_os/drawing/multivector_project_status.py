"""Project-level source status helpers for optional multi-vector retrieval."""

from __future__ import annotations

from typing import Any

from construction_os.domain.project import Project
from construction_os.drawing.multivector_state import (
    MultiVectorStateError,
    get_source_index_status,
)
from construction_os.drawing.multivector_store import QdrantMultiVectorStore


async def list_project_source_statuses(
    project_id: str,
    *,
    include_qdrant_count: bool = True,
) -> list[dict[str, Any]]:
    """Return visual-index state for every source currently linked to a project."""
    try:
        project = await Project.get(project_id)
        sources = await project.get_sources()
    except Exception as exc:
        raise MultiVectorStateError(f"Project not found: {project_id}") from exc

    statuses: list[dict[str, Any]] = []
    store = QdrantMultiVectorStore() if include_qdrant_count else None
    for source in sources:
        source_id = str(source.id or "")
        if not source_id:
            continue
        statuses.append(
            await get_source_index_status(
                project_id,
                source_id,
                include_qdrant_count=include_qdrant_count,
                store=store,
            )
        )
    return statuses


async def ready_project_source_ids(
    project_id: str,
    *,
    requested_source_ids: list[str] | None = None,
) -> list[str]:
    """Return only enabled, current, ready sources eligible for visual search."""
    requested = {
        source_id.strip()
        for source_id in (requested_source_ids or [])
        if source_id and source_id.strip()
    }
    statuses = await list_project_source_statuses(
        project_id,
        include_qdrant_count=False,
    )
    ready: list[str] = []
    for status in statuses:
        source_id = str(status.get("source_id") or "")
        if requested and source_id not in requested:
            continue
        if not bool(status.get("enabled")):
            continue
        if status.get("status") != "ready" or bool(status.get("stale")):
            continue
        if int(status.get("point_count") or 0) < 1:
            continue
        ready.append(source_id)
    return ready
