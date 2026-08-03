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


def _hit(
    point_id: str,
    score: float,
    page_index: int,
    asset_kind: str,
    *,
    source_filename: str = "plans.pdf",
):
    return MultiVectorSearchHit(
        point_id=point_id,
        score=score,
        payload={
            "project_id": "project:alpha",
            "source_id": "source:plans",
            "source_filename": source_filename,
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
    assert items[0].title == "A101 - Floor Plan"
    assert items[0].raw["multi_vector"] is True
    assert items[0].raw["retrieval_backend"] == "qdrant_maxsim"
    assert items[0].raw["evidence_crop"] == "/data/crop-page-one.png"
    assert searcher.calls[0]["source_ids"] == ["source:plans"]
    assert searcher.calls[0]["limit"] == 8


def test_retrieval_enriches_legacy_crop_filename_with_original_source(monkeypatch):
    async def fake_ready(project_id, requested_source_ids=None):
        return ["source:plans"]

    async def fake_embed(query):
        return {
            "vectors": [[0.1] * 128],
            "vector_count": 1,
            "dimension": 128,
        }

    async def fake_source_name(source_id):
        assert source_id == "source:plans"
        return "Page_007_P203.pdf"

    legacy_hit = _hit(
        "legacy-crop",
        29.5,
        0,
        "grid_crop",
        source_filename="grid_r1_c0.png",
    )
    legacy_hit.payload["sheet_number"] = None
    legacy_hit.payload["sheet_title"] = None

    monkeypatch.setattr(retrieval, "ready_project_source_ids", fake_ready)
    items = asyncio.run(
        retrieval.retrieve_multivector_evidence(
            "locate the gas regulator",
            project_id="project:alpha",
            source_ids=["source:plans"],
            searcher=_FakeSearcher([legacy_hit]),
            query_embedder=fake_embed,
            source_name_resolver=fake_source_name,
        )
    )

    assert items[0].title == "Page_007_P203.pdf - Page 1"
    assert items[0].content == "Visual evidence from Page_007_P203.pdf, page 1."
    assert items[0].raw["source_filename"] == "Page_007_P203.pdf"
    assert items[0].raw["visual_asset_filename"] == "grid_r1_c0.png"


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
