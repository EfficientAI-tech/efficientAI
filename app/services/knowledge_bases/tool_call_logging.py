"""Structured logging for search_knowledge_base invocations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

NotifyFn = Callable[[Dict[str, Any]], Awaitable[None]]


def record_knowledge_base_tool_call(
    *,
    channel: str,
    query: str,
    hit_count: int,
    agent_id: str,
    llm_model: Optional[str] = None,
    tool_calls_log: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Log to terminal and optionally append to an in-memory session log."""
    entry: Dict[str, Any] = {
        "tool": "search_knowledge_base",
        "query": query,
        "hit_count": hit_count,
        "agent_id": agent_id,
        "channel": channel,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if llm_model:
        entry["llm_model"] = llm_model

    logger.info(
        "[KnowledgeBase] tool_call channel={} model={} agent_id={} query={!r} hit_count={}",
        channel,
        llm_model or "—",
        agent_id,
        query,
        hit_count,
    )

    if tool_calls_log is not None:
        tool_calls_log.append(entry)
    return entry


class KnowledgeBaseVoiceNotifier:
    """Optional live RTVI push when a voice-bundle KB search runs."""

    def __init__(
        self,
        *,
        agent_id: str,
        llm_model: Optional[str] = None,
        tool_calls_log: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.agent_id = agent_id
        self.llm_model = llm_model
        self.tool_calls_log = tool_calls_log
        self._rtvi: Any = None
        self._notify_fn: Optional[NotifyFn] = None

    def bind_rtvi(self, rtvi: Any) -> None:
        self._rtvi = rtvi

    def bind_notify(self, notify_fn: NotifyFn) -> None:
        self._notify_fn = notify_fn

    async def on_tool_call(
        self, *, query: str, hit_count: int, channel: str = "voice_bundle"
    ) -> None:
        entry = record_knowledge_base_tool_call(
            channel=channel,
            query=query,
            hit_count=hit_count,
            agent_id=self.agent_id,
            llm_model=self.llm_model,
            tool_calls_log=self.tool_calls_log,
        )
        payload = {"type": "knowledge_base_tool_call", **entry}
        if self._notify_fn is not None:
            try:
                await self._notify_fn(payload)
            except Exception as exc:
                logger.warning("[KnowledgeBase] live notify failed: {}", exc)
        elif self._rtvi is not None:
            try:
                await self._rtvi.send_server_message(payload)
            except Exception as exc:
                logger.warning("[KnowledgeBase] RTVI notify failed: {}", exc)
