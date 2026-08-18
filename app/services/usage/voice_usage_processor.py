"""Voice pipeline processor that records LLM/TTS usage from MetricsFrames."""

from __future__ import annotations

import math
from typing import Optional
from uuid import UUID

from loguru import logger


def create_llm_usage_recorder(
    *,
    organization_id: UUID | str | None,
    workspace_id: UUID | str | None = None,
    product_section: str = "playground",
    resource_id: UUID | str | None = None,
    resource_type: Optional[str] = None,
):
    """Build a FrameProcessor that records LLM/TTS usage from MetricsFrames.

    Returns None when organization_id is missing or efficientai is unavailable.
    """
    if not organization_id:
        return None

    try:
        from efficientai.frames.frames import Frame, MetricsFrame
        from efficientai.metrics.metrics import (
            LLMUsageMetricsData,
            ProcessingMetricsData,
            TTSUsageMetricsData,
        )
        from efficientai.processors.frame_processor import FrameDirection, FrameProcessor

        from app.services.usage.context import (
            LLMUsageContext,
            LLMUsageProductSection,
        )
        from app.services.usage.llm_usage import (
            record_llm_usage,
            record_stt_usage,
            record_tts_usage,
        )
        from app.services.usage.normalize import UsageSnapshot, usage_snapshot_is_billable
    except Exception as exc:
        logger.debug("voice usage recorder unavailable: {}", exc)
        return None

    try:
        section = LLMUsageProductSection(product_section)
    except ValueError:
        section = LLMUsageProductSection.OTHER

    org_uuid = UUID(str(organization_id))
    ws_uuid = UUID(str(workspace_id)) if workspace_id else None
    res_uuid = UUID(str(resource_id)) if resource_id else None

    usage_ctx = LLMUsageContext(
        organization_id=org_uuid,
        workspace_id=ws_uuid,
        product_section=section,
        resource_id=res_uuid,
        resource_type=resource_type,
    )

    class LLMUsageRecorderProcessor(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, MetricsFrame):
                for item in frame.data or []:
                    if isinstance(item, LLMUsageMetricsData) and item.value is not None:
                        tokens = item.value
                        snapshot = UsageSnapshot(
                            prompt_tokens=int(tokens.prompt_tokens or 0),
                            completion_tokens=int(tokens.completion_tokens or 0),
                            cache_read_tokens=int(tokens.cache_read_input_tokens or 0),
                            cache_creation_tokens=int(
                                tokens.cache_creation_input_tokens or 0
                            ),
                            reasoning_tokens=int(tokens.reasoning_tokens or 0),
                        )
                        if not usage_snapshot_is_billable(snapshot):
                            continue
                        record_llm_usage(
                            item.model or "unknown",
                            snapshot,
                            organization_id=org_uuid,
                            ctx=usage_ctx,
                        )
                    elif isinstance(item, TTSUsageMetricsData):
                        record_tts_usage(
                            item.model or "unknown",
                            characters=int(item.value or 0),
                            organization_id=org_uuid,
                            ctx=usage_ctx,
                        )
                    elif isinstance(item, ProcessingMetricsData):
                        processor_name = (item.processor or "").lower()
                        if "stt" in processor_name and item.value is not None:
                            seconds = max(1, int(math.ceil(float(item.value))))
                            record_stt_usage(
                                item.model or "unknown",
                                audio_seconds=seconds,
                                organization_id=org_uuid,
                                ctx=usage_ctx,
                            )
            await self.push_frame(frame, direction)

    return LLMUsageRecorderProcessor()
