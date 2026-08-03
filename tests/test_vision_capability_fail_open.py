"""Fail-open regression tests for visual chat capability lookup."""

from __future__ import annotations

import asyncio

from construction_os.ai import vision_capabilities


def test_model_record_lookup_failure_disables_images_without_raising(monkeypatch):
    async def failing_get(model_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        vision_capabilities.Model,
        "get",
        staticmethod(failing_get),
    )

    result = asyncio.run(
        vision_capabilities.resolve_chat_vision_capability("model:test")
    )

    assert result["supported"] is False
    assert result["reason"] == "model_record_lookup_failed"


def test_default_model_lookup_failure_disables_images_without_raising(monkeypatch):
    async def failing_defaults():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        vision_capabilities.model_manager,
        "get_defaults",
        failing_defaults,
    )

    result = asyncio.run(vision_capabilities.resolve_chat_vision_capability(None))

    assert result["supported"] is False
    assert result["reason"] == "default_model_lookup_failed"
