"""Regression tests for multimodal payload handling in the chat tool loop."""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from construction_os.tool_runtime import chat_loop


class _FakeModel:
    def __init__(self):
        self.payloads = []

    def invoke(self, payload, config=None):
        self.payloads.append(payload)
        return AIMessage(content="answer")


def test_provisioning_content_excludes_base64_payload(monkeypatch):
    observed = {}
    model = _FakeModel()

    async def fake_provision(content, model_id, default_type, **kwargs):
        observed["content"] = content
        observed["model_id"] = model_id
        observed["default_type"] = default_type
        return model

    async def fake_allowlist(*args, **kwargs):
        return object()

    monkeypatch.setattr(chat_loop, "build_allowlist", fake_allowlist)
    monkeypatch.setattr(chat_loop, "build_langchain_tools", lambda *args, **kwargs: [])

    payload = [
        HumanMessage(
            content=[
                {"type": "text", "text": "question"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,VERY-LARGE"},
                },
            ]
        )
    ]
    result = asyncio.run(
        chat_loop.generate_with_tools(
            provision_model=fake_provision,
            payload=payload,
            provisioning_content="system prompt and question only",
            model_id="model:vision",
            mcp_tool_ids=[],
            session_id="chat_session:test",
        )
    )

    assert result.content == "answer"
    assert observed["content"] == "system prompt and question only"
    assert "base64" not in observed["content"]
    assert observed["default_type"] == "chat"
    assert model.payloads[0] == payload


def test_existing_callers_keep_original_provisioning_behavior(monkeypatch):
    observed = {}
    model = _FakeModel()

    async def fake_provision(content, model_id, default_type, **kwargs):
        observed["content"] = content
        return model

    async def fake_allowlist(*args, **kwargs):
        return object()

    monkeypatch.setattr(chat_loop, "build_allowlist", fake_allowlist)
    monkeypatch.setattr(chat_loop, "build_langchain_tools", lambda *args, **kwargs: [])

    payload = [HumanMessage(content="normal chat")]
    asyncio.run(
        chat_loop.generate_with_tools(
            provision_model=fake_provision,
            payload=payload,
            model_id=None,
            mcp_tool_ids=[],
            session_id="chat_session:test",
        )
    )

    assert observed["content"] == str(payload)
