"""Storage tests for the versioned Qdrant drawing multi-vector collection."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from construction_os.drawing.multivector_store import (
    MultiVectorAsset,
    MultiVectorCollectionMismatch,
    QdrantMultiVectorStore,
)
from construction_os.integrations.qdrant import QdrantSettings


def _settings() -> QdrantSettings:
    return QdrantSettings(
        enabled=True,
        url="http://qdrant:6333",
        timeout_seconds=1,
        api_key="secret",
        collection_name="construction_os_drawing_multivector_v1",
        vector_size=128,
    )


def _vectors(count: int = 2) -> list[list[float]]:
    return [[float(index) / 128 for index in range(128)] for _ in range(count)]


def _asset(**overrides: Any) -> MultiVectorAsset:
    values: dict[str, Any] = {
        "project_id": "project:alpha",
        "source_id": "source:plans",
        "run_id": "drawing_extraction_run:one",
        "asset_kind": "page",
        "page_index": 0,
        "image_path": "/data/page_0000/page.png",
        "vectors": _vectors(),
        "page_id": "drawing_page:one",
        "sheet_number": "A101",
        "sheet_title": "Floor Plan",
        "discipline": "architectural",
        "source_filename": "plans.pdf",
        "file_hash": "abc123",
    }
    values.update(overrides)
    return MultiVectorAsset(**values)


def test_asset_builds_stable_point_and_page_payload():
    first = _asset()
    second = _asset()

    point = first.to_qdrant_point(128)

    assert first.resolved_point_id == second.resolved_point_id
    assert point["payload"]["schema_version"] == 1
    assert point["payload"]["page_index"] == 0
    assert point["payload"]["page_number"] == 1
    assert point["payload"]["sheet_number"] == "A101"
    assert len(point["vector"]) == 2
    assert len(point["vector"][0]) == 128


def test_asset_rejects_wrong_vector_dimension():
    with pytest.raises(ValueError, match="Expected vector size 128"):
        _asset(vectors=[[0.1, 0.2]]).to_qdrant_point(128)


def test_ensure_collection_creates_maxsim_collection_and_indexes():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, request=request)
        return httpx.Response(200, request=request, json={"status": "ok"})

    async def scenario() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = QdrantMultiVectorStore(_settings(), client=client)
            return await store.ensure_collection()

    result = asyncio.run(scenario())
    create_request = requests[1]
    create_body = json.loads(create_request.content)
    index_requests = requests[2:]

    assert result["created"] is True
    assert create_body["vectors"]["size"] == 128
    assert create_body["vectors"]["distance"] == "Cosine"
    assert create_body["vectors"]["multivector_config"]["comparator"] == "max_sim"
    assert len(index_requests) == 6
    assert all(request.headers["api-key"] == "secret" for request in requests)


def test_ensure_collection_accepts_matching_existing_schema():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                request=request,
                json={
                    "result": {
                        "config": {
                            "params": {
                                "vectors": {
                                    "size": 128,
                                    "distance": "Cosine",
                                    "multivector_config": {"comparator": "max_sim"},
                                }
                            }
                        },
                        "payload_schema": {
                            "project_id": {},
                            "source_id": {},
                            "run_id": {},
                            "asset_kind": {},
                            "page_index": {},
                            "schema_version": {},
                        },
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await QdrantMultiVectorStore(
                _settings(), client=client
            ).ensure_collection()

    result = asyncio.run(scenario())

    assert result["created"] is False
    assert result["created_indexes"] == []


def test_ensure_collection_rejects_schema_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "result": {
                    "config": {
                        "params": {
                            "vectors": {
                                "size": 64,
                                "distance": "Cosine",
                                "multivector_config": {"comparator": "max_sim"},
                            }
                        }
                    }
                }
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await QdrantMultiVectorStore(_settings(), client=client).ensure_collection()

    with pytest.raises(MultiVectorCollectionMismatch):
        asyncio.run(scenario())


def test_replace_source_deletes_scoped_points_then_upserts():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request, json={"status": "ok"})

    async def scenario() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = QdrantMultiVectorStore(_settings(), client=client)
            return await store.replace_source(
                project_id="project:alpha",
                source_id="source:plans",
                assets=[
                    _asset(),
                    _asset(asset_kind="region_crop", crop_id="region:1"),
                ],
            )

    result = asyncio.run(scenario())
    delete_body = json.loads(requests[0].content)
    upsert_body = json.loads(requests[1].content)

    assert requests[0].url.path.endswith("/points/delete")
    assert delete_body["filter"]["must"] == [
        {"key": "project_id", "match": {"value": "project:alpha"}},
        {"key": "source_id", "match": {"value": "source:plans"}},
    ]
    assert requests[1].url.path.endswith("/points")
    assert len(upsert_body["points"]) == 2
    assert result["upserted"] == 2


def test_count_source_returns_exact_count():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["exact"] is True
        return httpx.Response(
            200,
            request=request,
            json={"result": {"count": 7}},
        )

    async def scenario() -> int:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await QdrantMultiVectorStore(
                _settings(), client=client
            ).count_source(
                project_id="project:alpha",
                source_id="source:plans",
            )

    assert asyncio.run(scenario()) == 7
