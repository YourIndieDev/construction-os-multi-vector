"""Tests for safe, bounded visual evidence assembly."""

from __future__ import annotations

import asyncio
from pathlib import Path

from construction_os.drawing import chat_evidence


def _result(
    *,
    point_id: str,
    source_id: str,
    page_index: int,
    image_path: Path,
    score: float,
) -> dict:
    return {
        "id": point_id,
        "qdrant_point_id": point_id,
        "source_id": source_id,
        "parent_id": source_id,
        "source_filename": "Page_007_P203.pdf",
        "asset_kind": "grid_crop",
        "page_index": page_index,
        "page_number": page_index + 1,
        "image_path": str(image_path),
        "evidence_crop": str(image_path),
        "similarity": score,
        "bbox_norm": {"x0": 0.0, "y0": 0.4, "x1": 0.4, "y1": 1.0},
    }


def _make_page(root: Path, page_index: int, crop_name: str) -> tuple[Path, Path]:
    page_dir = root / "multivector" / "source_plans" / "run" / f"page_{page_index:04d}"
    crop_dir = page_dir / "crops"
    crop_dir.mkdir(parents=True)
    page = page_dir / "page.png"
    crop = crop_dir / crop_name
    page.write_bytes(b"page-image")
    crop.write_bytes(b"crop-image")
    return page, crop


def test_visual_evidence_limits_deduplicates_and_adds_parent_pages(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    page_a, crop_a = _make_page(root, 0, "grid_r1_c0.png")
    page_b, crop_b = _make_page(root, 1, "grid_r0_c2.png")
    _, crop_a_duplicate = _make_page(root, 0, "grid_r0_c0.png")
    monkeypatch.setattr(chat_evidence, "DRAWING_EXTRACTION_FOLDER", str(root))

    async def fake_retriever(query, **kwargs):
        assert kwargs["mode"] == "compare"
        assert kwargs["source_ids"] == ["source:plans"]
        assert kwargs["limit"] == 3
        return {
            "requested_mode": "compare",
            "mode_used": "compare",
            "fallback_reason": None,
            "rankings": {
                "existing": {
                    "result_count": 0,
                    "duration_ms": 4.0,
                    "score_space": "native_existing_retrieval",
                    "retrieval_mode_used": "vector",
                    "results": [],
                    "error": None,
                },
                "multi_vector": {
                    "result_count": 3,
                    "duration_ms": 7.0,
                    "score_space": "qdrant_maxsim",
                    "retrieval_mode_used": "multi_vector",
                    "results": [
                        _result(
                            point_id="one",
                            source_id="source:plans",
                            page_index=0,
                            image_path=crop_a,
                            score=29.5,
                        ),
                        _result(
                            point_id="duplicate-page",
                            source_id="source:plans",
                            page_index=0,
                            image_path=crop_a_duplicate,
                            score=28.0,
                        ),
                        _result(
                            point_id="two",
                            source_id="source:plans",
                            page_index=1,
                            image_path=crop_b,
                            score=20.0,
                        ),
                    ],
                    "error": None,
                },
            },
        }

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="locate the LPG regulator",
            project_id="project:test",
            mode="compare",
            requested_source_ids=["source:plans", "source:outside"],
            allowed_source_ids=["source:plans"],
            limit=9,
            retriever=fake_retriever,
        )
    )

    assert len(result["evidence"]) == 2
    assert [item["page_number"] for item in result["evidence"]] == [1, 2]
    assert result["evidence"][0]["sheet_number"] == "P203"
    assert result["evidence"][0]["source_title"] == "Page_007_P203.pdf"
    assert result["evidence"][0]["parent_page_path"] == str(page_a.resolve())
    assert result["evidence"][1]["parent_page_path"] == str(page_b.resolve())
    assert len(result["images"]) == 4
    assert len({image["path"] for image in result["images"]}) == 4
    assert "Do not invent dimensions" in result["text_context"]
    assert "Sheet: P203" in result["text_context"]
    assert result["debug"]["existing"]["result_count"] == 0
    assert result["debug"]["multi_vector"]["result_count"] == 3
    assert "base64" not in str(result["debug"])


def test_visual_evidence_rejects_paths_outside_drawing_root(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not-allowed")
    monkeypatch.setattr(chat_evidence, "DRAWING_EXTRACTION_FOLDER", str(root))

    async def fake_retriever(query, **kwargs):
        return {
            "requested_mode": "multi_vector",
            "mode_used": "multi_vector",
            "fallback_reason": None,
            "rankings": {
                "multi_vector": {
                    "result_count": 1,
                    "duration_ms": 1.0,
                    "score_space": "qdrant_maxsim",
                    "retrieval_mode_used": "multi_vector",
                    "results": [
                        _result(
                            point_id="outside",
                            source_id="source:plans",
                            page_index=0,
                            image_path=outside,
                            score=10.0,
                        )
                    ],
                    "error": None,
                }
            },
        }

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="find it",
            project_id="project:test",
            mode="multi_vector",
            retriever=fake_retriever,
        )
    )

    assert result["evidence"] == []
    assert result["images"] == []
    assert result["debug"]["fallback_reason"] == "visual_evidence_empty"


def test_visual_retrieval_failure_never_raises():
    async def failing_retriever(*args, **kwargs):
        raise RuntimeError("qdrant offline")

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="find it",
            project_id="project:test",
            mode="multi_vector",
            retriever=failing_retriever,
        )
    )

    assert result["evidence"] == []
    assert "qdrant offline" in result["debug"]["fallback_reason"]


def test_existing_mode_does_not_call_visual_retriever():
    async def unexpected(*args, **kwargs):
        raise AssertionError("visual retriever should not run")

    result = asyncio.run(
        chat_evidence.build_visual_chat_evidence(
            query="hello",
            project_id="project:test",
            mode="existing",
            retriever=unexpected,
        )
    )

    assert result["evidence"] == []
    assert result["debug"]["requested_mode"] == "existing"
