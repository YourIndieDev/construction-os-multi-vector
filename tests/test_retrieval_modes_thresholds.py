"""Threshold and empty-result behavior for Phase 7 retrieval modes."""

from __future__ import annotations

import asyncio

from construction_os.drawing.retrieval_modes import retrieve_with_modes
from construction_os.retrieval.types import EvidenceBundle, EvidenceItem


def _existing_item() -> EvidenceItem:
    return EvidenceItem(
        id="existing-one",
        parent_id="source:plans",
        title="Existing result",
        score=0.65,
        source="vector",
        raw={"similarity": 0.65},
    )


def test_compare_forwards_independent_score_thresholds():
    observed: dict[str, float | None] = {}

    async def fake_existing(query, **kwargs):
        observed["existing"] = kwargs["minimum_score"]
        return EvidenceBundle(
            items=[_existing_item()],
            retrieval_mode_used="vector",
        )

    async def fake_multi_vector(query, **kwargs):
        observed["multi_vector"] = kwargs["minimum_score"]
        return []

    result = asyncio.run(
        retrieve_with_modes(
            "compare gas evidence",
            project_id="project:test",
            mode="compare",
            existing_minimum_score=0.35,
            multi_vector_minimum_score=9.0,
            existing_retriever=fake_existing,
            multi_vector_retriever=fake_multi_vector,
        )
    )

    assert observed == {"existing": 0.35, "multi_vector": 9.0}
    assert result["rankings"]["existing"]["minimum_score"] == 0.35
    assert result["rankings"]["multi_vector"]["minimum_score"] == 9.0


def test_empty_multi_vector_mode_falls_back_to_existing():
    async def fake_existing(query, **kwargs):
        return EvidenceBundle(
            items=[_existing_item()],
            retrieval_mode_used="vector",
        )

    async def empty_multi_vector(query, **kwargs):
        return []

    result = asyncio.run(
        retrieve_with_modes(
            "find gas piping",
            project_id="project:test",
            mode="multi_vector",
            existing_retriever=fake_existing,
            multi_vector_retriever=empty_multi_vector,
        )
    )

    assert result["requested_mode"] == "multi_vector"
    assert result["mode_used"] == "existing"
    assert result["fallback_reason"] == "multi_vector_empty"
    assert result["result_count"] == 1
