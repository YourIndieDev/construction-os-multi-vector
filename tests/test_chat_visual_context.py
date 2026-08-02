"""Regression tests for default project-chat context retrieval."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from construction_os.graphs import chat


def test_default_existing_mode_never_calls_visual_retrieval(monkeypatch):
    async def fake_context(**kwargs):
        return {
            "sources": [],
            "notes": [],
            "formatted": None,
            "total_tokens": 0,
            "sourceCount": 0,
            "noteCount": 0,
            "tokenCount": 0,
        }

    async def unexpected_visual(**kwargs):
        raise AssertionError("ordinary chat must not call visual retrieval")

    monkeypatch.setattr(chat, "build_relevance_context", fake_context)
    monkeypatch.setattr(chat, "build_visual_chat_evidence", unexpected_visual)
    monkeypatch.setattr(chat, "emit_agent_progress", lambda *args, **kwargs: None)

    result = chat.retrieving_context(
        {
            "messages": [HumanMessage(content="What does the project say?")],
            "project_id": "project:test",
            "context_config": {
                "sources": {"source:test": "full content"},
            },
        },
        {},
    )

    assert result["context"] is None
    assert result["visual_evidence"] is None
    assert result["drawing_retrieval_debug"] is None


def test_explicit_visual_mode_passes_selected_source_pool(monkeypatch):
    observed = {}

    async def fake_context(**kwargs):
        return {
            "sources": [],
            "notes": [],
            "formatted": None,
            "total_tokens": 0,
            "sourceCount": 0,
            "noteCount": 0,
            "tokenCount": 0,
        }

    async def fake_visual(**kwargs):
        observed.update(kwargs)
        return {
            "text_context": None,
            "evidence": [],
            "images": [],
            "debug": {
                "requested_mode": "multi_vector",
                "fallback_reason": "visual_evidence_empty",
            },
        }

    monkeypatch.setattr(chat, "build_relevance_context", fake_context)
    monkeypatch.setattr(chat, "build_visual_chat_evidence", fake_visual)
    monkeypatch.setattr(chat, "emit_agent_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_emit_drawing_debug", lambda *args, **kwargs: None)

    result = chat.retrieving_context(
        {
            "messages": [HumanMessage(content="Where is the regulator?")],
            "project_id": "project:test",
            "context_config": {
                "sources": {
                    "source:p203": "full content",
                    "source:excluded": "not in",
                },
            },
            "drawing_retrieval_mode": "multi_vector",
            "drawing_source_ids": ["source:p203"],
            "drawing_result_limit": 3,
        },
        {},
    )

    assert observed["mode"] == "multi_vector"
    assert observed["requested_source_ids"] == ["source:p203"]
    assert observed["allowed_source_ids"] == ["source:p203"]
    assert result["drawing_retrieval_debug"]["requested_mode"] == "multi_vector"
