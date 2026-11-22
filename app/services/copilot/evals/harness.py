"""Copilot eval harness: run golden conversations and score them.

Scoring is pure (``score_case``) so it is unit-tested; ``run_cases`` drives
real turns against a real workspace and the org's own LLM, so run it on a
staging workspace (it costs LLM tokens, writes nothing but its own throwaway
conversations, and proposals it makes are never confirmed).
"""

from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

CASES_PATH = Path(__file__).with_name("cases.json")


@dataclass
class Transcript:
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    answer: str = ""
    status: str = "complete"
    latency_ms: int = 0
    tokens: int = 0


@dataclass
class CaseResult:
    id: str
    passed: bool
    failures: list[str]
    tools: list[str]
    latency_ms: int = 0
    tokens: int = 0
    skipped: Optional[str] = None


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases


def _matches(name: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)


def score_case(case: dict[str, Any], t: Transcript) -> CaseResult:
    expect = case.get("expect", {})
    names = [n for n, _ in t.tool_calls]
    answer = t.answer.lower()
    failures: list[str] = []

    if t.status != "complete":
        failures.append(f"turn ended {t.status}")
    for pattern in expect.get("tools_called", []):
        if not any(_matches(n, pattern) for n in names):
            failures.append(f"expected a call to {pattern}")
    any_of = expect.get("tools_called_any")
    if any_of and not any(_matches(n, p) for n in names for p in any_of):
        failures.append(f"expected a call to one of {any_of}")
    for pattern in expect.get("tools_not_called", []):
        bad = [n for n in names if _matches(n, pattern)]
        if bad:
            failures.append(f"must not call {pattern} (called {bad})")
    for tool, wanted in expect.get("tool_args", {}).items():
        calls = [args for n, args in t.tool_calls if n == tool]
        if calls and not any(all(str(args.get(k)).lower() == str(v).lower() for k, v in wanted.items()) for args in calls):
            failures.append(f"{tool} arguments {calls[0]} don't include {wanted}")
    if "max_tool_calls" in expect and len(names) > expect["max_tool_calls"]:
        failures.append(f"{len(names)} tool calls > max {expect['max_tool_calls']}")
    contains_any = expect.get("answer_contains_any")
    if contains_any and not any(s.lower() in answer for s in contains_any):
        failures.append(f"answer mentions none of {contains_any}")
    for s in expect.get("answer_not_contains", []):
        if s.lower() in answer:
            failures.append(f"answer must not say {s!r}")
    return CaseResult(
        id=case["id"], passed=not failures, failures=failures, tools=names,
        latency_ms=t.latency_ms, tokens=t.tokens,
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    ran = [r for r in results if not r.skipped]
    passed = sum(r.passed for r in ran)
    latencies = sorted(r.latency_ms for r in ran) or [0]
    return {
        "cases": len(results),
        "ran": len(ran),
        "passed": passed,
        "pass_rate": round(passed / len(ran), 4) if ran else None,
        "p50_latency_ms": latencies[len(latencies) // 2],
        "p95_latency_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        "total_tokens": sum(r.tokens for r in ran),
        "results": [r.__dict__ for r in results],
    }


def _fill(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in variables.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, variables) for k, v in value.items()}
    return value


def run_cases(
    *,
    organization_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    variables: Optional[dict[str, str]] = None,
    only: Optional[set[str]] = None,
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    """Run every case as a real turn in its own throwaway conversation."""
    from app.core.auth.capabilities import ALL_CAPABILITIES
    from app.database import SessionLocal
    from app.models.database import CopilotSession
    from app.services.copilot import store
    from app.services.copilot.readiness import check_readiness
    from app.services.copilot.turn import TurnInput, run_turn

    variables = variables or {}
    results: list[CaseResult] = []
    db = SessionLocal()
    try:
        readiness = check_readiness(db, organization_id)
        if not readiness.ready or readiness.llm is None:
            raise RuntimeError(f"copilot not ready for org: {[r.message for r in readiness.reasons]}")
        for case in load_cases():
            if only and case["id"] not in only:
                continue
            missing = [v for v in case.get("requires", []) if v not in variables]
            if missing:
                results.append(CaseResult(case["id"], False, [], [], skipped=f"needs --var {missing[0]}=..."))
                continue
            session = store.create_session(
                db, organization_id=organization_id, workspace_id=workspace_id, user_id=user_id,
                title=f"[eval] {case['id']}",
            )
            try:
                rows = store.begin_turn(
                    db, session, content=case["message"], client_message_id=None,
                    page_context=_fill(case.get("page_context"), variables),
                )
                started = time.monotonic()
                run_turn(
                    TurnInput(
                        session_id=session.id,
                        user_message_id=rows.user_message.id,
                        user_seq=rows.user_message.seq,
                        assistant_message_id=rows.assistant_message.id,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        user_id=user_id,
                        capabilities=frozenset(ALL_CAPABILITIES),
                        timezone=timezone_name,
                        page_context=_fill(case.get("page_context"), variables),
                        llm=readiness.llm,
                    ),
                    lambda event, data: None,
                )
                db.expire_all()
                reply = db.get(type(rows.assistant_message), rows.assistant_message.id)
                transcript = Transcript(
                    tool_calls=[
                        (c["name"], _args(c.get("arguments")))
                        for step in (reply.steps or []) for c in step.get("calls", [])
                    ],
                    answer=reply.content or "",
                    status=reply.status,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    tokens=int(reply.prompt_tokens or 0) + int(reply.completion_tokens or 0),
                )
                results.append(score_case(case, transcript))
            finally:
                db.query(CopilotSession).filter(CopilotSession.id == session.id).delete()
                db.commit()
    finally:
        db.close()
    return summarize(results)


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}
