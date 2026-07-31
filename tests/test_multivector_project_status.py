"""Tests for project-level visual-index source filtering."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from construction_os.drawing import multivector_project_status as status


def test_ready_source_filter_excludes_disabled_stale_and_unrequested(monkeypatch):
    project = SimpleNamespace(
        get_sources=lambda: _async_value(
            [
                SimpleNamespace(id="source:ready"),
                SimpleNamespace(id="source:disabled"),
                SimpleNamespace(id="source:stale"),
                SimpleNamespace(id="source:other"),
            ]
        )
    )

    async def fake_project_get(project_id):
        assert project_id == "project:alpha"
        return project

    states = {
        "source:ready": {
            "source_id": "source:ready",
            "enabled": True,
            "status": "ready",
            "stale": False,
            "point_count": 7,
        },
        "source:disabled": {
            "source_id": "source:disabled",
            "enabled": False,
            "status": "disabled",
            "stale": False,
            "point_count": 7,
        },
        "source:stale": {
            "source_id": "source:stale",
            "enabled": True,
            "status": "stale",
            "stale": True,
            "point_count": 7,
        },
        "source:other": {
            "source_id": "source:other",
            "enabled": True,
            "status": "ready",
            "stale": False,
            "point_count": 3,
        },
    }

    async def fake_source_status(project_id, source_id, **kwargs):
        assert kwargs["include_qdrant_count"] is False
        return states[source_id]

    monkeypatch.setattr(status.Project, "get", staticmethod(fake_project_get))
    monkeypatch.setattr(status, "get_source_index_status", fake_source_status)

    result = asyncio.run(
        status.ready_project_source_ids(
            "project:alpha",
            requested_source_ids=["source:ready", "source:disabled", "source:stale"],
        )
    )
    assert result == ["source:ready"]


async def _async_value(value):
    return value
