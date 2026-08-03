from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routers import multivector_search


def test_resolve_evidence_image_accepts_file_inside_drawing_root(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    image = root / "multivector" / "source_a" / "page_0000" / "page.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    monkeypatch.setattr(multivector_search, "DRAWING_EXTRACTION_FOLDER", str(root))

    assert multivector_search._resolve_evidence_image_path(str(image)) == image.resolve()
    assert (
        multivector_search._resolve_evidence_image_path(
            "multivector/source_a/page_0000/page.png"
        )
        == image.resolve()
    )


def test_resolve_evidence_image_rejects_path_traversal(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    monkeypatch.setattr(multivector_search, "DRAWING_EXTRACTION_FOLDER", str(root))

    with pytest.raises(HTTPException) as exc:
        multivector_search._resolve_evidence_image_path(str(outside))

    assert exc.value.status_code == 400


def test_resolve_evidence_image_rejects_unsupported_type(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    document = root / "evidence.svg"
    document.parent.mkdir(parents=True)
    document.write_text("<svg />", encoding="utf-8")
    monkeypatch.setattr(multivector_search, "DRAWING_EXTRACTION_FOLDER", str(root))

    with pytest.raises(HTTPException) as exc:
        multivector_search._resolve_evidence_image_path(str(document))

    assert exc.value.status_code == 400
