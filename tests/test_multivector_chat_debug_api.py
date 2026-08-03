import asyncio
from types import SimpleNamespace

from api.routers import multivector_search


def test_visual_chat_debug_returns_sanitized_message_map(monkeypatch):
    class FakeSession:
        guest_key = None

    async def fake_session_get(session_id):
        assert session_id == "chat_session:test"
        return FakeSession()

    class FakeGraph:
        async def aget_state(self, config):
            assert config["configurable"]["thread_id"] == "chat_session:test"
            return SimpleNamespace(
                values={
                    "drawing_retrieval_by_message_id": {
                        "ai:one": {
                            "requested_mode": "multi_vector",
                            "mode_used": "multi_vector",
                            "project_id": "project:test",
                            "requested_source_ids": ["source:p203"],
                            "evidence": [],
                        },
                        42: {"ignored": True},
                        "invalid": "ignored",
                    }
                }
            )

    monkeypatch.setattr(
        multivector_search.ChatSession,
        "get",
        staticmethod(fake_session_get),
    )
    monkeypatch.setattr(
        multivector_search,
        "_assert_session_guest_access",
        lambda *args: None,
    )
    monkeypatch.setattr(multivector_search.chat_graph_module, "graph", FakeGraph())

    result = asyncio.run(multivector_search.get_visual_chat_debug("test", None))

    assert result["session_id"] == "chat_session:test"
    assert list(result["debug_by_message_id"]) == ["ai:one"]
    assert (
        result["debug_by_message_id"]["ai:one"]["requested_mode"]
        == "multi_vector"
    )
