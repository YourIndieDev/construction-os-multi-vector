"""Tests for the experimental visual chat source-pool adapter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.routers import multivector_search as api


def test_visual_source_ids_create_context_pool_when_context_is_omitted(monkeypatch):
    observed = {}

    class FakeSession:
        model_override = None
        skill_ids = []
        collection_ids = []
        html_template_id = None

        async def save(self):
            return None

    async def fake_session_get(session_id):
        return FakeSession()

    async def fake_project_id(session_id):
        return "project:test"

    async def fake_project_get(project_id):
        return SimpleNamespace(id=project_id, name="Test", description=None)

    async def fake_none(*args, **kwargs):
        return None, None

    def fake_run_input(**kwargs):
        observed.update(kwargs)
        return "run-input"

    monkeypatch.setattr(api, "normalize_chat_session_id", lambda value: value)
    monkeypatch.setattr(api.ChatSession, "get", staticmethod(fake_session_get))
    monkeypatch.setattr(api, "_assert_session_guest_access", lambda *args: None)
    monkeypatch.setattr(api, "get_refers_to_out_id", fake_project_id)
    monkeypatch.setattr(api.Project, "get", staticmethod(fake_project_get))
    monkeypatch.setattr(api, "resolve_session_skill_ids", lambda *args: [])
    monkeypatch.setattr(api, "resolve_session_collection_ids", lambda *args: [])
    monkeypatch.setattr(api, "resolve_session_html_template_id", lambda *args: None)
    monkeypatch.setattr(api, "resolve_html_template_meta", fake_none)
    monkeypatch.setattr(api, "resolve_artifact_meta", fake_none)
    monkeypatch.setattr(api.ag_ui_agents, "build_run_input", fake_run_input)
    monkeypatch.setattr(
        api.ag_ui_agents,
        "ag_ui_streaming_response",
        lambda *args, **kwargs: "stream",
    )

    body = api.VisualChatExecuteRequest(
        session_id="chat_session:test",
        message="Where is the regulator?",
        drawing_retrieval_mode="multi_vector",
        drawing_source_ids=["source:p203"],
    )

    result = asyncio.run(api.execute_visual_project_chat(body, x_guest_key=None))

    assert result == "stream"
    assert observed["forwarded_props"]["context_config"] == {
        "sources": {"source:p203": "full content"}
    }
