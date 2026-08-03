"""Tests for filtered Qdrant MaxSim visual search."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from construction_os.drawing.multivector_search import QdrantMultiVectorSearch
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


def _query_vectors() -> list[list[float]]:
    return [[0.1] * 128, [0.2] * 128]


def test_search_sends_multivectors_and_project_source_filters():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "result": {
                    "points": [
                        {
                            "id": "point-one",
                            "score": 8.25,
                            "payload": {
                                "project_id": "project:alpha",
                                "source_id": "source:plans",
                                "page_index": 0,
                                "image_path": "/data/page.png",
                            },
                        }
                    ]
                }
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await QdrantMultiVectorSearch(
                _settings(), client=client
            ).search(
                query_vectors=_query_vectors(),
                project_id="project:alpha",
                source_ids=["source:plans", "source:details"],
                asset_kinds=["page", "region_crop"],
                limit=12,
                score_threshold=1.5,
            )

    hits = asyncio.run(scenario())
    body = json.loads(requests[0].content)

    assert requests[0].url.path.endswith("/points/query")
    assert requests[0].headers["api-key"] == "secret"
    assert body["query"] == _query_vectors()
    assert body["limit"] == 12
    assert body["score_threshold"] == 1.5
    assert body["with_payload"] is True
    assert body["filter"]["must"] == [
        {"key": "project_id", "match": {"value": "project:alpha"}},
        {
            "key": "source_id",
            "match": {"any": ["source:details", "source:plans"]},
        },
        {
            "key": "asset_kind",
            "match": {"any": ["page", "region_crop"]},
        },
    ]
    assert hits[0].point_id == "point-one"
    assert hits[0].score == 8.25


def test_search_rejects_wrong_query_dimension():
    async def scenario():
        await QdrantMultiVectorSearch(_settings()).search(
            query_vectors=[[0.1, 0.2]],
            project_id="project:alpha",
        )

    with pytest.raises(ValueError, match="dimension 128"):
        asyncio.run(scenario())
