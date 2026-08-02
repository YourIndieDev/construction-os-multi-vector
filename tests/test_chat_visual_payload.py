"""Tests for image encoding and request-scoped multimodal message copies."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from construction_os.drawing import chat_evidence


def test_encode_image_blocks_and_attach_without_mutating_history(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    root.mkdir()
    image = root / "crop.png"
    image.write_bytes(b"png-bytes")
    monkeypatch.setattr(chat_evidence, "DRAWING_EXTRACTION_FOLDER", str(root))

    blocks, attached = chat_evidence.encode_visual_image_blocks(
        [
            {
                "role": "crop",
                "path": str(image),
                "source_id": "source:plans",
                "sheet_number": "P203",
                "page_number": 1,
                "evidence_rank": 1,
            },
            {
                "role": "duplicate",
                "path": str(image),
                "source_id": "source:plans",
            },
        ]
    )

    assert len(blocks) == 1
    assert blocks[0]["type"] == "image_url"
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert len(attached) == 1
    assert attached[0]["sheet_number"] == "P203"

    original = [HumanMessage(content="Where is the regulator?"), AIMessage(content="Earlier")]
    copied = chat_evidence.attach_image_blocks_to_latest_user_message(original, blocks)

    assert original[0].content == "Where is the regulator?"
    assert isinstance(copied[0].content, list)
    assert copied[0].content[0] == {
        "type": "text",
        "text": "Where is the regulator?",
    }
    assert copied[0].content[1]["type"] == "image_url"
    assert copied[1].content == "Earlier"


def test_encoder_skips_oversized_and_unsafe_images(monkeypatch, tmp_path):
    root = tmp_path / "drawing-extractions"
    root.mkdir()
    large = root / "large.png"
    large.write_bytes(b"12345")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"small")
    monkeypatch.setattr(chat_evidence, "DRAWING_EXTRACTION_FOLDER", str(root))

    blocks, attached = chat_evidence.encode_visual_image_blocks(
        [
            {"path": str(large)},
            {"path": str(outside)},
        ],
        max_image_bytes=4,
    )

    assert blocks == []
    assert attached == []


def test_no_image_blocks_preserves_message_objects():
    messages = [HumanMessage(content="Normal chat")]
    copied = chat_evidence.attach_image_blocks_to_latest_user_message(messages, [])

    assert copied == messages
    assert copied[0] is messages[0]
