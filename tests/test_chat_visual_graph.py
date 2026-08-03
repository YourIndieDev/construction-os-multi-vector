"""Graph-level tests for request-scoped visual project chat."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from construction_os.graphs import chat


class _Prompt:
    def __init__(self, *args, **kwargs):
        pass

    def render(self, data):
        return f"SYSTEM\n{data.get('context') or ''}"


def _base_state() -> dict:
    return {
        "messages": [HumanMessage(content="Where is the LPG regulator?")],
        "project": {"id": "project:test", "name": "Test"},
        "project_id": "project:test",
        "context": "Existing textual context",
        "context_config": None,
        "model_override": "model:vision",
        "skills_context": "Selected skill instructions",
        "skill_ids": ["skill:test"],
        "collections_context": "Selected collection context",
        "collection_ids": ["collection:test"],
        "mcp_tool_ids": ["mcp:test"],
        "strict_mcp_tools": False,
        "session_id": "chat_session:test",
        "is_guest": True,
        "html_template_id": None,
        "html_template": None,
        "artifact_id": None,
        "artifact": None,
        "artifact_instructions": None,
        "a2ui_pending": None,
        "a2ui_by_message_id": None,
        "drawing_retrieval_mode": "multi_vector",
        "drawing_source_ids": ["source:p203"],
        "drawing_result_limit": 3,
        "visual_evidence": {
            "text_context": (
                "## Retrieved Visual Drawing Evidence\n"
                "Do not invent dimensions.\nSheet: P203"
            ),
            "images": [{"path": "/safe/crop.png"}],
            "evidence": [{"sheet_number": "P203"}],
        },
        "drawing_retrieval_debug": {
            "requested_mode": "multi_vector",
            "mode_used": "multi_vector",
            "fallback_reason": None,
            "evidence": [{"sheet_number": "P203"}],
            "vision": None,
        },
        "drawing_retrieval_by_message_id": None,
    }


def _patch_common(monkeypatch):
    monkeypatch.setattr(chat, "Prompter", _Prompt)
    monkeypatch.setattr(chat, "emit_agent_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_emit_drawing_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "is_a2ui_chat_enabled", lambda: False)

    async def vision(model_id):
        return {
            "model_id": model_id,
            "model_name": "gpt-5",
            "provider": "openai",
            "supported": True,
            "reason": "known_vision_model",
        }

    monkeypatch.setattr(chat, "resolve_chat_vision_capability", vision)
    monkeypatch.setattr(
        chat,
        "encode_visual_image_blocks",
        lambda images: (
            [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,IMAGE"},
                }
            ],
            [{"path": "/safe/crop.png", "role": "crop"}],
        ),
    )


def test_generating_attaches_images_and_visual_guardrails(monkeypatch):
    _patch_common(monkeypatch)
    observed = {}

    def fake_generate_once(**kwargs):
        observed.update(kwargs)
        return AIMessage(content="The regulator is shown on sheet P203.")

    monkeypatch.setattr(chat, "_generate_once", fake_generate_once)
    result = chat.generating(_base_state(), {})

    payload = observed["payload"]
    assert "Do not invent dimensions" in payload[0].content
    assert "Sheet: P203" in payload[0].content
    assert isinstance(payload[1].content, list)
    assert payload[1].content[-1]["type"] == "image_url"
    assert "base64" not in observed["provisioning_content"]
    assert result["messages"].content == "The regulator is shown on sheet P203."
    debug = next(iter(result["drawing_retrieval_by_message_id"].values()))
    assert debug["vision"]["image_count"] == 1
    assert debug["vision"]["attached_images"][0]["role"] == "crop"
    assert result["drawing_retrieval_mode"] == "existing"
    assert result["drawing_source_ids"] == []
    assert result["visual_evidence"] is None


def test_multimodal_rejection_retries_text_only(monkeypatch):
    _patch_common(monkeypatch)
    calls = []

    def fake_generate_once(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("This model does not support images")
        return AIMessage(content="Text fallback answer")

    monkeypatch.setattr(chat, "_generate_once", fake_generate_once)
    result = chat.generating(_base_state(), {})

    assert len(calls) == 2
    assert isinstance(calls[0]["payload"][1].content, list)
    assert calls[1]["payload"][1].content == "Where is the LPG regulator?"
    debug = result["drawing_retrieval_debug"]
    assert debug["vision"]["supported"] is False
    assert debug["vision"]["image_count"] == 0
    assert "vision_request_rejected" in debug["fallback_reason"]
    assert result["messages"].content == "Text fallback answer"


def test_existing_chat_payload_remains_text_only(monkeypatch):
    _patch_common(monkeypatch)
    observed = {}
    state = _base_state()
    state.update(
        {
            "drawing_retrieval_mode": "existing",
            "drawing_source_ids": [],
            "visual_evidence": None,
            "drawing_retrieval_debug": None,
        }
    )

    def fake_generate_once(**kwargs):
        observed.update(kwargs)
        return AIMessage(content="Normal answer")

    monkeypatch.setattr(chat, "_generate_once", fake_generate_once)
    result = chat.generating(state, {})

    assert observed["payload"][1].content == "Where is the LPG regulator?"
    assert "Retrieved Visual Drawing Evidence" not in observed["payload"][0].content
    assert "drawing_retrieval_debug" not in result
    assert result["messages"].content == "Normal answer"
