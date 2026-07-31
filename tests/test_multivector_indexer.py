"""Targeted tests for the background multi-vector source indexer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from construction_os.drawing import multivector_indexer as indexer


class _FakeStore:
    instances = []

    def __init__(self):
        self.calls = []
        self.points = []
        self.__class__.instances.append(self)

    async def ensure_collection(self):
        self.calls.append("ensure")
        return {"created": False}

    async def delete_source(self, *, project_id, source_id):
        self.calls.append(("delete", project_id, source_id))
        return {"deleted": True}

    async def upsert_assets(self, assets):
        self.points.extend(assets)
        self.calls.append(("upsert", len(assets)))
        return {"upserted": len(assets)}


def test_run_source_index_embeds_assets_one_at_a_time(monkeypatch, tmp_path):
    image_a = tmp_path / "page.png"
    image_b = tmp_path / "crop.png"
    image_a.write_bytes(b"page")
    image_b.write_bytes(b"crop")
    source = SimpleNamespace(id="source:test", title="Plans", asset=SimpleNamespace(file_path="plans.pdf"))

    async def fake_status(*args, **kwargs):
        return {"enabled": True, "status": "queued"}

    async def fake_get(source_id):
        return source

    async def fake_collect(*args, **kwargs):
        return (
            [
                indexer.VisualAsset(image_a, "page", 0),
                indexer.VisualAsset(image_b, "grid_crop", 0, crop_id="grid:0"),
            ],
            "drawing_extraction_run:test",
        )

    async def fake_embed(path, **kwargs):
        return {
            "vectors": [[0.1] * 128, [0.2] * 128],
            "vector_count": 2,
            "dimension": 128,
            "model": "vidore/colSmol-256M",
            "image_width": 640,
            "image_height": 480,
        }

    ready = []
    errors = []

    async def fake_ready(project_id, source_id, **fields):
        ready.append((project_id, source_id, fields))
        return fields

    async def fake_error(project_id, source_id, **fields):
        errors.append((project_id, source_id, fields))
        return fields

    monkeypatch.setattr(indexer, "get_source_index_status", fake_status)
    monkeypatch.setattr(indexer.Source, "get", staticmethod(fake_get))
    monkeypatch.setattr(indexer, "source_file_hash", lambda value: "hash-123")
    monkeypatch.setattr(indexer, "_collect_assets", fake_collect)
    monkeypatch.setattr(indexer, "embed_colsmol_image", fake_embed)
    monkeypatch.setattr(indexer, "QdrantMultiVectorStore", _FakeStore)
    monkeypatch.setattr(indexer, "mark_source_indexing", lambda *args, **kwargs: _async_value({}))
    monkeypatch.setattr(indexer, "_write_progress", lambda *args, **kwargs: _async_value(None))
    monkeypatch.setattr(indexer, "mark_source_index_ready", fake_ready)
    monkeypatch.setattr(indexer, "mark_source_index_error", fake_error)

    asyncio.run(indexer.run_source_multivector_index("project:test", "source:test"))

    store = _FakeStore.instances[-1]
    assert store.calls[0] == "ensure"
    assert store.calls[1] == ("delete", "project:test", "source:test")
    assert [call for call in store.calls if call[0] == "upsert"] == [
        ("upsert", 1),
        ("upsert", 1),
    ]
    assert len(store.points) == 2
    assert store.points[0].vectors[0] == [0.1] * 128
    assert ready[0][2]["point_count"] == 2
    assert errors == []


def test_queue_avoids_duplicate_active_task(monkeypatch):
    key = ("project:test", "source:test")

    async def scenario():
        blocker = asyncio.Event()

        async def active_job():
            await blocker.wait()

        task = asyncio.create_task(active_job())
        indexer._TASKS[key] = task
        monkeypatch.setattr(
            indexer,
            "get_source_index_status",
            lambda *args, **kwargs: _async_value({"status": "indexing"}),
        )
        try:
            result = await indexer.queue_source_multivector_index(*key)
            assert result["status"] == "indexing"
            assert indexer._TASKS[key] is task
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            indexer._TASKS.pop(key, None)

    asyncio.run(scenario())


async def _async_value(value):
    return value
