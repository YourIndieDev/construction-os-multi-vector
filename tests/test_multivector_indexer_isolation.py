"""Isolation coverage for indexing multiple visual sources independently."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from construction_os.drawing import multivector_indexer as indexer


class _IsolatedStore:
    instances: list["_IsolatedStore"] = []

    def __init__(self):
        self.deleted: list[tuple[str, str]] = []
        self.points = []
        self.__class__.instances.append(self)

    async def ensure_collection(self):
        return {"created": False}

    async def delete_source(self, *, project_id: str, source_id: str):
        self.deleted.append((project_id, source_id))
        return {"deleted": True}

    async def upsert_assets(self, assets):
        self.points.extend(assets)
        return {"upserted": len(assets)}


async def _value(value):
    return value


def test_two_sources_keep_separate_qdrant_payloads(monkeypatch, tmp_path: Path):
    source_ids = ("source:alpha", "source:beta")
    image_paths = {}
    for name in ("alpha", "beta"):
        path = tmp_path / f"{name}.png"
        path.write_bytes(name.encode())
        image_paths[f"source:{name}"] = path

    async def fake_get(source_id: str):
        return SimpleNamespace(
            id=source_id,
            title=source_id,
            asset=SimpleNamespace(file_path=f"{source_id}.pdf"),
        )

    async def fake_collect(source, source_id: str, file_hash: str):
        return [indexer.VisualAsset(image_paths[source_id], "page", 0)], f"run:{source_id}"

    async def fake_embed(path, **kwargs):
        marker = 0.1 if path.name.startswith("alpha") else 0.2
        return {
            "vectors": [[marker] * 128],
            "vector_count": 1,
            "dimension": 128,
            "model": "vidore/colSmol-256M",
            "image_width": 100,
            "image_height": 100,
        }

    ready = []

    async def fake_ready(project_id: str, source_id: str, **fields):
        ready.append((project_id, source_id, fields))
        return fields

    monkeypatch.setattr(indexer, "get_source_index_status", lambda *args, **kwargs: _value({"status": "queued"}))
    monkeypatch.setattr(indexer.Source, "get", staticmethod(fake_get))
    monkeypatch.setattr(indexer, "source_file_hash", lambda source: f"hash:{source.id}")
    monkeypatch.setattr(indexer, "_collect_assets", fake_collect)
    monkeypatch.setattr(indexer, "embed_colsmol_image", fake_embed)
    monkeypatch.setattr(indexer, "QdrantMultiVectorStore", _IsolatedStore)
    monkeypatch.setattr(indexer, "mark_source_indexing", lambda *args, **kwargs: _value({}))
    monkeypatch.setattr(indexer, "_write_progress", lambda *args, **kwargs: _value(None))
    monkeypatch.setattr(indexer, "mark_source_index_ready", fake_ready)
    monkeypatch.setattr(indexer, "mark_source_index_error", lambda *args, **kwargs: _value({}))

    async def scenario():
        await asyncio.gather(
            *(indexer.run_source_multivector_index("project:test", source_id) for source_id in source_ids)
        )

    asyncio.run(scenario())

    recent = _IsolatedStore.instances[-2:]
    assert {store.deleted[0] for store in recent} == {
        ("project:test", "source:alpha"),
        ("project:test", "source:beta"),
    }

    points_by_source = {
        point.source_id: point
        for store in recent
        for point in store.points
    }
    assert set(points_by_source) == set(source_ids)
    assert points_by_source["source:alpha"].vectors[0][0] == 0.1
    assert points_by_source["source:beta"].vectors[0][0] == 0.2
    assert {item[1] for item in ready} == set(source_ids)
