"""Targeted tests for source-level multi-vector opt-in and readiness state."""

import asyncio
from types import SimpleNamespace

from construction_os.drawing import multivector_state as state


def test_state_record_id_is_stable_and_project_scoped():
    first = state.state_record_id("project:one", "source:one")
    second = state.state_record_id("project:one", "source:one")
    other = state.state_record_id("project:two", "source:one")

    assert first == second
    assert first.startswith("drawing_multivector_index:")
    assert first != other


def test_derived_status_detects_disabled_stale_and_ready():
    assert (
        state._derived_status(
            {"enabled": False},
            current_file_hash="new",
            point_count=3,
        )
        == "disabled"
    )
    assert (
        state._derived_status(
            {"enabled": True, "indexed_file_hash": "old", "status": "ready"},
            current_file_hash="new",
            point_count=3,
        )
        == "stale"
    )
    assert (
        state._derived_status(
            {"enabled": True, "indexed_file_hash": "same", "status": "ready"},
            current_file_hash="same",
            point_count=3,
        )
        == "ready"
    )


class _CountStore:
    def __init__(self, count=4):
        self.count = count
        self.calls = []

    async def count_source(self, *, project_id, source_id):
        self.calls.append((project_id, source_id))
        return self.count


class _DeleteStore:
    def __init__(self):
        self.calls = []

    async def delete_source(self, *, project_id, source_id):
        self.calls.append((project_id, source_id))
        return {"deleted": True}


def test_status_detects_stale_file_and_live_point_count(monkeypatch):
    source = SimpleNamespace(title="Plan Set")
    monkeypatch.setattr(
        state,
        "_load_source_for_project",
        lambda project_id, source_id: _async_value(source),
    )
    monkeypatch.setattr(
        state,
        "get_persisted_state",
        lambda project_id, source_id: _async_value(
            {
                "id": "drawing_multivector_index:test",
                "enabled": True,
                "status": "ready",
                "indexed_file_hash": "old-hash",
                "point_count": 2,
            }
        ),
    )
    monkeypatch.setattr(state, "source_file_hash", lambda source: "new-hash")
    store = _CountStore(count=7)

    result = asyncio.run(
        state.get_source_index_status(
            "project:test",
            "source:test",
            store=store,
        )
    )

    assert result["status"] == "stale"
    assert result["stale"] is True
    assert result["point_count"] == 7
    assert store.calls == [("project:test", "source:test")]


def test_disabled_status_does_not_query_qdrant(monkeypatch):
    source = SimpleNamespace(title="Plan Set")
    monkeypatch.setattr(
        state,
        "_load_source_for_project",
        lambda project_id, source_id: _async_value(source),
    )
    monkeypatch.setattr(
        state,
        "get_persisted_state",
        lambda project_id, source_id: _async_value(
            {"enabled": False, "status": "disabled", "point_count": 5}
        ),
    )
    monkeypatch.setattr(state, "source_file_hash", lambda source: "hash")
    store = _CountStore(count=9)

    result = asyncio.run(
        state.get_source_index_status(
            "project:test",
            "source:test",
            store=store,
        )
    )

    assert result["status"] == "disabled"
    assert result["point_count"] == 5
    assert store.calls == []


def test_enable_new_source_persists_not_indexed(monkeypatch):
    source = SimpleNamespace(title="Plan Set")
    persisted = []

    monkeypatch.setattr(
        state,
        "_load_source_for_project",
        lambda project_id, source_id: _async_value(source),
    )
    monkeypatch.setattr(
        state,
        "get_persisted_state",
        lambda project_id, source_id: _async_value(
            {"enabled": False, "status": "disabled", "point_count": 0}
        ),
    )
    monkeypatch.setattr(state, "source_file_hash", lambda source: "current-hash")

    async def fake_persist(project_id, source_id, **fields):
        persisted.append(fields)
        return fields

    async def fake_status(project_id, source_id, **kwargs):
        return {"enabled": True, "status": "not_indexed"}

    monkeypatch.setattr(state, "_persist_state", fake_persist)
    monkeypatch.setattr(state, "get_source_index_status", fake_status)

    result = asyncio.run(
        state.set_source_index_enabled(
            "project:test",
            "source:test",
            enabled=True,
        )
    )

    assert result["status"] == "not_indexed"
    assert persisted[0]["enabled"] is True
    assert persisted[0]["status"] == "not_indexed"


def test_rebuild_clears_qdrant_and_queues_state(monkeypatch):
    source = SimpleNamespace(title="Plan Set")
    persisted = []
    store = _DeleteStore()

    monkeypatch.setattr(
        state,
        "_load_source_for_project",
        lambda project_id, source_id: _async_value(source),
    )
    monkeypatch.setattr(state, "source_file_hash", lambda source: "current-hash")

    async def fake_persist(project_id, source_id, **fields):
        persisted.append(fields)
        return fields

    async def fake_status(project_id, source_id, **kwargs):
        return {"enabled": True, "status": "queued", "point_count": 0}

    monkeypatch.setattr(state, "_persist_state", fake_persist)
    monkeypatch.setattr(state, "get_source_index_status", fake_status)

    result = asyncio.run(
        state.request_source_rebuild(
            "project:test",
            "source:test",
            store=store,
        )
    )

    assert result["status"] == "queued"
    assert store.calls == [("project:test", "source:test")]
    assert persisted[0]["indexed_file_hash"] is None
    assert persisted[0]["point_count"] == 0


async def _async_value(value):
    return value
