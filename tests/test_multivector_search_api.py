"""Tests for the isolated multi-vector visual search API."""

from __future__ import annotations

import asyncio

from api.routers import multivector_search as api
from construction_os.retrieval.types import EvidenceItem


def test_search_api_returns_existing_search_result_shape(monkeypatch):
    async def fake_retrieve(query, **kwargs):
        assert query == "find the main entrance"
        assert kwargs["project_id"] == "project:alpha"
        assert kwargs["source_ids"] == ["source:plans"]
        return [
            EvidenceItem(
                id="point-one",
                parent_id="source:plans",
                title="A101 — Floor Plan",
                score=9.5,
                matches=["/data/page.png"],
                content="Visual evidence from plans.pdf, page 1.",
                source="drawing",
                raw={
                    "drawing": True,
                    "multi_vector": True,
                    "image_path": "/data/page.png",
                },
            )
        ]

    monkeypatch.setattr(api, "retrieve_multivector_evidence", fake_retrieve)
    body = api.MultiVectorSearchRequest(
        query="find the main entrance",
        project_id="project:alpha",
        source_ids=["source:plans"],
        limit=5,
    )

    result = asyncio.run(api.search_multivector_drawings(body))

    assert result["mode"] == "multi_vector"
    assert result["result_count"] == 1
    assert result["results"][0]["id"] == "point-one"
    assert result["results"][0]["drawing"] is True
    assert result["results"][0]["multi_vector"] is True
    assert result["results"][0]["similarity"] == 9.5
