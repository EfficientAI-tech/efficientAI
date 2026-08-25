"""Extract production-agent LLM usage from external voice provider call payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from loguru import logger

from app.services.usage.context import LLMUsageContext
from app.services.usage.llm_usage import record_llm_usage, record_stt_usage, record_tts_usage
from app.services.usage.normalize import UsageSnapshot, usage_snapshot_is_billable


@dataclass(frozen=True)
class ExternalAgentUsageExtraction:
    model: str
    llm: Optional[UsageSnapshot] = None
    stt_audio_seconds: int = 0
    tts_characters: int = 0


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _pick(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _vapi_cost_breakdown(call_data: dict[str, Any]) -> dict[str, Any]:
    raw = call_data.get("costBreakdown") or call_data.get("cost_breakdown") or {}
    return raw if isinstance(raw, dict) else {}


def _retell_llm_snapshot(call_data: dict[str, Any]) -> Optional[UsageSnapshot]:
    llm_usage = call_data.get("llm_token_usage") or {}
    if not isinstance(llm_usage, dict):
        llm_usage = {}

    prompt = completion = 0
    direct_fields = (
        ("prompt_tokens", "prompt"),
        ("input_tokens", "prompt"),
        ("llm_prompt_tokens", "prompt"),
        ("completion_tokens", "completion"),
        ("output_tokens", "completion"),
        ("llm_completion_tokens", "completion"),
    )
    for key, bucket in direct_fields:
        value = _as_int(llm_usage.get(key))
        if value <= 0:
            continue
        if bucket == "prompt":
            prompt += value
        else:
            completion += value

    call_cost = call_data.get("call_cost") or {}
    product_costs = call_cost.get("product_costs") if isinstance(call_cost, dict) else None
    if isinstance(product_costs, list):
        for item in product_costs:
            if not isinstance(item, dict):
                continue
            product = str(item.get("product") or "").lower()
            if "llm" not in product and "gpt" not in product and "model" not in product:
                continue
            prompt += _as_int(_pick(item.get("prompt_tokens"), item.get("input_tokens")))
            completion += _as_int(
                _pick(item.get("completion_tokens"), item.get("output_tokens"))
            )

    latency = call_data.get("latency") or {}
    if isinstance(latency, dict):
        llm_latency = latency.get("llm")
        if isinstance(llm_latency, dict):
            prompt += _as_int(_pick(llm_latency.get("prompt_tokens"), llm_latency.get("input_tokens")))
            completion += _as_int(
                _pick(llm_latency.get("completion_tokens"), llm_latency.get("output_tokens"))
            )

    if prompt > 0 or completion > 0:
        return UsageSnapshot(prompt_tokens=prompt, completion_tokens=completion)

    values = llm_usage.get("values")
    total_tokens = sum(_as_int(v) for v in values) if isinstance(values, list) else 0
    if total_tokens <= 0:
        return None

    prompt = int(round(total_tokens * 0.7))
    completion = max(0, total_tokens - prompt)
    return UsageSnapshot(prompt_tokens=prompt, completion_tokens=completion)


def extract_external_agent_usage(
    call_data: dict[str, Any] | None,
    *,
    platform: str,
) -> Optional[ExternalAgentUsageExtraction]:
    if not isinstance(call_data, dict) or not call_data:
        return None

    platform_key = (platform or "").strip().lower()
    if platform_key == "vapi":
        cb = _vapi_cost_breakdown(call_data)
        snapshot = UsageSnapshot(
            prompt_tokens=_as_int(
                _pick(cb.get("llmPromptTokens"), cb.get("llm_prompt_tokens"))
            ),
            completion_tokens=_as_int(
                _pick(cb.get("llmCompletionTokens"), cb.get("llm_completion_tokens"))
            ),
            cache_read_tokens=_as_int(
                _pick(
                    cb.get("llmCachedPromptTokens"),
                    cb.get("llm_cached_prompt_tokens"),
                )
            ),
        )
        model = (
            _pick(
                call_data.get("model"),
                call_data.get("assistant", {}).get("model")
                if isinstance(call_data.get("assistant"), dict)
                else None,
            )
            or "vapi-agent"
        )
        duration = _as_int(
            _pick(
                call_data.get("durationSeconds"),
                call_data.get("duration_seconds"),
            )
        )
        tts_chars = _as_int(
            _pick(cb.get("ttsCharacters"), cb.get("tts_characters"))
        )
        if not usage_snapshot_is_billable(snapshot) and duration <= 0 and tts_chars <= 0:
            return None
        return ExternalAgentUsageExtraction(
            model=str(model),
            llm=snapshot if usage_snapshot_is_billable(snapshot) else None,
            stt_audio_seconds=duration,
            tts_characters=tts_chars,
        )

    if platform_key == "retell":
        call_cost = call_data.get("call_cost") or {}
        duration_ms = call_data.get("duration_ms")
        duration = _as_int(
            _pick(
                call_cost.get("total_duration_seconds")
                if isinstance(call_cost, dict)
                else None,
                int(duration_ms) / 1000 if duration_ms else None,
                call_data.get("duration_seconds"),
                call_data.get("duration"),
            )
        )
        model = _pick(call_data.get("llm_model"), call_data.get("model")) or "retell-agent"
        snapshot = _retell_llm_snapshot(call_data)
        if not usage_snapshot_is_billable(snapshot) and duration <= 0:
            return None
        return ExternalAgentUsageExtraction(
            model=str(model),
            llm=snapshot if usage_snapshot_is_billable(snapshot) else None,
            stt_audio_seconds=duration,
        )

    if platform_key == "elevenlabs":
        metadata = call_data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        duration = _as_int(
            _pick(
                metadata.get("call_duration_secs"),
                call_data.get("duration_seconds"),
                call_data.get("duration"),
            )
        )
        if duration <= 0:
            return None
        return ExternalAgentUsageExtraction(
            model="elevenlabs-agent",
            stt_audio_seconds=duration,
        )

    if platform_key == "smallest":
        duration = _as_int(
            _pick(
                call_data.get("duration_seconds"),
                call_data.get("duration"),
            )
        )
        if duration <= 0:
            return None
        return ExternalAgentUsageExtraction(
            model="smallest-agent",
            stt_audio_seconds=duration,
        )

    return None


def record_playground_provider_usage_from_call_data(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    agent_id: Optional[UUID],
    provider_platform: str,
    call_short_id: Optional[str],
    call_data: dict[str, Any],
) -> dict[str, Any]:
    """Record provider usage for a completed playground Voice AI call."""
    from types import SimpleNamespace

    from app.services.usage.context import (
        llm_usage_context,
        usage_context_for_playground_voice_call,
    )

    metrics = dict(call_data or {})
    if metrics.get("external_usage_recorded"):
        return metrics

    usage_ctx = usage_context_for_playground_voice_call(
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        provider_platform=provider_platform,
        call_short_id=call_short_id,
    )
    stub = SimpleNamespace(
        organization_id=organization_id,
        provider_platform=provider_platform,
        call_data=metrics,
        result_id=call_short_id or "playground",
    )
    with llm_usage_context(usage_ctx):
        record_external_agent_usage(stub, usage_ctx=usage_ctx)
    metrics["external_usage_recorded"] = True
    return metrics


def record_external_agent_usage(
    result: Any,
    *,
    usage_ctx: LLMUsageContext,
) -> None:
    """Record production-agent usage from stored provider call_data."""
    call_data = getattr(result, "call_data", None)
    platform = getattr(result, "provider_platform", None) or ""
    extraction = extract_external_agent_usage(
        call_data if isinstance(call_data, dict) else None,
        platform=str(platform),
    )
    if extraction is None:
        return

    org_id = getattr(result, "organization_id", None)
    if org_id is None:
        return

    ctx = LLMUsageContext(
        organization_id=usage_ctx.organization_id,
        workspace_id=usage_ctx.workspace_id,
        product_section=usage_ctx.product_section,
        resource_id=usage_ctx.resource_id,
        resource_type=usage_ctx.resource_type,
        extra={
            **(usage_ctx.extra or {}),
            "synthetic_testing": "pre_prod",
            "simulation_leg": "production_agent",
            "provider_platform": str(platform).lower(),
        },
    )

    try:
        if extraction.llm and usage_snapshot_is_billable(extraction.llm):
            record_llm_usage(
                extraction.model,
                extraction.llm,
                organization_id=org_id,
                ctx=ctx,
            )
        if extraction.stt_audio_seconds > 0:
            record_stt_usage(
                f"{platform}-stt",
                audio_seconds=extraction.stt_audio_seconds,
                organization_id=org_id,
                ctx=ctx,
                count_call=False,
            )
        if extraction.tts_characters > 0:
            record_tts_usage(
                f"{platform}-tts",
                characters=extraction.tts_characters,
                organization_id=org_id,
                ctx=ctx,
            )
    except Exception as exc:
        logger.debug(
            "external agent usage record skipped for result {}: {}",
            getattr(result, "result_id", result),
            exc,
        )
