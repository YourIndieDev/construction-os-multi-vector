"""Tests for isolated existing, multi-vector, and compare retrieval modes."""

from __future__ import annotations

import asyncio

import pytest

from construction_os.drawing.retrieval_modes import (
    RetrievalModeExecutionError,
    retrieve_with_modes,
)
from construction_os.retrieval.types import EvidenceBundle, EvidenceItem


def _existing_item(item_id: str = "existing-one", score: float = 0.81) -> EvidenceItem:
    return EvidenceItem(
        id=item_id,
        parent_id="source:plans",
        title="Existing result",
        score=score,
        matches=["existing content"],
        content="existing content",
        source="vector",
        raw={"similarity": score},
    )


def _visual_item(item_id: str = "visual-one", score: float = 11.4) -> EvidenceItem:
    return EvidenceItem(
        id=item_id,
        parent_id="source:plans",
        title="P203 — Plumbing Gas Floor Plan",
        score=score,
        matches=["/data/p203-grid.png"],
        content="Visual evidence from Page_007_P203.pdf, page 1.",
        source="drawing",
        raw={
            "similarity": score,
            "multi_vector": True,
            "retrieval_backend": "qdrant_maxsim",
            "evidence_crop": "/data/p203-grid.png",
        },
    )


def test_existing_is_default_and_does_not_call_multi_vector():
    calls: list[tuple[str, dict]] = []

    async def fake_existing(query, **kwargs):
        calls.append((query, kwargs))
        return EvidenceBundle(
            items=[_existing_item()],
            retrieval_mode_used="hybrid",
        )

    async def unexpected_multi_vector(*args, **kwargs):
        raise AssertionError("multi-vector retrieval must not run in default mode")

    result = asyncio.run(
        retrieve_with_modes(
            "find the gas plan",
            project_id="project:test",
            existing_retriever=fake_existing,
            multi_vector_retriever=unexpected_multi_vector,
        )
    )

    assert result["requested_mode"] == "existing"
    assert result["mode_used"] == "existing"
    assert result["result_count"] == 1
    assert result["results"][0]["rank"] == 1
    assert result["results"][0]["similarity"] == 0.81
    assert result["rankings"]["existing"]["retrieval_mode_used"] == "hybrid"
    assert result["rankings"]["existing"]["score_space"] == (
        "native_existing_retrieval"
    )
    assert result["rankings"]["existing"]["duration_ms"] >= 0
    assert calls[0][1]["mode"] == "auto"


def test_multi_vector_mode_returns_native_maxsim_ranking():
    observed: dict = {}

    async def fake_multi_vector(query, **kwargs):
        observed.update(kwargs)
        return [_visual_item()]

    async def unexpected_existing(*args, **kwargs):
        raise AssertionError("existing retrieval must not run after visual success")

    result = asyncio.run(
        retrieve_with_modes(
            "locate the LPG regulator",
            project_id="project:test",
            mode="multi_vector",
            source_ids=["source:plans"],
            existing_retriever=unexpected_existing,
            multi_vector_retriever=fake_multi_vector,
        )
    )

    assert result["mode_used"] == "multi_vector"
    assert result["results"][0]["similarity"] == 11.4
    assert result["results"][0]["rank"] == 1
    assert result["rankings"]["multi_vector"]["score_space"] == "qdrant_maxsim"
    assert observed["source_ids"] == ["source:plans"]


def test_multi_vector_failure_falls_back_to_existing():
    async def failing_multi_vector(*args, **kwargs):
        raise RuntimeError("qdrant unavailable")

    async def fake_existing(query, **kwargs):
        return EvidenceBundle(
            items=[_existing_item()],
            retrieval_mode_used="vector",
        )

    result = asyncio.run(
        retrieve_with_modes(
            "find the gas plan",
            project_id="project:test",
            mode="multi_vector",
            existing_retriever=fake_existing,
            multi_vector_retriever=failing_multi_vector,
        )
    )

    assert result["requested_mode"] == "multi_vector"
    assert result["mode_used"] == "existing"
    assert "qdrant unavailable" in result["fallback_reason"]
    assert result["result_count"] == 1
    assert result["rankings"]["multi_vector"]["error"] is not None
    assert result["rankings"]["existing"]["error"] is None


def test_compare_keeps_rankings_timings_and_scores_separate():
    async def fake_existing(query, **kwargs):
        await asyncio.sleep(0)
        return EvidenceBundle(
            items=[_existing_item(score=0.73)],
            retrieval_mode_used="hybrid",
        )

    async def fake_multi_vector(query, **kwargs):
        await asyncio.sleep(0)
        return [_visual_item(score=12.75)]

    result = asyncio.run(
        retrieve_with_modes(
            "compare gas plan retrieval",
            project_id="project:test",
            mode="compare",
            source_ids=["source:plans"],
            existing_retriever=fake_existing,
            multi_vector_retriever=fake_multi_vector,
        )
    )

    assert result["requested_mode"] == "compare"
    assert result["mode_used"] == "compare"
    assert "results" not in result
    existing = result["rankings"]["existing"]
    visual = result["rankings"]["multi_vector"]
    assert existing["results"][0]["similarity"] == 0.73
    assert visual["results"][0]["similarity"] == 12.75
    assert existing["results"][0]["rank"] == 1
    assert visual["results"][0]["rank"] == 1
    assert existing["score_space"] != visual["score_space"]
    assert existing["duration_ms"] >= 0
    assert visual["duration_ms"] >= 0


def test_compare_reports_partial_failure_without_hiding_existing_results():
    async def fake_existing(query, **kwargs):
        return EvidenceBundle(
            items=[_existing_item()],
            retrieval_mode_used="vector",
        )

    async def failing_multi_vector(*args, **kwargs):
        raise RuntimeError("colsmol offline")

    result = asyncio.run(
        retrieve_with_modes(
            "compare retrieval",
            project_id="project:test",
            mode="compare",
            existing_retriever=fake_existing,
            multi_vector_retriever=failing_multi_vector,
        )
    )

    assert result["mode_used"] == "compare"
    assert "colsmol offline" in result["fallback_reason"]
    assert result["rankings"]["existing"]["result_count"] == 1
    assert result["rankings"]["multi_vector"]["result_count"] == 0


def test_both_compare_backends_failing_raises():
    async def failing_existing(*args, **kwargs):
        raise RuntimeError("surreal unavailable")

    async def failing_multi_vector(*args, **kwargs):
        raise RuntimeError("qdrant unavailable")

    with pytest.raises(RetrievalModeExecutionError) as exc_info:
        asyncio.run(
            retrieve_with_modes(
                "compare retrieval",
                project_id="project:test",
                mode="compare",
                existing_retriever=failing_existing,
                multi_vector_retriever=failing_multi_vector,
            )
        )

    assert "surreal unavailable" in str(exc_info.value)
    assert "qdrant unavailable" in str(exc_info.value)
