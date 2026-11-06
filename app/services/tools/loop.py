"""LLM ↔ tool loop: call the model with tools until it answers in text or hits the round cap."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service
from app.services.tools.base import TOOL_STATUS_ERROR, ToolCallRecord
from app.services.tools.toolset import Toolset

DEFAULT_MAX_TOOL_ROUNDS = 8


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], Optional[str]]:
    if isinstance(raw, dict):
        return dict(raw), None
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        return {}, f"Invalid JSON arguments: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Tool arguments must be a JSON object"
    return parsed, None


def run_tool_loop(
    db: Session,
    *,
    toolset: Toolset,
    messages: list[dict[str, Any]],
    organization_id: UUID,
    llm_provider: ModelProvider,
    llm_model: str,
    llm_config: Optional[dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
    task_defaults: Optional[dict[str, Any]] = None,
    max_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    side: str = "production",
) -> tuple[str, list[ToolCallRecord], list[dict[str, Any]]]:
    """Return ``(reply_text, tool_call_records, messages_appended)``; tool failures go back to the model."""
    records: list[ToolCallRecord] = []
    working = list(messages)
    initial_len = len(working)
    empty_retries = 0
    for _ in range(max_rounds):
        result = llm_service.generate_response_with_tools(
            messages=working,
            tools=toolset.definitions(),
            llm_provider=llm_provider,
            llm_model=llm_model,
            organization_id=organization_id,
            db=db,
            llm_config=llm_config,
            credential_id=credential_id,
            task_defaults=task_defaults,
        )
        tool_calls = result.get("tool_calls")
        if not tool_calls:
            text = (result.get("text") or "").strip()
            # length with no text means the output budget was used up (often by
            # reasoning) before a reply or a tool call was finished. Try again
            # instead of treating that as the customer's answer.
            if text:
                return text, records, working[initial_len:]
            if result.get("finish_reason") == "length" or empty_retries < 1:
                empty_retries += 1
                continue
            return "", records, working[initial_len:]
        working.append(
            {"role": "assistant", "content": result.get("text") or None, "tool_calls": tool_calls}
        )
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            arguments, parse_error = _parse_arguments(fn.get("arguments"))
            if parse_error:
                content = parse_error
                records.append(
                    ToolCallRecord(
                        call_id=call.get("id"),
                        tool=name,
                        provider="unknown",
                        arguments={"raw": fn.get("arguments")},
                        status=TOOL_STATUS_ERROR,
                        result_preview=parse_error,
                        latency_ms=0,
                        side=side,
                        error=parse_error,
                    )
                )
            else:
                tool_result, record = toolset.execute(
                    name, arguments, call_id=call.get("id"), side=side
                )
                content = tool_result.content
                records.append(record)
            working.append({"role": "tool", "tool_call_id": call.get("id"), "content": content})

    working.append(
        {
            "role": "user",
            "content": (
                "Reply to the customer now in plain text, using the tool results above. "
                "Do not call another tool."
            ),
        }
    )
    final = llm_service.generate_response(
        messages=working,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        credential_id=credential_id,
        task_defaults=task_defaults,
    )
    return (final.get("text") or "").strip(), records, working[initial_len:]
