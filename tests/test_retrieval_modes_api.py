"""API contract tests for Phase 7 retrieval modes."""

from __future__ import annotations

import asyncio

from api.routers import multivector_search as api


def test_retrieve_api_defaults_to_existing(monkeypatch):
    observed: dict = {}

    async def fake_retrieve(query, **kwargs):
        observed["query"] = query
        observed.update(kwargs)
        return {
            "requested_mode": "existing",
            "mode_used": "existing",
            "fallback_reason": None,
            "project_id": kwargs["project_id"],
            "result_count": 1,
            "results": [{"id": "existing-one", "rank": 1}],
            "rankings": {
                "existing": {
                    "duration_ms": 1.2,
                    "result_count": 1,
                    "results": [{"id": "existing-one", "rank": 1}],
                }
            },
        }

    monkeypatch.setattr(api, "retrieve_with_modes", fake_retrieve)
    body = api.DrawingRetrievalModeRequest(
        query="find the gas plan",
        project_id="project:test",
    )

    result = asyncio.run(api.retrieve_drawings_by_mode(body))

    assert body.mode == "existing"
    assert result["mode_used"] == "existing"
    assert observed["query"] == "find the gas plan"
    assert observed["mode"] == "existing"
    assert observed["existing_mode"] == "auto"
    assert observed["source_ids"] == []


def test_retrieve_api_forwards_compare_options(monkeypatch):
    observed: dict = {}

    async def fake_retrieve(query, **kwargs):
        observed["query"] = query
        observed.update(kwargs)
        return {
            "requested_mode": "compare",
            "mode_used": "compare",
            "fallback_reason": None,
            "project_id": kwargs["project_id"],
            "rankings": {
                "existing": {"duration_ms": 3.0, "results": []},
                "multi_vector": {"duration_ms": 7.0, "results": []},
            },
        }

    monkeypatch.setattr(api, "retrieve_with_modes", fake_retrieve)
    body = api.DrawingRetrievalModeRequest(
        query="compare LPG routing evidence",
        project_id="project:test",
        mode="compare",
        source_ids=["source:p203"],
        limit=5,
        existing_mode="hybrid",
        search_notes=False,
        minimum_score=0.3,
    )

    result = asyncio.run(api.retrieve_drawings_by_mode(body))

    assert result["mode_used"] == "compare"
    assert observed["mode"] == "compare"
    assert observed["source_ids"] == ["source:p203"]
    assert observed["limit"] == 5
    assert observed["existing_mode"] == "hybrid"
    assert observed["search_notes"] is False
    assert observed["minimum_score"] == 0.3
