"""Tests for chat vision capability resolution."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from construction_os.ai import vision_capabilities


def test_known_openai_vision_model(monkeypatch):
    async def fake_get(model_id):
        return SimpleNamespace(
            id=model_id,
            name="gpt-5",
            provider="openai",
            type="language",
        )

    monkeypatch.setattr(vision_capabilities.Model, "get", staticmethod(fake_get))
    result = asyncio.run(
        vision_capabilities.resolve_chat_vision_capability("model:vision")
    )

    assert result["supported"] is True
    assert result["reason"] == "known_vision_model"


def test_unknown_language_model_fails_closed(monkeypatch):
    async def fake_get(model_id):
        return SimpleNamespace(
            id=model_id,
            name="custom-text-model",
            provider="custom_provider",
            type="language",
        )

    monkeypatch.setattr(vision_capabilities.Model, "get", staticmethod(fake_get))
    result = asyncio.run(
        vision_capabilities.resolve_chat_vision_capability("model:unknown")
    )

    assert result["supported"] is False
    assert result["reason"] == "vision_capability_unconfirmed"


def test_explicit_vision_override(monkeypatch):
    monkeypatch.setenv("CONSTRUCTION_OS_VISION_MODEL_IDS", "model:custom")

    async def unexpected_get(model_id):
        raise AssertionError("explicit overrides should not query the model record")

    monkeypatch.setattr(
        vision_capabilities.Model,
        "get",
        staticmethod(unexpected_get),
    )
    result = asyncio.run(
        vision_capabilities.resolve_chat_vision_capability("model:custom")
    )

    assert result["supported"] is True
    assert result["reason"] == "explicit_vision_override"


def test_default_chat_model_is_resolved(monkeypatch):
    async def fake_defaults():
        return SimpleNamespace(default_chat_model="model:default")

    async def fake_get(model_id):
        assert model_id == "model:default"
        return SimpleNamespace(
            id=model_id,
            name="claude-4-sonnet",
            provider="anthropic",
            type="language",
        )

    monkeypatch.setattr(vision_capabilities.model_manager, "get_defaults", fake_defaults)
    monkeypatch.setattr(vision_capabilities.Model, "get", staticmethod(fake_get))
    result = asyncio.run(vision_capabilities.resolve_chat_vision_capability(None))

    assert result["model_id"] == "model:default"
    assert result["supported"] is True


def test_multimodal_error_classifier_is_narrow():
    assert vision_capabilities.is_multimodal_compatibility_error(
        RuntimeError("This model does not support images")
    )
    assert not vision_capabilities.is_multimodal_compatibility_error(
        RuntimeError("database unavailable")
    )
