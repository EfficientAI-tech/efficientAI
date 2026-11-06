"""Deterministic tool-use checks for a trial (no LLM): success rate and scenario expectations.

A scenario's ``expected_tool_calls`` is a list of expectations::

    {"tool": "search_knowledge_base", "args_contains": {"query": "refund"}, "min_calls": 1}
    {"tool": "slack__post_message", "forbidden": true}
    {"tool": "postgres__query", "must_succeed": true, "mock_response": {...}}

``args_contains`` matches case-insensitive substrings of the call's arguments.
``mock_response`` is used by the toolset, not by these checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.tools.base import TOOL_STATUS_ERROR

KB_TOOL = "search_knowledge_base"


def _args_match(arguments: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in (expected or {}).items():
        actual = arguments.get(key)
        if actual is None or str(value).lower() not in str(actual).lower():
            return False
    return True


def _check_expectation(expectation: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    tool = str(expectation.get("tool") or "")
    forbidden = bool(expectation.get("forbidden"))
    matching = [
        c
        for c in calls
        if c.get("tool") == tool
        and _args_match(c.get("arguments") or {}, expectation.get("args_contains") or {})
    ]
    if forbidden:
        satisfied = not matching
        reason = (
            None if satisfied else f"{tool} was called {len(matching)} time(s) but is forbidden"
        )
        return {
            **expectation,
            "satisfied": satisfied,
            "matched_calls": len(matching),
            "reason": reason,
        }

    if expectation.get("must_succeed"):
        matching = [c for c in matching if c.get("status") != TOOL_STATUS_ERROR]
    min_calls = int(expectation.get("min_calls") or 1)
    max_calls = expectation.get("max_calls")
    reason = None
    if len(matching) < min_calls:
        what = "successful matching" if expectation.get("must_succeed") else "matching"
        reason = f"expected at least {min_calls} {what} call(s) to {tool}, got {len(matching)}"
    elif max_calls is not None and len(matching) > int(max_calls):
        reason = f"expected at most {max_calls} call(s) to {tool}, got {len(matching)}"
    return {
        **expectation,
        "satisfied": reason is None,
        "matched_calls": len(matching),
        "reason": reason,
    }


@dataclass
class ToolCheckReport:
    total_calls: int = 0
    errored_calls: int = 0
    kb_calls: int = 0
    kb_calls_with_hits: int = 0
    expectations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> Optional[float]:
        if not self.total_calls:
            return None
        return round((self.total_calls - self.errored_calls) / self.total_calls, 4)

    @property
    def kb_hit_rate(self) -> Optional[float]:
        return round(self.kb_calls_with_hits / self.kb_calls, 4) if self.kb_calls else None

    @property
    def has_expectations(self) -> bool:
        return bool(self.expectations)

    @property
    def all_expectations_met(self) -> bool:
        return all(e["satisfied"] for e in self.expectations)

    @property
    def expectation_score(self) -> Optional[float]:
        if not self.expectations:
            return None
        met = sum(1 for e in self.expectations if e["satisfied"])
        return round(met / len(self.expectations), 4)

    @property
    def forbidden_violations(self) -> int:
        return sum(1 for e in self.expectations if e.get("forbidden") and not e["satisfied"])

    def rewards(self) -> dict[str, float]:
        """``tool_*`` reward components for Harbor (only the ones that apply)."""
        values = {
            "tool_success_rate": self.success_rate,
            "tool_expectations_met": self.expectation_score,
            "kb_retrieval_hit_rate": self.kb_hit_rate,
        }
        return {key: value for key, value in values.items() if value is not None}

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "errored_calls": self.errored_calls,
            "success_rate": self.success_rate,
            "kb_calls": self.kb_calls,
            "kb_hit_rate": self.kb_hit_rate,
            "expectations": self.expectations,
            "expectation_score": self.expectation_score,
            "all_expectations_met": self.all_expectations_met if self.has_expectations else None,
            "forbidden_violations": self.forbidden_violations,
        }


def check_tool_calls(
    tool_calls: Optional[list[dict[str, Any]]],
    expected_tool_calls: Optional[list[dict[str, Any]]],
) -> ToolCheckReport:
    calls = [
        c
        for c in tool_calls or []
        if isinstance(c, dict) and c.get("side", "production") == "production"
    ]
    kb_calls = [
        c for c in calls if c.get("tool") == KB_TOOL and c.get("status") != TOOL_STATUS_ERROR
    ]
    return ToolCheckReport(
        total_calls=len(calls),
        errored_calls=sum(1 for c in calls if c.get("status") == TOOL_STATUS_ERROR),
        kb_calls=len(kb_calls),
        kb_calls_with_hits=sum(1 for c in kb_calls if (c.get("hit_count") or 0) > 0),
        expectations=[
            _check_expectation(e, calls)
            for e in expected_tool_calls or []
            if isinstance(e, dict) and e.get("tool")
        ],
    )


def format_tool_calls_for_judge(
    tool_calls: Optional[list[dict[str, Any]]], limit: int = 600
) -> str:
    """``## Tool Calls`` section appended to the judge's transcript (empty when none)."""
    calls = [c for c in tool_calls or [] if isinstance(c, dict)]
    if not calls:
        return ""
    lines = [
        "## Tool Calls (made by the production agent, Speaker 2)",
        "Each call shows its turn, arguments, status and the result the agent saw.",
    ]
    for call in calls:
        result = (call.get("result_preview") or "").strip().replace("\n", " ")
        if len(result) > limit:
            result = result[:limit] + "…"
        lines.append(
            f"- turn {call.get('turn_index')}: {call.get('tool')}({call.get('arguments') or {}}) "
            f"→ {call.get('status')}: {result}"
        )
    return "\n".join(lines)
