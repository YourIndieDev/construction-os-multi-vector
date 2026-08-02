"""Safe, bounded visual evidence assembly for project chat."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional, Sequence

import fitz
from langchain_core.messages import BaseMessage
from loguru import logger

from construction_os.config import DRAWING_EXTRACTION_FOLDER
from construction_os.drawing.retrieval_modes import retrieve_with_modes

DrawingChatMode = Literal["existing", "multi_vector", "compare"]
ModeRetriever = Callable[..., Awaitable[dict[str, Any]]]

MAX_VISUAL_RESULTS = 3
MAX_VISUAL_IMAGES = 6
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_EDGE = 2048
_ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_SHEET_RE = re.compile(r"(?:^|[_\s-])([A-Z]{1,3}\d{2,4})(?:[_\s.-]|$)", re.IGNORECASE)

_VISUAL_INSTRUCTIONS = """## Retrieved Visual Drawing Evidence

Use the attached drawing images as evidence for the user's question.

Rules:
- Read only values and labels that are visibly supported.
- Do not invent dimensions, quantities, equipment labels, pipe sizes, or notes.
- Cite the sheet number whenever it is available.
- Identify the source drawing when relevant.
- State clearly when text or symbols are too small, cropped, obstructed, or unclear.
- Use the crop for detail and the parent page for surrounding sheet context.
- Distinguish visible evidence from inference.
"""


def _normalize_ids(values: Optional[Sequence[str]]) -> list[str]:
    return sorted({str(value).strip() for value in (values or []) if str(value).strip()})


def _source_scope(
    requested_source_ids: Optional[Sequence[str]],
    allowed_source_ids: Optional[Sequence[str]],
) -> tuple[list[str], Optional[str]]:
    """Return effective sources and a fail-closed reason when a pool is supplied."""
    requested = set(_normalize_ids(requested_source_ids))
    if allowed_source_ids is None:
        return sorted(requested), None

    allowed = set(_normalize_ids(allowed_source_ids))
    if not allowed:
        return [], "no_selected_drawing_sources"
    if requested:
        effective = requested & allowed
        if not effective:
            return [], "requested_sources_not_in_chat_pool"
        return sorted(effective), None
    return sorted(allowed), None


def _safe_image_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    try:
        candidate = Path(str(value)).expanduser().resolve()
        root = Path(DRAWING_EXTRACTION_FOLDER).expanduser().resolve()
        if not candidate.is_relative_to(root):
            return None
        if candidate.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
            return None
        if not candidate.is_file():
            return None
        return candidate
    except (OSError, RuntimeError, ValueError):
        return None


def _parent_page_path(image_path: Path, asset_kind: str) -> Optional[Path]:
    if asset_kind == "page":
        return image_path
    root = Path(DRAWING_EXTRACTION_FOLDER).expanduser().resolve()
    current = image_path.parent
    while current.is_relative_to(root):
        page = current / "page.png"
        if page.is_file():
            return page.resolve()
        if current == root:
            break
        current = current.parent
    return None


def _sheet_number(result: dict[str, Any], source_title: str) -> Optional[str]:
    explicit = str(result.get("sheet_number") or "").strip()
    if explicit:
        return explicit
    match = _SHEET_RE.search(source_title)
    return match.group(1).upper() if match else None


def _visual_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    rankings = response.get("rankings") or {}
    ranked = rankings.get("multi_vector") or {}
    results = ranked.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    if response.get("mode_used") == "multi_vector" and isinstance(
        response.get("results"), list
    ):
        return [dict(item) for item in response["results"] if isinstance(item, dict)]
    return []


def _ranking_debug(response: dict[str, Any], name: str) -> Optional[dict[str, Any]]:
    ranking = (response.get("rankings") or {}).get(name)
    if not isinstance(ranking, dict):
        return None
    return {
        "result_count": int(ranking.get("result_count") or 0),
        "duration_ms": ranking.get("duration_ms"),
        "score_space": ranking.get("score_space"),
        "retrieval_mode_used": ranking.get("retrieval_mode_used"),
        "error": ranking.get("error"),
    }


def _empty_result(
    *,
    mode: DrawingChatMode,
    project_id: str,
    source_ids: Sequence[str],
    fallback_reason: Optional[str],
    response: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    response = response or {}
    return {
        "text_context": None,
        "evidence": [],
        "images": [],
        "debug": {
            "requested_mode": mode,
            "mode_used": response.get("mode_used") or "existing",
            "project_id": project_id,
            "requested_source_ids": list(source_ids),
            "existing": _ranking_debug(response, "existing"),
            "multi_vector": _ranking_debug(response, "multi_vector"),
            "vision": None,
            "evidence": [],
            "fallback_reason": fallback_reason or response.get("fallback_reason"),
        },
    }


def _format_text_context(evidence: Sequence[dict[str, Any]]) -> str:
    blocks = [_VISUAL_INSTRUCTIONS.rstrip()]
    for item in evidence:
        lines = [
            f"### Visual evidence rank {item['rank']}",
            f"Source: {item['source_title']}",
            f"Sheet: {item['sheet_number'] or 'Sheet number unavailable'}",
            f"Page: {item['page_number']}",
            f"Asset: {item['asset_kind']}",
            f"Visual score: {item['score']}",
        ]
        if item.get("sheet_title"):
            lines.append(f"Sheet title: {item['sheet_title']}")
        if item.get("bbox_norm"):
            lines.append(f"Crop bounds: {item['bbox_norm']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks).strip()


async def build_visual_chat_evidence(
    *,
    query: str,
    project_id: str,
    mode: DrawingChatMode,
    requested_source_ids: Optional[Sequence[str]] = None,
    allowed_source_ids: Optional[Sequence[str]] = None,
    limit: int = MAX_VISUAL_RESULTS,
    retriever: ModeRetriever = retrieve_with_modes,
) -> dict[str, Any]:
    """Retrieve and prepare safe crop/page pairs without blocking normal chat."""
    effective_sources, scope_error = _source_scope(
        requested_source_ids,
        allowed_source_ids,
    )
    bounded_limit = max(1, min(int(limit), MAX_VISUAL_RESULTS))
    if mode == "existing":
        return _empty_result(
            mode=mode,
            project_id=project_id,
            source_ids=effective_sources,
            fallback_reason=None,
        )
    if scope_error:
        return _empty_result(
            mode=mode,
            project_id=project_id,
            source_ids=effective_sources,
            fallback_reason=scope_error,
        )

    try:
        response = await retriever(
            query,
            project_id=project_id,
            mode=mode,
            source_ids=effective_sources,
            limit=bounded_limit,
            existing_mode="auto",
            search_sources=True,
            search_notes=False,
        )
    except Exception as exc:
        logger.warning("Visual chat retrieval failed; normal chat will continue: {}", exc)
        return _empty_result(
            mode=mode,
            project_id=project_id,
            source_ids=effective_sources,
            fallback_reason=f"visual_retrieval_failed: {type(exc).__name__}: {exc}",
        )

    raw_results = _visual_results(response)
    evidence: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    seen_images: set[str] = set()
    seen_pages: set[tuple[str, int]] = set()

    for result in raw_results:
        if len(evidence) >= bounded_limit:
            break
        source_id = str(result.get("source_id") or result.get("parent_id") or "")
        page_number = int(result.get("page_number") or int(result.get("page_index") or 0) + 1)
        page_key = (source_id, page_number)
        if page_key in seen_pages:
            continue

        crop = _safe_image_path(result.get("evidence_crop") or result.get("image_path"))
        if crop is None:
            continue
        asset_kind = str(result.get("asset_kind") or "page")
        parent_page = _parent_page_path(crop, asset_kind)
        source_title = str(
            result.get("source_filename")
            or result.get("source_title")
            or source_id
            or "Drawing"
        ).strip()
        sheet_number = _sheet_number(result, source_title)
        rank = len(evidence) + 1
        item = {
            "rank": rank,
            "source_id": source_id,
            "source_title": source_title,
            "sheet_number": sheet_number,
            "sheet_title": str(result.get("sheet_title") or "").strip() or None,
            "page_number": page_number,
            "page_index": int(result.get("page_index") or 0),
            "asset_kind": asset_kind,
            "score": float(result.get("similarity") or result.get("score") or 0.0),
            "bbox_norm": result.get("bbox_norm"),
            "crop_path": str(crop),
            "parent_page_path": str(parent_page) if parent_page else None,
            "qdrant_point_id": result.get("qdrant_point_id") or result.get("id"),
        }
        evidence.append(item)
        seen_pages.add(page_key)

        for role, path in (("crop", crop), ("parent_page", parent_page)):
            if path is None or len(images) >= MAX_VISUAL_IMAGES:
                continue
            key = str(path)
            if key in seen_images:
                continue
            seen_images.add(key)
            images.append(
                {
                    "role": role,
                    "path": key,
                    "source_id": source_id,
                    "sheet_number": sheet_number,
                    "page_number": page_number,
                    "evidence_rank": rank,
                }
            )

    if not evidence:
        return _empty_result(
            mode=mode,
            project_id=project_id,
            source_ids=effective_sources,
            fallback_reason=response.get("fallback_reason") or "visual_evidence_empty",
            response=response,
        )

    debug_evidence = [dict(item) for item in evidence]
    debug = {
        "requested_mode": mode,
        "mode_used": response.get("mode_used") or mode,
        "project_id": project_id,
        "requested_source_ids": effective_sources,
        "existing": _ranking_debug(response, "existing"),
        "multi_vector": _ranking_debug(response, "multi_vector"),
        "vision": None,
        "evidence": debug_evidence,
        "fallback_reason": response.get("fallback_reason"),
    }
    return {
        "text_context": _format_text_context(evidence),
        "evidence": evidence,
        "images": images,
        "debug": debug,
    }


def _bounded_image_bytes(
    path: Path,
    *,
    max_image_bytes: int,
    max_image_edge: int,
) -> Optional[tuple[bytes, str, int, int]]:
    """Read an image and shrink it when needed, returning bytes and dimensions."""
    try:
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        width = 0
        height = 0
        try:
            pixmap = fitz.Pixmap(str(path))
            width, height = pixmap.width, pixmap.height
            shrunk = False
            while max(pixmap.width, pixmap.height) > max_image_edge:
                pixmap.shrink(1)
                shrunk = True
            if shrunk or len(raw) > max_image_bytes:
                raw = pixmap.tobytes("png")
                mime = "image/png"
                width, height = pixmap.width, pixmap.height
        except Exception:
            # Existing rendered assets are validated by file type and size below.
            pass
        if not raw or len(raw) > max_image_bytes:
            return None
        return raw, mime, width, height
    except OSError:
        return None


def encode_visual_image_blocks(
    images: Sequence[dict[str, Any]],
    *,
    max_images: int = MAX_VISUAL_IMAGES,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_image_edge: int = MAX_IMAGE_EDGE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Encode validated local images for a remote multimodal chat request."""
    blocks: list[dict[str, Any]] = []
    attached: list[dict[str, Any]] = []
    seen: set[str] = set()
    for image in images:
        if len(blocks) >= max_images:
            break
        path = _safe_image_path(image.get("path"))
        if path is None or str(path) in seen:
            continue
        bounded = _bounded_image_bytes(
            path,
            max_image_bytes=max_image_bytes,
            max_image_edge=max_image_edge,
        )
        if bounded is None:
            continue
        raw, mime, width, height = bounded
        seen.add(str(path))
        encoded = base64.b64encode(raw).decode("ascii")
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
        attached.append(
            {
                "role": image.get("role"),
                "path": str(path),
                "source_id": image.get("source_id"),
                "sheet_number": image.get("sheet_number"),
                "page_number": image.get("page_number"),
                "evidence_rank": image.get("evidence_rank"),
                "byte_count": len(raw),
                "image_width": width or None,
                "image_height": height or None,
            }
        )
    return blocks, attached


def attach_image_blocks_to_latest_user_message(
    messages: Sequence[BaseMessage],
    image_blocks: Sequence[dict[str, Any]],
) -> list[BaseMessage]:
    """Copy the latest user message with images; never mutate checkpointed history."""
    copied = list(messages)
    if not image_blocks:
        return copied
    for index in range(len(copied) - 1, -1, -1):
        message = copied[index]
        if str(getattr(message, "type", "")).lower() not in {"human", "user"}:
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            text_parts = list(content)
        else:
            text_parts = [{"type": "text", "text": str(content)}]
        copied[index] = message.model_copy(
            update={"content": text_parts + [dict(block) for block in image_blocks]}
        )
        break
    return copied
