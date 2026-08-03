"""Live Phase 8 verifier for the experimental visual project-chat endpoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx

DEFAULT_QUESTION = (
    "Where is the second-stage regulator and meter shown, and how does the LPG "
    "piping route from the existing propane tank into the building? Cite the sheet "
    "number and state when any label is unclear."
)

_VISION_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "openai": (
        re.compile(r"^(gpt-4(?:o|\.1)|gpt-5|o[134])", re.IGNORECASE),
    ),
    "anthropic": (
        re.compile(r"^claude-(?:3|3\.5|3\.7|4)", re.IGNORECASE),
    ),
    "google": (
        re.compile(r"^(?:gemini|models/gemini)", re.IGNORECASE),
    ),
    "google-generative-ai": (
        re.compile(r"^(?:gemini|models/gemini)", re.IGNORECASE),
    ),
    "mistral": (
        re.compile(r"^(?:pixtral|mistral-(?:small|medium|large)-.*vision)", re.IGNORECASE),
    ),
    "groq": (
        re.compile(r"(?:vision|llama-3\.2-.*vision)", re.IGNORECASE),
    ),
    "ollama": (
        re.compile(
            r"(?:llava|bakllava|moondream|qwen(?:2|2\.5)?-?vl|gemma3|minicpm-v)",
            re.IGNORECASE,
        ),
    ),
}


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


def _get_json(client: httpx.Client, path: str) -> Any:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _normalized_provider(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _looks_vision_capable(model: dict[str, Any]) -> bool:
    provider = _normalized_provider(model.get("provider"))
    name = str(model.get("name") or "").strip()
    patterns = _VISION_PATTERNS.get(provider, ())
    return bool(name and any(pattern.search(name) for pattern in patterns))


def _model_summary(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(model.get("id") or ""),
        "name": str(model.get("name") or ""),
        "provider": str(model.get("provider") or ""),
        "vision_candidate": _looks_vision_capable(model),
    }


def _resolve_model_candidates(
    client: httpx.Client,
    explicit_model_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_models = _get_json(client, "/api/models?type=language")
    if not isinstance(raw_models, list):
        raise RuntimeError("Expected a list from /api/models?type=language")

    models = [dict(model) for model in raw_models if isinstance(model, dict)]
    diagnostics = [_model_summary(model) for model in models]
    by_id = {
        str(model.get("id") or ""): model
        for model in models
        if str(model.get("id") or "")
    }

    if explicit_model_id:
        selected = by_id.get(explicit_model_id)
        if selected is None:
            known = ", ".join(sorted(by_id)) or "none"
            raise RuntimeError(
                f"Requested model {explicit_model_id!r} is not configured. "
                f"Configured language model IDs: {known}"
            )
        ordered = [selected]
    else:
        defaults = _get_json(client, "/api/models/defaults")
        default_id = (
            str(defaults.get("default_chat_model") or "")
            if isinstance(defaults, dict)
            else ""
        )
        vision_models = [model for model in models if _looks_vision_capable(model)]
        ordered = sorted(
            vision_models,
            key=lambda model: (
                0 if str(model.get("id") or "") == default_id else 1,
                str(model.get("provider") or ""),
                str(model.get("name") or ""),
            ),
        )

    working: list[dict[str, Any]] = []
    for model in ordered:
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        test_path = f"/api/models/{quote(model_id, safe='')}/test"
        try:
            test = _post_json(client, test_path, {})
        except Exception as exc:
            test = {
                "success": False,
                "message": f"{type(exc).__name__}: {exc}",
            }
        summary = _model_summary(model)
        summary["test_success"] = bool(test.get("success"))
        summary["test_message"] = str(test.get("message") or "")
        for item in diagnostics:
            if item["id"] == model_id:
                item.update(
                    {
                        "test_success": summary["test_success"],
                        "test_message": summary["test_message"],
                    }
                )
                break
        if summary["test_success"]:
            working.append(summary)

    return working, diagnostics


def _create_session(
    client: httpx.Client,
    *,
    project_id: str,
    model: dict[str, Any],
) -> str:
    session = _post_json(
        client,
        "/api/chat/sessions",
        {
            "project_id": project_id,
            "title": f"Phase 8 visual verification - {model.get('name') or model['id']}",
            "model_override": model["id"],
        },
    )
    session_id = str(session.get("id") or "")
    if not session_id:
        raise RuntimeError("Unable to resolve a chat session ID")
    return session_id


def _run_candidate(
    client: httpx.Client,
    *,
    args: argparse.Namespace,
    model: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    request_body = {
        "session_id": session_id,
        "message": args.question,
        "model_override": model["id"],
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
    return {
        "model": model,
        "session_id": session_id,
        "answer": answer,
        "event_count": len(events),
        "errors": errors,
        "checks": checks,
        "result": "passed" if all(checks.values()) else "failed",
        "events": events,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    with httpx.Client(base_url=args.api, timeout=args.timeout) as client:
        candidates, model_diagnostics = _resolve_model_candidates(
            client,
            args.model_id,
        )
        attempts: list[dict[str, Any]] = []
        winning_attempt: dict[str, Any] | None = None

        for candidate in candidates:
            session_id = args.session_id or _create_session(
                client,
                project_id=args.project_id,
                model=candidate,
            )
            attempt = _run_candidate(
                client,
                args=args,
                model=candidate,
                session_id=session_id,
            )
            attempts.append({key: value for key, value in attempt.items() if key != "events"})
            if attempt["result"] == "passed":
                winning_attempt = attempt
                break
            if args.session_id:
                break

    all_events = winning_attempt["events"] if winning_attempt else []
    selected_attempt = winning_attempt or (
        {
            "model": None,
            "session_id": args.session_id,
            "answer": "",
            "event_count": 0,
            "errors": [
                "No configured vision-capable language model passed its model test."
                if not candidates
                else "Every tested vision model failed the live chat verification."
            ],
            "checks": {
                "no_run_error": False,
                "debug_event": False,
                "sheet_cited": False,
                "visual_backend": False,
                "multi_vector_marker": False,
            },
            "result": "failed",
        }
    )

    result = {
        "project_id": args.project_id,
        "source_id": args.source_id,
        "session_id": selected_attempt.get("session_id"),
        "mode": args.mode,
        "question": args.question,
        "model": selected_attempt.get("model"),
        "answer": selected_attempt.get("answer", ""),
        "event_count": selected_attempt.get("event_count", 0),
        "errors": selected_attempt.get("errors", []),
        "checks": selected_attempt.get("checks", {}),
        "attempts": attempts,
        "configured_models": model_diagnostics,
        "result": selected_attempt.get("result", "failed"),
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    events_output = Path(args.events_output)
    events_output.parent.mkdir(parents=True, exist_ok=True)
    events_output.write_text(json.dumps(all_events, indent=2), encoding="utf-8")
    result["report_path"] = str(output)
    result["events_path"] = str(events_output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:5056")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--session-id")
    parser.add_argument(
        "--model-id",
        help="Optional configured language-model record ID to use instead of auto-selection.",
    )
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
    parser.add_argument(
        "--events-output",
        default="data/phase8-events.json",
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
