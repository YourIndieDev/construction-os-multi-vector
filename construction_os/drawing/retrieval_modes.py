"""Isolated retrieval-mode orchestration for existing and multi-vector evidence."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Literal, Optional, Sequence

from construction_os.drawing.multivector_retrieval import retrieve_multivector_evidence
from construction_os.retrieval import retrieve
from construction_os.retrieval.types import EvidenceBundle, EvidenceItem, RetrievalMode

DrawingRetrievalMode = Literal["existing", "multi_vector", "compare"]
ExistingRetriever = Callable[..., Awaitable[EvidenceBundle]]
MultiVectorRetriever = Callable[..., Awaitable[list[EvidenceItem]]]


class RetrievalModeExecutionError(RuntimeError):
    """Raised when a requested retrieval mode cannot produce any result set."""


def _error_text(exc: BaseException) -> str:
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _ranked_results(items: Sequence[EvidenceItem]) -> list[dict]:
    """Serialize one backend's ranking without modifying its native scores."""
    ranked: list[dict] = []
    for rank, item in enumerate(items, start=1):
        result = item.to_search_result()
        result["rank"] = rank
        ranked.append(result)
    return ranked


async def _run_existing(
    query: str,
    *,
    project_id: str,
    limit: int,
    existing_mode: RetrievalMode,
    search_sources: bool,
    search_notes: bool,
    minimum_score: float,
    retriever: ExistingRetriever,
) -> dict:
    started = time.perf_counter()
    try:
        bundle = await retriever(
            query,
            project_id=project_id,
            mode=existing_mode,
            limit=limit,
            search_sources=search_sources,
            search_notes=search_notes,
            minimum_score=minimum_score,
        )
        items = list(bundle.items[:limit])
        return {
            "backend": "existing",
            "score_space": "native_existing_retrieval",
            "minimum_score": minimum_score,
            "retrieval_mode_used": bundle.retrieval_mode_used,
            "fallback_reason": bundle.fallback_reason,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "result_count": len(items),
            "results": _ranked_results(items),
            "error": None,
        }
    except Exception as exc:
        return {
            "backend": "existing",
            "score_space": "native_existing_retrieval",
            "minimum_score": minimum_score,
            "retrieval_mode_used": existing_mode,
            "fallback_reason": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "result_count": 0,
            "results": [],
            "error": _error_text(exc),
        }


async def _run_multi_vector(
    query: str,
    *,
    project_id: str,
    source_ids: Sequence[str],
    limit: int,
    minimum_score: Optional[float],
    retriever: MultiVectorRetriever,
) -> dict:
    started = time.perf_counter()
    try:
        items = await retriever(
            query,
            project_id=project_id,
            source_ids=list(source_ids),
            limit=limit,
            minimum_score=minimum_score,
        )
        selected = list(items[:limit])
        return {
            "backend": "multi_vector",
            "score_space": "qdrant_maxsim",
            "minimum_score": minimum_score,
            "retrieval_mode_used": "multi_vector",
            "fallback_reason": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "result_count": len(selected),
            "results": _ranked_results(selected),
            "error": None,
        }
    except Exception as exc:
        return {
            "backend": "multi_vector",
            "score_space": "qdrant_maxsim",
            "minimum_score": minimum_score,
            "retrieval_mode_used": "multi_vector",
            "fallback_reason": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "result_count": 0,
            "results": [],
            "error": _error_text(exc),
        }


