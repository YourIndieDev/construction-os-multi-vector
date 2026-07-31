"""Contract tests for the ColSmol query embedding client."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from construction_os.integrations.colsmol import (
    ColSmolEmbeddingError,
    ColSmolSettings,
)
from construction_os.integrations.colsmol_query import embed_colsmol_query


def _settings() -> ColSmolSettings:
    return ColSmolSettings(
        enabled=True,
        url="http://colsmol:8000",
        timeout_seconds=1,
        embedding_timeout_seconds=5,
    )


def test_query_embedding_posts_text_and_validates_matrix():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json={
                "vectors": [[0.1] * 128, [0.2] * 128],
                "vector_count": 2,
                "dimension": 128,
                "model": "vidore/colSmol-256M",
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await embed_colsmol_query(
                " door schedule ",
                settings=_settings(),
                client=client,
            )

    result = asyncio.run(scenario())
    assert result["vector_count"] == 2
    assert result["dimension"] == 128
    assert requests[0].url.path == "/embed/query"
    assert requests[0].content == b'{"text":"door schedule"}'


def test_query_embedding_rejects_invalid_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={"vectors": [[0.1]], "vector_count": 2, "dimension": 1},
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await embed_colsmol_query(
                "door schedule",
                settings=_settings(),
                client=client,
            )

    with pytest.raises(ColSmolEmbeddingError, match="invalid query"):
        asyncio.run(scenario())
