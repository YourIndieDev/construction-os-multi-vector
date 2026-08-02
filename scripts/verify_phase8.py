"""Live Phase 8 verifier for the experimental visual project-chat endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import httpx

DEFAULT_QUESTION = (
    "Where is the second-stage regulator and meter shown, and how does the LPG "
    "piping route from the existing propane tank into the building? Cite the sheet "
    "number and state when any label is unclear."
)


def _iter_sse_events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    data_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                data_lines.clear()
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    yield parsed
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            parsed = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            yield parsed


def _event_text(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "").upper()
    if "TEXT_MESSAGE_CONTENT" not in event_type:
        return ""
    return str(event.get("delta") or event.get("content") or "")


def _contains_debug_event(event: dict[str, Any]) -> bool:
    return "drawing_retrieval_debug" in json.dumps(event, sort_keys=True)


def _event_error(event: dict[str, Any]) -> str | None:
    if str(event.get("type") or "").upper() != "RUN_ERROR":
        return None
    return str(event.get("message") or event)


def _post_json(client: httpx.Client, path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=body)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {path}")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    with httpx.Client(base_url=args.api, timeout=args.timeout) as client:
        session_id = args.session_id
        if not session_id:
            session = _post_json(
                client,
                "/api/chat/sessions",
                {
                    "project_id": args.project_id,
                    "title": "Phase 8 visual verification",
                },
            )
            session_id = str(session.get("id") or "")
        if not session_id:
            raise RuntimeError("Unable to resolve a chat session ID")

        request_body = {
            "session_id": session_id,
            "message": args.question,
            "context_config": {
                "sources": {args.source_id: "full content"},
            },
            "drawing_retrieval_mode": args.mode,
            "drawing_source_ids": [args.source_id],
            "drawing_result_limit": 3,
        }

        events: list[dict[str, Any]] = []
        with client.stream(
            "POST",
            "/api/drawing-extractions/multivector/chat/execute",
            json=request_body,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            events.extend(_iter_sse_events(response.iter_lines()))

    errors = [error for event in events if (error := _event_error(event))]
    answer = "".join(_event_text(event) for event in events).strip()
    debug_found = any(_contains_debug_event(event) for event in events)
    serialized_events = json.dumps(events, sort_keys=True)

    checks = {
        "no_run_error": not errors,
        "debug_event": debug_found,
        "sheet_cited": "P203" in answer.upper(),
        "visual_backend": "qdrant_maxsim" in serialized_events,
        "multi_vector_marker": "multi_vector" in serialized_events,
    }
    result = {
        "project_id": args.project_id,
        "source_id": args.source_id,
        "session_id": session_id,
        "mode": args.mode,
        "question": args.question,
        "answer": answer,
        "event_count": len(events),
        "errors": errors,
        "checks": checks,
        "result": "passed" if all(checks.values()) else "failed",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:5056")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--session-id")
    parser.add_argument(
        "--mode",
        choices=("multi_vector", "compare"),
        default="multi_vector",
    )
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--output",
        default="data/phase8-verification.json",
    )
    args = parser.parse_args()

    try:
        result = run(args)
    except Exception as exc:
        print(f"PHASE 8 LIVE VERIFICATION FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(json.dumps(result, indent=2))
    if result["result"] != "passed":
        print("PHASE 8 LIVE VERIFICATION FAILED")
        return 1
    print("PHASE 8 LIVE VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
