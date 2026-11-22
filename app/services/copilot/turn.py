"""Run one copilot turn: stream the model's reply, execute its tool calls, persist.

Turns run on a bounded per-process thread pool, never on the event loop. The
HTTP request only relays events, so a client that disconnects doesn't stop the
turn: the reply is still saved, and the client can recover it by reading the
session's messages (a Redis snapshot covers the in-flight part).

DB connections are never held across an LLM call: every LLM call and tool call
opens its own short-lived session.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.services.copilot import redis_state, store
from app.services.copilot.prompts import build_system_prompt
from app.services.copilot.skills import (
    guidance_for,
    select_groups,
    tool_names_from_history,
    user_texts_from_history,
)
from app.services.copilot.registry import (
    LLMChoice,
    ToolContext,
    available_tools,
    execute,
    openai_definition,
)

Emit = Callable[[str, dict[str, Any]], None]

STORED_TOOL_RESULT_CHARS = 4_000
SNAPSHOT_INTERVAL_SECONDS = 1.0
CANCEL_CHECK_INTERVAL_SECONDS = 0.5
TEMPERATURE = 0.2


@dataclass(frozen=True)
class TurnInput:
    session_id: UUID
    user_message_id: UUID
    user_seq: int
    assistant_message_id: UUID
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    capabilities: frozenset[str]
    timezone: str
    page_context: Optional[dict[str, Any]]
    llm: LLMChoice


class _Stop(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class _TurnState:
    inp: TurnInput
    emit: Emit
    started: float = field(default_factory=time.monotonic)
    text: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    draft: Optional[dict[str, Any]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    _last_snapshot: float = 0.0
    _last_cancel_check: float = 0.0
    _round_has_text: bool = False

    @property
    def deadline(self) -> float:
        return self.started + settings.COPILOT_TURN_TIMEOUT_SECONDS

    def content(self) -> str:
        return "".join(self.text).strip()

    def check_stop(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if now > self.deadline:
            raise _Stop(store.STATUS_FAILED, "The assistant took too long to answer. Try a narrower question.")
        if force or now - self._last_cancel_check >= CANCEL_CHECK_INTERVAL_SECONDS:
            self._last_cancel_check = now
            if redis_state.is_cancelled(self.inp.assistant_message_id):
                raise _Stop(store.STATUS_CANCELLED, "Stopped.")

    def snapshot(self, status: str = store.STATUS_STREAMING, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_snapshot < SNAPSHOT_INTERVAL_SECONDS:
            return
        self._last_snapshot = now
        redis_state.write_snapshot(
            self.inp.assistant_message_id,
            {"status": status, "content": self.content(), "steps": self.steps},
        )

    def on_delta(self, delta: str) -> None:
        self.check_stop()
        if not self._round_has_text and self.text:
            # New model round after tool calls: start a new paragraph.
            self.text.append("\n\n")
            self.emit("token", {"text": "\n\n"})
        self._round_has_text = True
        self.text.append(delta)
        self.emit("token", {"text": delta})
        self.snapshot()


def _call_llm(
    state: _TurnState,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    session_factory: Callable[[], Session],
) -> dict[str, Any]:
    from app.services.ai.llm_service import llm_service

    llm = state.inp.llm
    db = session_factory()
    try:
        result = llm_service.generate_response_with_tools(
            messages=messages,
            tools=tools,
            llm_provider=llm.provider,
            llm_model=llm.model,
            organization_id=state.inp.organization_id,
            db=db,
            temperature=TEMPERATURE,
            credential_id=llm.credential_id,
            on_text_delta=state.on_delta,
            release_db_before_call=True,
        )
    finally:
        db.close()
    usage = result.get("usage") or {}
    prompt, completion = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    state.prompt_tokens += prompt
    state.completion_tokens += completion
    redis_state.add_org_tokens(state.inp.organization_id, prompt + completion)
    return result


def _llm_error_message(exc: Exception) -> str:
    text = str(exc).lower()
    if any(s in text for s in ("401", "unauthorized", "invalid api key", "authentication")):
        return "Your AI provider rejected the API key. Check it in Settings → AI Providers."
    if any(s in text for s in ("429", "rate limit", "quota", "insufficient")):
        return "Your AI provider is rate-limiting or out of quota. Try again shortly."
    return "The AI provider returned an error. Try again, or check Settings → AI Providers."


def _run_rounds(state: _TurnState, session_factory: Callable[[], Session]) -> None:
    inp = state.inp
    ctx = ToolContext(
        organization_id=inp.organization_id,
        workspace_id=inp.workspace_id,
        user_id=inp.user_id,
        capabilities=inp.capabilities,
        timezone=inp.timezone,
        session_id=inp.session_id,
        llm=inp.llm,
        message_id=inp.assistant_message_id,
    )
    db = session_factory()
    try:
        history = store.history_for_llm(
            db, inp.session_id, up_to_seq=inp.user_seq, limit=settings.COPILOT_HISTORY_MESSAGES
        )
    finally:
        db.close()
    permitted = available_tools(inp.capabilities)
    group_of = {t.name: t.group for t in permitted}
    groups = select_groups(
        user_texts=user_texts_from_history(history),
        page_context=inp.page_context,
        recent_tool_groups={group_of.get(n, "") for n in tool_names_from_history(history)},
    )
    tools = [t for t in permitted if t.group in groups]
    definitions = [openai_definition(t) for t in tools]
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                tz_name=inp.timezone,
                page_context=inp.page_context,
                tool_names=[t.name for t in tools],
                guidance=guidance_for(groups),
            ),
        },
        *history,
    ]

    max_rounds = max(1, settings.COPILOT_MAX_TOOL_ROUNDS)
    for round_index in range(max_rounds + 1):
        state.check_stop(force=True)
        state._round_has_text = False
        # Last round: no tools, so the model has to answer with what it has.
        offered = definitions if round_index < max_rounds else []
        try:
            result = _call_llm(state, messages, offered, session_factory)
        except _Stop:
            raise
        except Exception as exc:
            # llm_service wraps errors raised in on_delta (cancel, deadline).
            if isinstance(exc.__cause__, _Stop):
                raise exc.__cause__ from None
            logger.warning("[Copilot] LLM call failed for session {}: {}", inp.session_id, exc)
            raise _Stop(store.STATUS_FAILED, _llm_error_message(exc)) from exc

        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            return

        messages.append({"role": "assistant", "content": result.get("text") or None, "tool_calls": tool_calls})
        step: dict[str, Any] = {"text": result.get("text") or "", "calls": []}
        for call in tool_calls:
            state.check_stop(force=True)
            fn = call.get("function") or {}
            call_id = call.get("id") or f"call_{round_index}_{len(step['calls'])}"
            name = fn.get("name") or ""
            arguments = fn.get("arguments") or "{}"
            state.emit("tool_call", {"id": call_id, "name": name})
            outcome = execute(ctx, name, arguments, session_factory=session_factory)
            state.emit("tool_result", {
                "id": call_id,
                "name": name,
                "status": outcome.status,
                "latency_ms": outcome.latency_ms,
            })
            if outcome.ui is not None:
                state.emit(outcome.ui.get("type", "card"), outcome.ui)
                if outcome.ui.get("type") == "draft":
                    state.draft = outcome.ui.get("draft")
            step["calls"].append({
                "id": call_id,
                "name": name,
                "arguments": arguments if isinstance(arguments, str) else str(arguments),
                "status": outcome.status,
                "latency_ms": outcome.latency_ms,
                "content": outcome.content[:STORED_TOOL_RESULT_CHARS],
                **({"ui": outcome.ui} if outcome.ui is not None else {}),
            })
            messages.append({"role": "tool", "tool_call_id": call_id, "content": outcome.content})
        state.steps.append(step)
        state.snapshot(force=True)


def run_turn(
    inp: TurnInput,
    emit: Emit,
    *,
    session_factory: Optional[Callable[[], Session]] = None,
) -> str:
    """Run the turn to completion and persist it. Returns the final status. Never raises."""
    session_factory = session_factory or SessionLocal
    from app.services.usage.context import (
        LLMUsageContext,
        LLMUsageProductSection,
        llm_usage_context,
    )

    state = _TurnState(inp=inp, emit=emit)
    status, error = store.STATUS_COMPLETE, None
    try:
        with llm_usage_context(
            LLMUsageContext(
                organization_id=inp.organization_id,
                workspace_id=inp.workspace_id,
                product_section=LLMUsageProductSection.COPILOT,
                resource_id=inp.session_id,
                resource_type="copilot_session",
            )
        ):
            _run_rounds(state, session_factory)
        if not state.content():
            state.text.append("Sorry, I couldn't come up with an answer. Try rephrasing the question.")
            emit("token", {"text": state.content()})
    except _Stop as stop:
        status, error = stop.status, stop.message
        emit("error", {"code": stop.status, "message": stop.message})
    except Exception:
        logger.exception("[Copilot] turn crashed for session {}", inp.session_id)
        status, error = store.STATUS_FAILED, "Something went wrong. Try again."
        emit("error", {"code": "internal", "message": error})

    latency_ms = int((time.monotonic() - state.started) * 1000)
    try:
        db = session_factory()
        try:
            store.finish_turn(
                db,
                inp.assistant_message_id,
                content=state.content(),
                steps=state.steps,
                status=status,
                error=error,
                model=inp.llm.model,
                prompt_tokens=state.prompt_tokens,
                completion_tokens=state.completion_tokens,
                latency_ms=latency_ms,
                session_id=inp.session_id,
                draft={"test_setup": state.draft} if state.draft else None,
            )
        finally:
            db.close()
    except Exception:
        logger.exception("[Copilot] could not save turn {}", inp.assistant_message_id)
    state.snapshot(status, force=True)
    emit("done", {
        "message_id": str(inp.assistant_message_id),
        "status": status,
        "latency_ms": latency_ms,
        "usage": {"prompt_tokens": state.prompt_tokens, "completion_tokens": state.completion_tokens},
    })
    return status


# --- per-process execution ---------------------------------------------------

_pool_lock = threading.Lock()
_executor: Optional[ThreadPoolExecutor] = None
_slots: Optional[threading.BoundedSemaphore] = None


def _pool() -> tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    global _executor, _slots
    with _pool_lock:
        if _executor is None:
            size = max(1, settings.COPILOT_MAX_CONCURRENT_TURNS_PER_PROCESS)
            _executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="copilot-turn")
            _slots = threading.BoundedSemaphore(size)
        return _executor, _slots  # type: ignore[return-value]


def try_reserve_slot() -> bool:
    """Reject (rather than queue) when this process is at its turn limit, so the
    load balancer can send the retry to a less busy replica."""
    _, slots = _pool()
    return slots.acquire(blocking=False)


def release_slot() -> None:
    _, slots = _pool()
    try:
        slots.release()
    except ValueError:
        pass


def submit_turn(inp: TurnInput, emit: Emit) -> None:
    """Run a turn in the background. Caller must hold a slot; it is released here."""
    executor, _ = _pool()

    def _work() -> None:
        try:
            run_turn(inp, emit)
        finally:
            redis_state.release_turn_lock(inp.user_id, inp.assistant_message_id)
            release_slot()

    try:
        executor.submit(_work)
    except Exception:
        release_slot()
        redis_state.release_turn_lock(inp.user_id, inp.assistant_message_id)
        raise
