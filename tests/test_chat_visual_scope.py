"""Source-pool isolation tests for visual project chat."""

from __future__ import annotations

import asyncio

from construction_os.drawing import chat_evidence


def test_empty_selected_source_pool_skips_retrieval():
    async def unexpected(*args, **kwargs):
        raise AssertionError("retrieval must not broaden an empty source pool")

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="find the regulator",
            project_id="project:test",
            mode="multi_vector",
            requested_source_ids=["source:p203"],
            allowed_source_ids=[],
            retriever=unexpected,
        )
    )

    assert result["evidence"] == []
    assert result["debug"]["fallback_reason"] == "no_selected_drawing_sources"


def test_requested_source_outside_selected_pool_skips_retrieval():
    async def unexpected(*args, **kwargs):
        raise AssertionError("retrieval must not escape the selected source pool")

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="find the regulator",
            project_id="project:test",
            mode="compare",
            requested_source_ids=["source:outside"],
            allowed_source_ids=["source:p203"],
            retriever=unexpected,
        )
    )

    assert result["evidence"] == []
    assert result["debug"]["fallback_reason"] == (
        "requested_sources_not_in_chat_pool"
    )


def test_no_pool_argument_keeps_explicit_project_scoped_sources():
    observed = {}

    async def fake_retriever(query, **kwargs):
        observed.update(kwargs)
        return {
            "requested_mode": "multi_vector",
            "mode_used": "multi_vector",
            "fallback_reason": "multi_vector_empty",
            "results": [],
            "rankings": {
                "multi_vector": {
                    "result_count": 0,
                    "results": [],
                    "duration_ms": 1.0,
                    "error": None,
                }
            },
        }

    asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="find the regulator",
            project_id="project:test",
            mode="multi_vector",
            requested_source_ids=["source:p203"],
            allowed_source_ids=None,
            retriever=fake_retriever,
        )
    )

    assert observed["source_ids"] == ["source:p203"]
