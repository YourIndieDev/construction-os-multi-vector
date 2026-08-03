"""Background source indexing for ColSmol + Qdrant visual retrieval."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
from loguru import logger

from construction_os.config import DRAWING_EXTRACTION_FOLDER
from construction_os.drawing import repository as drawing_repo
from construction_os.drawing.config import load_drawing_extraction_config
from construction_os.drawing.multivector_state import (
    _persist_state,
    get_source_index_status,
    mark_source_index_error,
    mark_source_index_ready,
    mark_source_indexing,
    set_source_index_enabled,
    source_file_hash,
)
from construction_os.drawing.multivector_store import (
    MultiVectorAsset,
    QdrantMultiVectorStore,
)
from construction_os.drawing.pdf_inspect import open_pdf, resolve_source_pdf_path
from construction_os.drawing.render import render_page_assets
from construction_os.domain.project import Source
from construction_os.integrations.colsmol import (
    ColSmolEmbeddingError,
    embed_colsmol_image,
    load_colsmol_settings,
)


@dataclass(frozen=True)
class VisualAsset:
    path: Path
    asset_kind: str
    page_index: int
    page_id: Optional[str] = None
    crop_id: Optional[str] = None
    crop_index: Optional[int] = None
    bbox_norm: Optional[dict[str, float]] = None
    sheet_number: Optional[str] = None
    sheet_title: Optional[str] = None
    discipline: Optional[str] = None


_TASKS: dict[tuple[str, str], asyncio.Task[None]] = {}


def _task_key(project_id: str, source_id: str) -> tuple[str, str]:
    return project_id, source_id


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _path_if_file(value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_file() else None


def _append_unique(
    assets: list[VisualAsset],
    seen: set[str],
    asset: VisualAsset,
) -> None:
    key = str(asset.path.resolve())
    if key in seen:
        return
    seen.add(key)
    assets.append(asset)


async def _existing_drawing_assets(source_id: str) -> tuple[list[VisualAsset], Optional[str]]:
    runs = await drawing_repo.list_runs_for_source(source_id)
    usable = [
        run
        for run in runs
        if str(run.get("status") or "") in {"completed", "partial"}
    ]
    if not usable:
        return [], None

    run = next((item for item in usable if bool(item.get("active"))), usable[0])
    run_id = str(run.get("id"))
    detail = await drawing_repo.get_run_detail(run_id)
    pages = detail.get("pages") or []
    regions = detail.get("regions") or []
    regions_by_page: dict[str, list[dict[str, Any]]] = {}
    for region in regions:
        regions_by_page.setdefault(str(region.get("page_id")), []).append(region)

    assets: list[VisualAsset] = []
    seen: set[str] = set()
    for page in sorted(pages, key=lambda row: int(row.get("page_index") or 0)):
        page_index = int(page.get("page_index") or 0)
        page_id = str(page.get("id")) if page.get("id") else None
        render_path = _path_if_file(page.get("render_path"))
        common = {
            "page_index": page_index,
            "page_id": page_id,
            "sheet_number": page.get("sheet_number"),
            "sheet_title": page.get("sheet_title"),
            "discipline": page.get("discipline"),
        }
        if render_path:
            _append_unique(
                assets,
                seen,
                VisualAsset(path=render_path, asset_kind="page", **common),
            )
            crop_dir = render_path.parent / "crops"
            for crop_index, crop_path in enumerate(sorted(crop_dir.glob("*.png"))):
                _append_unique(
                    assets,
                    seen,
                    VisualAsset(
                        path=crop_path,
                        asset_kind="grid_crop",
                        crop_id=f"{page_id or page_index}:grid:{crop_path.stem}",
                        crop_index=crop_index,
                        **common,
                    ),
                )

        for region_index, region in enumerate(regions_by_page.get(page_id or "", [])):
            crop_path = _path_if_file(region.get("crop_path"))
            if not crop_path:
                continue
            _append_unique(
                assets,
                seen,
                VisualAsset(
                    path=crop_path,
                    asset_kind="region_crop",
                    crop_id=str(region.get("id") or f"{page_id}:region:{region_index}"),
                    crop_index=region_index,
                    bbox_norm=region.get("bbox_norm"),
                    **common,
                ),
            )

    return assets, run_id


def _render_source_assets(source: Source, file_hash: str) -> list[VisualAsset]:
    if not source.asset or not source.asset.file_path:
        raise ValueError("Source has no uploaded PDF")

    pdf_path = resolve_source_pdf_path(source.asset.file_path)
    cfg = load_drawing_extraction_config()
    output_dir = (
        Path(DRAWING_EXTRACTION_FOLDER)
        / "multivector"
        / _safe_segment(str(source.id or "source"))
        / file_hash[:12]
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    assets: list[VisualAsset] = []
    doc = open_pdf(pdf_path)
    try:
        for page_index in range(len(doc)):
            page_dir = output_dir / f"page_{page_index:04d}"
            renders = render_page_assets(
                doc[page_index],
                page_dir,
                page_dpi=cfg.page_render_dpi,
                thumbnail_dpi=cfg.thumbnail_dpi,
                dense_crop_dpi=cfg.dense_crop_dpi,
                crop_overlap=cfg.crop_overlap,
                include_grid_crops=True,
            )
            assets.append(
                VisualAsset(
                    path=Path(renders["render_path"]),
                    asset_kind="page",
                    page_index=page_index,
                )
            )
            for crop_index, crop in enumerate(renders.get("crops") or []):
                crop_path = _path_if_file(crop.get("path"))
                if not crop_path:
                    continue
                assets.append(
                    VisualAsset(
                        path=crop_path,
                        asset_kind="grid_crop",
                        page_index=page_index,
                        crop_id=f"page:{page_index}:grid:{crop_index}",
                        crop_index=crop_index,
                        bbox_norm=crop.get("bbox_norm"),
                    )
                )
    finally:
        doc.close()

    return assets


async def _collect_assets(
    source: Source,
    source_id: str,
    file_hash: str,
) -> tuple[list[VisualAsset], str]:
    assets, drawing_run_id = await _existing_drawing_assets(source_id)
    if assets:
        return assets, drawing_run_id or f"multivector:{file_hash[:24]}"

    rendered = await asyncio.to_thread(_render_source_assets, source, file_hash)
    return rendered, f"multivector:{file_hash[:24]}"


async def _write_progress(
    project_id: str,
    source_id: str,
    *,
    run_id: str,
    processed_assets: int,
    total_assets: int,
    current_asset: Optional[str],
) -> None:
    await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="indexing",
        point_count=processed_assets,
        indexed_file_hash=None,
        indexed_run_id=run_id,
        indexed_at=None,
        last_error=None,
        processed_assets=processed_assets,
        total_assets=total_assets,
        current_asset=current_asset,
    )


async def run_source_multivector_index(project_id: str, source_id: str) -> None:
    """Render/reuse visual assets, embed one at a time, and publish to Qdrant."""
    try:
        await get_source_index_status(
            project_id,
            source_id,
            include_qdrant_count=False,
        )
        source = await Source.get(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")

        file_hash = source_file_hash(source)
        assets, run_id = await _collect_assets(source, source_id, file_hash)
        if not assets:
            raise ValueError("No page or crop images were available for visual indexing")

        await mark_source_indexing(project_id, source_id, run_id=run_id)
        await _write_progress(
            project_id,
            source_id,
            run_id=run_id,
            processed_assets=0,
            total_assets=len(assets),
            current_asset=None,
        )

        store = QdrantMultiVectorStore()
        await store.ensure_collection()
        await store.delete_source(project_id=project_id, source_id=source_id)

        colsmol_settings = load_colsmol_settings()
        timeout = httpx.Timeout(colsmol_settings.embedding_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for index, visual in enumerate(assets, start=1):
                await _write_progress(
                    project_id,
                    source_id,
                    run_id=run_id,
                    processed_assets=index - 1,
                    total_assets=len(assets),
                    current_asset=visual.path.name,
                )
                embedding = await embed_colsmol_image(
                    visual.path,
                    settings=colsmol_settings,
                    client=client,
                )
                point = MultiVectorAsset(
                    project_id=project_id,
                    source_id=source_id,
                    run_id=run_id,
                    asset_kind=visual.asset_kind,  # type: ignore[arg-type]
                    page_index=visual.page_index,
                    image_path=str(visual.path),
                    vectors=embedding["vectors"],
                    page_id=visual.page_id,
                    crop_id=visual.crop_id,
                    crop_index=visual.crop_index,
                    bbox_norm=visual.bbox_norm,
                    sheet_number=visual.sheet_number,
                    sheet_title=visual.sheet_title,
                    discipline=visual.discipline,
                    source_filename=visual.path.name,
                    file_hash=file_hash,
                    metadata={
                        "model": embedding.get("model"),
                        "vector_count": embedding.get("vector_count"),
                        "image_width": embedding.get("image_width"),
                        "image_height": embedding.get("image_height"),
                    },
                )
                await store.upsert_assets([point])
                await _write_progress(
                    project_id,
                    source_id,
                    run_id=run_id,
                    processed_assets=index,
                    total_assets=len(assets),
                    current_asset=None,
                )

        await mark_source_index_ready(
            project_id,
            source_id,
            file_hash=file_hash,
            run_id=run_id,
            point_count=len(assets),
        )
        logger.info(
            "Multi-vector visual index ready for {}/{} with {} points",
            project_id,
            source_id,
            len(assets),
        )
    except asyncio.CancelledError:
        logger.info("Multi-vector indexing cancelled for {}/{}", project_id, source_id)
        raise
    except (ColSmolEmbeddingError, Exception) as exc:
        logger.exception(
            "Multi-vector indexing failed for {}/{}: {}",
            project_id,
            source_id,
            exc,
        )
        await mark_source_index_error(
            project_id,
            source_id,
            error=f"{type(exc).__name__}: {exc}",
        )


async def queue_source_multivector_index(
    project_id: str,
    source_id: str,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Enable and queue one source, avoiding duplicate in-process jobs."""
    key = _task_key(project_id, source_id)
    existing = _TASKS.get(key)
    if existing and not existing.done():
        return await get_source_index_status(
            project_id,
            source_id,
            include_qdrant_count=False,
        )

    enabled = await set_source_index_enabled(
        project_id,
        source_id,
        enabled=True,
    )
    if enabled.get("status") == "ready" and not force:
        return enabled

    await _persist_state(
        project_id,
        source_id,
        enabled=True,
        status="queued",
        point_count=0,
        indexed_file_hash=None if force else enabled.get("indexed_file_hash"),
        indexed_run_id=None,
        indexed_at=None,
        last_error=None,
        processed_assets=0,
        total_assets=0,
        current_asset=None,
    )

    task = asyncio.create_task(
        run_source_multivector_index(project_id, source_id),
        name=f"multivector:{project_id}:{source_id}",
    )
    _TASKS[key] = task

    def _clear(done: asyncio.Task[None]) -> None:
        if _TASKS.get(key) is done:
            _TASKS.pop(key, None)

    task.add_done_callback(_clear)
    return await get_source_index_status(
        project_id,
        source_id,
        include_qdrant_count=False,
    )


def cancel_source_multivector_index(project_id: str, source_id: str) -> bool:
    """Cancel a running in-process indexing task before disabling a source."""
    task = _TASKS.get(_task_key(project_id, source_id))
    if not task or task.done():
        return False
    task.cancel()
    return True
