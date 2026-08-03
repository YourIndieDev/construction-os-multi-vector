"""Contract tests that do not download or load the real ColSmol checkpoint."""

import io
import os

os.environ["COLSMOL_SKIP_MODEL_LOAD"] = "true"

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app, runtime


def _png_bytes(width: int = 32, height: int = 24) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_health_contract_reports_test_runtime():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "test"
    assert body["ready"] is False
    assert body["model"] == "vidore/colSmol-256M"
    assert body["device"] == "test"


def test_query_endpoint_validates_empty_text():
    with TestClient(app) as client:
        response = client.post("/embed/query", json={"text": ""})

    assert response.status_code == 422


def test_query_endpoint_returns_multi_vector_contract(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "embed_query",
        lambda text: {
            "vectors": [[0.1, 0.2], [0.3, 0.4]],
            "vector_count": 2,
            "dimension": 2,
            "model": runtime.model_name,
        },
    )

    with TestClient(app) as client:
        response = client.post("/embed/query", json={"text": "door schedule"})

    assert response.status_code == 200
    body = response.json()
    assert body["vector_count"] == 2
    assert body["dimension"] == 2
    assert len(body["vectors"]) == 2


def test_image_endpoint_rejects_non_image():
    with TestClient(app) as client:
        response = client.post(
            "/embed/image",
            files={"file": ("bad.txt", b"not an image", "text/plain")},
        )

    assert response.status_code == 400


def test_image_endpoint_returns_dimensions_and_vectors(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "embed_image",
        lambda image: {
            "vectors": [[0.1, 0.2]],
            "vector_count": 1,
            "dimension": 2,
            "model": runtime.model_name,
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/embed/image",
            files={"file": ("drawing.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["image_width"] == 32
    assert body["image_height"] == 24
    assert body["vector_count"] == 1


def test_decode_image_resizes_large_input():
    image = runtime.decode_image(_png_bytes(2000, 1000))

    assert image.size == (1536, 768)
