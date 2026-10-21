"""Inject retrieved knowledge-base passages before each user turn (voice pipeline).

Tool calling is optional and often unsupported by voice-bundle LLMs; this processor
runs vector search on final STT text and appends excerpts to the LLM context.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from uuid import UUID

from loguru import logger

_GREETING_ONLY_RE = re.compile(
    r"^(?:hi|hey|hello|howdy|good\s+(?:morning|afternoon|evening))[\s,!.?]*"
    r"(?:how\s+are\s+you|what'?s\s+up)?[\s,!.?]*$",
    re.IGNORECASE,
)


def _should_retrieve_on_transcript(text: str, *, min_query_chars: int) -> bool:
    query = (text or "").strip()
    if len(query) < min_query_chars:
        return False
    if _GREETING_ONLY_RE.match(query):
        return False
    return True


def create_knowledge_base_inject_processor(
    context: Any,
    *,
    organization_id: str,
    workspace_id: str,
    agent_id: str,
    kb_notifier: Any = None,
    min_query_chars: int = 12,
    role: str = "production",
):
    """Return a FrameProcessor placed after STT and before the user context aggregator."""
    imports = None

    def _imports():
        nonlocal imports
        if imports is None:
            from efficientai.frames.frames import TranscriptionFrame
            from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

            imports = {
                "TranscriptionFrame": TranscriptionFrame,
                "FrameDirection": FrameDirection,
                "FrameProcessor": FrameProcessor,
            }
        return imports

    imp = _imports()
    FrameProcessor = imp["FrameProcessor"]
    FrameDirection = imp["FrameDirection"]
    TranscriptionFrame = imp["TranscriptionFrame"]

    org_uuid = UUID(organization_id)
    ws_uuid = UUID(workspace_id)
    agent_uuid = UUID(agent_id)

    class KnowledgeBaseInjectProcessor(FrameProcessor):
        def __init__(self):
            super().__init__()
            self._last_query: Optional[str] = None

        def _inject_sync(self, query: str) -> tuple[int, Optional[float]]:
            from app.database import SessionLocal
            from app.services.knowledge_bases.retrieval import (
                format_search_results_for_tool,
                search_knowledge_base,
            )

            db = SessionLocal()
            try:
                hits = search_knowledge_base(
                    db,
                    organization_id=org_uuid,
                    workspace_id=ws_uuid,
                    agent_id=agent_uuid,
                    query=query,
                    role=role,
                )
            finally:
                db.close()
            if not hits:
                return 0, None
            top_score = hits[0].get("score")
            block = format_search_results_for_tool(hits)
            context.add_message(
                {
                    "role": "system",
                    "content": (
                        "Retrieved passages from attached knowledge bases. "
                        "The production agent's last message asked about topics below; "
                        "use these facts in your next assistant reply when they answer "
                        "that question (do not refuse solely because of your persona):\n\n"
                        f"{block}"
                    ),
                }
            )
            return len(hits), top_score if isinstance(top_score, (int, float)) else None

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)

            if direction != FrameDirection.DOWNSTREAM:
                await self.push_frame(frame, direction)
                return

            if isinstance(frame, TranscriptionFrame):
                query = (frame.text or "").strip()
                if (
                    _should_retrieve_on_transcript(query, min_query_chars=min_query_chars)
                    and query != self._last_query
                ):
                    self._last_query = query
                    try:
                        hit_count, top_score = await asyncio.to_thread(self._inject_sync, query)
                    except Exception as exc:
                        logger.warning("[KnowledgeBase] auto-inject search failed: {}", exc)
                        hit_count, top_score = 0, None
                    else:
                        if hit_count:
                            logger.info(
                                "[KnowledgeBase] auto-inject agent_id={} query={!r} "
                                "hit_count={} top_score={}",
                                agent_id,
                                query,
                                hit_count,
                                top_score,
                            )
                            if kb_notifier is not None:
                                await kb_notifier.on_tool_call(
                                    query=query,
                                    hit_count=hit_count,
                                    channel="voice_rag_auto",
                                )
                        else:
                            logger.debug(
                                "[KnowledgeBase] auto-inject skipped/no hits agent_id={} query={!r}",
                                agent_id,
                                query,
                            )

            await self.push_frame(frame, direction)

    return KnowledgeBaseInjectProcessor()
