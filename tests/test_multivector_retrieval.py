"""Tests for ColSmol + Qdrant visual evidence retrieval."""

from __future__ import annotations

import asyncio

from construction_os.drawing import multivector_retrieval as retrieval
from construction_os.drawing.multivector_search import MultiVectorSearchHit


class _FakeSearcher:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.hits


def _hit(point_id: str, score: float, page_index: int, asset_kind: str):
    return MultiVectorSearchHit(
        point_id=point_id,
        score=score,
        payload={
            "project_id": "project:alpha",
            "source_id": "source:plans",
            "source_filename": "plans.pdf",
            "asset_kind": asset_kind,
            "page_index": page_index,
            "page_number": page_index + 1,
            "image_path": f"/data/{point_id}.png",
            "sheet_number": "A101" if page_index == 0 else "A102",
            "sheet_title": "Floor Plan" if page_index == 0 else "Reflected Ceiling Plan",
        },
    )


def test_retrieval_filters_ready_sources_and_deduplicates_same_page(monkeypatch):
    async def fake_ready(project_id, requested_source_ids=None):
        assert project_id == "project:alpha"
        assert requested_source_ids == ["source:plans", "source:disabled"]
        return ["source:plans"]

    async def fake_embed(query):
        assert query == "find the main entry"
        return {
            "vectors": [[0.1] * 128, [0.2] * 128],
            "vector_count": 2,
            "dimension": 128,
        }

    searcher = _FakeSearcher(
        [
            _hit("crop-page-one", 11.0, 0, "grid_crop"),
            _hit("full-page-one", 10.0, 0, "page"),
            _hit("page-two", 9.0, 1, "page"),
        ]
    )
    monkeypatch.setattr(retrieval, "ready_project_source_ids", fake_ready)

    items = asyncio.run(
        retrieval.retrieve_multivector_evidence(
            "find the main entry",
            project_id="project:alpha",
            source_ids=["source:plans", "source:disabled"],
            limit=2,
            searcher=searcher,
            query_embedder=fake_embed,
        )
    )

    assert [item.id for item in items] == ["crop-page-one", "page-two"]
    assert items[0].title == "A101 — Floor Plan"
    assert items[0].raw["multi_vector"] is True
    assert items[0].raw["retrieval_backend"] == "qdrant_maxsim"
    assert items[0].raw["evidence_crop"] == "/data/crop-page-one.png"
    assert searcher.calls[0]["source_ids"] == ["source:plans"]
    assert searcher.calls[0]["limit"] == 8


def test_retrieval_returns_empty_when_no_ready_sources(monkeypatch):
    async def fake_ready(project_id, requested_source_ids=None):
        return []

    async def should_not_embed(query):
        raise AssertionError("query embedding should not run")

    monkeypatch.setattr(retrieval, "ready_project_source_ids", fake_ready)

    items = asyncio.run(
        retrieval.retrieve_multivector_evidence(
            "door schedule",
            project_id="project:alpha",
            query_embedder=should_not_embed,
        )
    )
    assert items == []