async def retrieve_with_modes(
    query: str,
    *,
    project_id: str,
    mode: DrawingRetrievalMode = "existing",
    source_ids: Optional[Sequence[str]] = None,
    limit: int = 10,
    existing_mode: RetrievalMode = "auto",
    search_sources: bool = True,
    search_notes: bool = True,
    existing_minimum_score: float = 0.2,
    multi_vector_minimum_score: Optional[float] = None,
    existing_retriever: ExistingRetriever = retrieve,
    multi_vector_retriever: MultiVectorRetriever = retrieve_multivector_evidence,
) -> dict:
    """Run existing, multi-vector, or side-by-side retrieval without score fusion.

    Existing retrieval is the default. A failed or empty multi-vector-only request
    falls back to existing retrieval and reports the reason. Compare mode preserves
    independent rankings, timings, thresholds, and native scores.
    """
    text = query.strip()
    project = project_id.strip()
    if not text:
        raise ValueError("query must not be empty")
    if not project:
        raise ValueError("project_id must not be empty")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")

    requested_sources = list(source_ids or [])
    existing_kwargs = dict(
        query=text,
        project_id=project,
        limit=limit,
        existing_mode=existing_mode,
        search_sources=search_sources,
        search_notes=search_notes,
        minimum_score=existing_minimum_score,
        retriever=existing_retriever,
    )
    multi_vector_kwargs = dict(
        query=text,
        project_id=project,
        source_ids=requested_sources,
        limit=limit,
        minimum_score=multi_vector_minimum_score,
        retriever=multi_vector_retriever,
    )

    if mode == "existing":
        existing_run = await _run_existing(**existing_kwargs)
        if existing_run["error"]:
            raise RetrievalModeExecutionError(existing_run["error"])
        return {
            "requested_mode": "existing",
            "mode_used": "existing",
            "fallback_reason": existing_run["fallback_reason"],
            "project_id": project,
            "source_ids": requested_sources,
            "result_count": existing_run["result_count"],
            "results": existing_run["results"],
            "rankings": {"existing": existing_run},
        }

    if mode == "multi_vector":
        multi_vector_run = await _run_multi_vector(**multi_vector_kwargs)
        if not multi_vector_run["error"] and multi_vector_run["result_count"] > 0:
            return {
                "requested_mode": "multi_vector",
                "mode_used": "multi_vector",
                "fallback_reason": None,
                "project_id": project,
                "source_ids": requested_sources,
                "result_count": multi_vector_run["result_count"],
                "results": multi_vector_run["results"],
                "rankings": {"multi_vector": multi_vector_run},
            }

        fallback_reason = (
            f"multi_vector_failed: {multi_vector_run['error']}"
            if multi_vector_run["error"]
            else "multi_vector_empty"
        )
        existing_run = await _run_existing(**existing_kwargs)
        if existing_run["error"]:
            raise RetrievalModeExecutionError(
                "{0}; existing fallback failed ({1})".format(
                    fallback_reason, existing_run["error"]
                )
            )
        return {
            "requested_mode": "multi_vector",
            "mode_used": "existing",
            "fallback_reason": fallback_reason,
            "project_id": project,
            "source_ids": requested_sources,
            "result_count": existing_run["result_count"],
            "results": existing_run["results"],
            "rankings": {
                "multi_vector": multi_vector_run,
                "existing": existing_run,
            },
        }

    if mode != "compare":
        raise ValueError(f"Unsupported retrieval mode: {mode}")

    existing_run, multi_vector_run = await asyncio.gather(
        _run_existing(**existing_kwargs),
        _run_multi_vector(**multi_vector_kwargs),
    )
    if existing_run["error"] and multi_vector_run["error"]:
        raise RetrievalModeExecutionError(
            "existing failed ({0}); multi_vector failed ({1})".format(
                existing_run["error"], multi_vector_run["error"]
            )
        )

    errors = []
    if existing_run["error"]:
        errors.append(f"existing_failed: {existing_run['error']}")
    if multi_vector_run["error"]:
        errors.append(f"multi_vector_failed: {multi_vector_run['error']}")

    return {
        "requested_mode": "compare",
        "mode_used": "compare",
        "fallback_reason": "; ".join(errors) or None,
        "project_id": project,
        "source_ids": requested_sources,
        "rankings": {
            "existing": existing_run,
            "multi_vector": multi_vector_run,
        },
    }
