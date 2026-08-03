"""Contract tests for the experimental visual project-chat endpoint."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.routers import multivector_search as api


def test_visual_chat_request_defaults_are_backward_safe():
    body = api.VisualChatExecuteRequest(
        session_id="chat_session:test",
        message="hello",
    )

    assert body.drawing_retrieval_mode == "existing"
    assert body.drawing_source_ids == []
    assert body.drawing_result_limit == 3


def test_visual_chat_forwards_existing_and_drawing_state(monkeypatch):
    observed: dict = {}

    class FakeSession:
        model_override = "model:session"
        skill_ids = ["skill:stored"]
        collection_ids = ["collection:stored"]
        html_template_id = None

        async def save(self):
            observed["saved"] = True

    async def fake_session_get(session_id):
        assert session_id == "chat_session:test"
        return FakeSession()

    async def fake_project_id(session_id):
        return "project:test"

    async def fake_project_get(project_id):
        return SimpleNamespace(
            id=project_id,
            name="Test",
            description="Project",
        )

    async def fake_html(*args, **kwargs):
        return None, None

    async def fake_artifact(*args, **kwargs):
        return None, None

    def fake_build_run_input(**kwargs):
        observed["run_input"] = kwargs
        return {"run": "input"}

    def fake_stream(agent, run_input, **kwargs):
        observed["stream"] = {
            "agent": agent,
            "run_input": run_input,
            "kwargs": kwargs,
        }
        return {"streaming": True}

    monkeypatch.setattr(api, "normalize_chat_session_id", lambda value: value)
    monkeypatch.setattr(api.ChatSession, "get", staticmethod(fake_session_get))
    monkeypatch.setattr(api, "_assert_session_guest_access", lambda *args: None)
    monkeypatch.setattr(api, "get_refers_to_out_id", fake_project_id)
    monkeypatch.setattr(api.Project, "get", staticmethod(fake_project_get))
    monkeypatch.setattr(
        api,
        "resolve_session_skill_ids",
        lambda session, requested: list(requested or session.skill_ids),
    )
    monkeypatch.setattr(
        api,
        "resolve_session_collection_ids",
        lambda session, requested: list(requested or session.collection_ids),
    )
    monkeypatch.setattr(
        api,
        "resolve_session_html_template_id",
        lambda session, requested: requested,
    )
    monkeypatch.setattr(api, "resolve_html_template_meta", fake_html)
    monkeypatch.setattr(api, "resolve_artifact_meta", fake_artifact)
    monkeypatch.setattr(api.ag_ui_agents, "build_run_input", fake_build_run_input)
    monkeypatch.setattr(
        api.ag_ui_agents,
        "ag_ui_streaming_response",
        fake_stream,
    )
    monkeypatch.setattr(api.ag_ui_agents, "project_chat_agent", "agent")

    body = api.VisualChatExecuteRequest(
        session_id="chat_session:test",
        message="Where is the LPG regulator?",
        context_config={"sources": {"source:p203": "full content"}},
        skill_ids=["skill:explicit"],
        collection_ids=["collection:explicit"],
        mcp_tool_ids=["mcp:one"],
        drawing_retrieval_mode="compare",
        drawing_source_ids=["source:p203"],
        drawing_result_limit=2,
    )

    result = asyncio.run(api.execute_visual_project_chat(body, x_guest_key=None))

    assert result == {"streaming": True}
    props = observed["run_input"]["forwarded_props"]
    assert props["project_id"] == "project:test"
    assert props["skill_ids"] == ["skill:explicit"]
    assert props["collection_ids"] == ["collection:explicit"]
    assert props["mcp_tool_ids"] == ["mcp:one"]
    assert props["drawing_retrieval_mode"] == "compare"
    assert props["drawing_source_ids"] == ["source:p203"]
    assert props["drawing_result_limit"] == 2
    assert observed["stream"]["kwargs"]["configurable"] == {
        "model_id": "model:session"
    }
