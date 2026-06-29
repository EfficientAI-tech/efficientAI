"""Flexprice usage metering (optional; no-op when disabled).

Event naming: ``product.action`` snake_case (e.g. ``call_import.batch_created``).
Every event uses ``external_customer_id=str(organization.id)`` and a stable
``event_id`` for idempotency. ``properties`` should include ``workspace_id`` and
``feature`` (license key) when the surface is gated.
"""

from __future__ import annotations

from typing import Any, Optional, Union
from uuid import UUID

from loguru import logger

from app.config import settings

EVENT_SOURCE = "efficientai"
FEATURE_CALL_IMPORTS = "call_imports"
FEATURE_VOICE_PLAYGROUND = "voice_playground"
FEATURE_GEPA = "gepa_optimization"

# Event names
BLIND_TEST_SHARE_CREATED = "blind_test.share_created"
BLIND_TEST_RESPONSE_SUBMITTED = "blind_test.response_submitted"
TTS_GENERATION_STARTED = "tts.generation_started"
TTS_SAMPLE_SYNTHESIZED = "tts.sample_synthesized"
TTS_REPORT_REQUESTED = "tts.report_requested"
TTS_REPORT_COMPLETED = "tts.report_completed"
CALL_IMPORT_BATCH_CREATED = "call_import.batch_created"
CALL_IMPORT_ROW_IMPORTED = "call_import.row_imported"
CALL_IMPORT_EVALUATION_STARTED = "call_import.evaluation_started"
CALL_IMPORT_EVALUATION_COMPLETED = "call_import.evaluation_completed"
CALL_IMPORT_EVALUATION_ROW_COMPLETED = "call_import.evaluation_row_completed"
PLAYGROUND_WEB_CALL_STARTED = "playground.web_call_started"
PLAYGROUND_WEBSOCKET_SESSION_STARTED = "playground.websocket_session_started"
PLAYGROUND_CALL_EVALUATED = "playground.call_evaluated"
PLAYGROUND_EVALUATION_COMPLETED = "playground.evaluation_completed"
EVALUATOR_RUN_REQUESTED = "evaluator.run_requested"
EVALUATOR_RUN_COMPLETED = "evaluator.run_completed"
EVALUATION_CREATED = "evaluation.created"
EVALUATION_COMPLETED = "evaluation.completed"
PROMPT_OPTIMIZATION_RUN_STARTED = "prompt_optimization.run_started"
PROMPT_OPTIMIZATION_RUN_COMPLETED = "prompt_optimization.run_completed"
JUDGE_ALIGNMENT_RUN_STARTED = "judge_alignment.run_started"
JUDGE_ALIGNMENT_RUN_COMPLETED = "judge_alignment.run_completed"
OBSERVABILITY_CALL_INGESTED = "observability.call_ingested"
OBSERVABILITY_CALL_EVALUATED = "observability.call_evaluated"
TEST_AGENT_CONVERSATION_STARTED = "test_agent.conversation_started"
TEST_AGENT_CONVERSATION_ENDED = "test_agent.conversation_ended"
METRICS_LLM_ASSIST = "metrics.llm_assist"
CHAT_COMPLETION = "chat.completion"


def is_enabled() -> bool:
    """Return True only when Flexprice is explicitly enabled with an API key."""
    return bool(settings.FLEXPRICE_ENABLED and settings.FLEXPRICE_API_KEY)


def _is_customer_already_exists(exc: Exception) -> bool:
    message = str(exc).lower()
    if "already exist" in message or "duplicate" in message:
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code == 409


def _ingest_usage_event(client, payload: dict) -> None:
    """Call Flexprice event ingest across SDK versions (flat kwargs vs request=)."""
    events = client.events
    ingest = getattr(events, "ingest_event", None) or getattr(events, "ingest", None)
    if ingest is None:
        raise AttributeError("Flexprice SDK has no events.ingest_event or events.ingest")

    try:
        ingest(**payload)
    except TypeError:
        ingest(request=payload)


def _coerce_properties(properties: Optional[dict[str, Any]]) -> dict[str, str]:
    """Normalize event properties for Flexprice ingest (SDK expects string values)."""
    if not properties:
        return {}
    out: dict[str, str] = {}
    for key, value in properties.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (int, float, UUID)):
            out[key] = str(value)
        else:
            out[key] = str(value)
    return out


def record_event(
    event_name: str,
    organization_id: UUID,
    event_id: Union[str, UUID],
    *,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    """Ingest a usage event. No-op when Flexprice is disabled; never raises."""
    if not is_enabled():
        return

    try:
        from flexprice import Flexprice

        with Flexprice(
            server_url=settings.FLEXPRICE_API_HOST,
            api_key_auth=settings.FLEXPRICE_API_KEY,
        ) as client:
            _ingest_usage_event(
                client,
                {
                    "event_name": event_name,
                    "external_customer_id": str(organization_id),
                    "event_id": str(event_id),
                    "source": EVENT_SOURCE,
                    "properties": _coerce_properties(properties),
                },
            )
    except Exception as exc:
        logger.warning(
            "Flexprice {} ingest failed (event_id={}): {}",
            event_name,
            event_id,
            exc,
        )


def ensure_customer(
    organization_id: UUID,
    *,
    name: str,
    email: Optional[str] = None,
) -> None:
    """Register an organization as a Flexprice customer. No-op when disabled."""
    if not is_enabled():
        return

    try:
        from flexprice import Flexprice

        with Flexprice(
            server_url=settings.FLEXPRICE_API_HOST,
            api_key_auth=settings.FLEXPRICE_API_KEY,
        ) as client:
            client.customers.create_customer(
                external_id=str(organization_id),
                name=name,
                email=email,
            )
    except Exception as exc:
        if _is_customer_already_exists(exc):
            return
        logger.warning(
            "Flexprice ensure_customer failed for org {}: {}",
            organization_id,
            exc,
        )


# --- Voice playground ---


def record_blind_test_share_created(
    organization_id: UUID,
    share_id: UUID,
    *,
    workspace_id: UUID,
    comparison_id: UUID,
) -> None:
    record_event(
        BLIND_TEST_SHARE_CREATED,
        organization_id,
        share_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "share_id": share_id,
            "comparison_id": comparison_id,
        },
    )


def record_blind_test_response_submitted(
    organization_id: UUID,
    response_id: UUID,
    *,
    share_id: UUID,
    workspace_id: UUID,
    response_count: int,
) -> None:
    record_event(
        BLIND_TEST_RESPONSE_SUBMITTED,
        organization_id,
        response_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "share_id": share_id,
            "response_count": response_count,
            "quantity": response_count,
        },
    )


def record_tts_generation_started(
    organization_id: UUID,
    comparison_id: UUID,
    *,
    workspace_id: UUID,
    sample_count: int,
) -> None:
    record_event(
        TTS_GENERATION_STARTED,
        organization_id,
        comparison_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "comparison_id": comparison_id,
            "sample_count": sample_count,
        },
    )


def record_tts_sample_synthesized(
    organization_id: UUID,
    sample_id: UUID,
    *,
    workspace_id: UUID,
    comparison_id: UUID,
    provider: Optional[str] = None,
    side: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    record_event(
        TTS_SAMPLE_SYNTHESIZED,
        organization_id,
        sample_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "comparison_id": comparison_id,
            "sample_id": sample_id,
            "provider": provider,
            "side": side,
            "duration_seconds": duration_seconds,
            "quantity": 1,
        },
    )


def record_tts_report_requested(
    organization_id: UUID,
    report_job_id: UUID,
    *,
    workspace_id: UUID,
    comparison_id: UUID,
) -> None:
    record_event(
        TTS_REPORT_REQUESTED,
        organization_id,
        report_job_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "comparison_id": comparison_id,
            "report_job_id": report_job_id,
        },
    )


def record_tts_report_completed(
    organization_id: UUID,
    report_job_id: UUID,
    *,
    workspace_id: UUID,
    comparison_id: UUID,
) -> None:
    record_event(
        TTS_REPORT_COMPLETED,
        organization_id,
        report_job_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_VOICE_PLAYGROUND,
            "comparison_id": comparison_id,
            "report_job_id": report_job_id,
        },
    )


# --- Call imports ---


def record_call_import_batch_created(
    organization_id: UUID,
    call_import_id: UUID,
    *,
    workspace_id: UUID,
    total_rows: int,
    source: str,
    provider: Optional[str] = None,
) -> None:
    record_event(
        CALL_IMPORT_BATCH_CREATED,
        organization_id,
        call_import_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_CALL_IMPORTS,
            "call_import_id": call_import_id,
            "total_rows": total_rows,
            "quantity": total_rows,
            "source": source,
            "provider": provider,
        },
    )


# --- Call imports (evaluations) ---


def record_call_import_evaluation_completed(
    organization_id: UUID,
    evaluation_id: UUID,
    *,
    workspace_id: UUID,
    call_import_id: UUID,
    rows_billed: int,
    completed_total: int,
    metric_count: int = 0,
) -> None:
    """Bill one pass of an evaluation run for newly completed rows."""
    record_event(
        CALL_IMPORT_EVALUATION_COMPLETED,
        organization_id,
        f"{evaluation_id}:{completed_total}",
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_CALL_IMPORTS,
            "call_import_id": call_import_id,
            "evaluation_id": evaluation_id,
            "rows_billed": rows_billed,
            "completed_total": completed_total,
            "metric_count": metric_count,
            "quantity": rows_billed,
        },
    )


# --- Agent playground ---


def record_playground_web_call_started(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    agent_id: UUID,
) -> None:
    record_event(
        PLAYGROUND_WEB_CALL_STARTED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "call_short_id": call_short_id,
        },
    )


def record_playground_websocket_session_started(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
) -> None:
    record_event(
        PLAYGROUND_WEBSOCKET_SESSION_STARTED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "call_short_id": call_short_id,
        },
    )


def record_playground_call_evaluated(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    metric_count: int,
) -> None:
    record_event(
        PLAYGROUND_CALL_EVALUATED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "call_short_id": call_short_id,
            "metric_count": metric_count,
        },
    )


def record_playground_evaluation_completed(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    duration_seconds: Optional[float] = None,
) -> None:
    record_event(
        PLAYGROUND_EVALUATION_COMPLETED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "call_short_id": call_short_id,
            "duration_seconds": duration_seconds,
        },
    )


# --- Evaluators ---


def record_evaluator_run_requested(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: UUID,
    quantity: int,
) -> None:
    record_event(
        EVALUATOR_RUN_REQUESTED,
        organization_id,
        request_id,
        properties={
            "workspace_id": workspace_id,
            "quantity": quantity,
        },
    )


def record_evaluator_run_completed(
    organization_id: UUID,
    result_id: str,
    *,
    workspace_id: UUID,
    evaluator_id: UUID,
    call_count: int = 1,
) -> None:
    record_event(
        EVALUATOR_RUN_COMPLETED,
        organization_id,
        result_id,
        properties={
            "workspace_id": workspace_id,
            "evaluator_id": evaluator_id,
            "result_id": result_id,
            "call_count": call_count,
        },
    )


# --- Legacy evaluations ---


def record_evaluation_created(
    organization_id: UUID,
    evaluation_id: UUID,
    *,
    workspace_id: UUID,
    audio_id: UUID,
    metrics_requested: int,
) -> None:
    record_event(
        EVALUATION_CREATED,
        organization_id,
        evaluation_id,
        properties={
            "workspace_id": workspace_id,
            "audio_id": audio_id,
            "metrics_requested": metrics_requested,
        },
    )


def record_evaluation_completed(
    organization_id: UUID,
    evaluation_id: UUID,
    *,
    workspace_id: UUID,
) -> None:
    record_event(
        EVALUATION_COMPLETED,
        organization_id,
        evaluation_id,
        properties={"workspace_id": workspace_id},
    )


# --- Prompt optimization ---


def record_prompt_optimization_run_started(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    max_metric_calls: Optional[int] = None,
) -> None:
    record_event(
        PROMPT_OPTIMIZATION_RUN_STARTED,
        organization_id,
        run_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_GEPA,
            "run_id": run_id,
            "agent_id": agent_id,
            "max_metric_calls": max_metric_calls,
        },
    )


def record_prompt_optimization_run_completed(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    candidates_count: int = 0,
) -> None:
    record_event(
        PROMPT_OPTIMIZATION_RUN_COMPLETED,
        organization_id,
        run_id,
        properties={
            "workspace_id": workspace_id,
            "feature": FEATURE_GEPA,
            "run_id": run_id,
            "agent_id": agent_id,
            "candidates_count": candidates_count,
        },
    )


# --- Judge alignment ---


def record_judge_alignment_run_started(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
    sample_count: int,
) -> None:
    record_event(
        JUDGE_ALIGNMENT_RUN_STARTED,
        organization_id,
        run_id,
        properties={
            "workspace_id": workspace_id,
            "run_id": run_id,
            "dataset_id": dataset_id,
            "sample_count": sample_count,
        },
    )


def record_judge_alignment_run_completed(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
    samples_scored: int,
) -> None:
    record_event(
        JUDGE_ALIGNMENT_RUN_COMPLETED,
        organization_id,
        run_id,
        properties={
            "workspace_id": workspace_id,
            "run_id": run_id,
            "dataset_id": dataset_id,
            "samples_scored": samples_scored,
        },
    )


# --- Observability ---


def record_observability_call_ingested(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    provider: Optional[str] = None,
) -> None:
    record_event(
        OBSERVABILITY_CALL_INGESTED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "call_short_id": call_short_id,
            "provider": provider,
        },
    )


def record_observability_call_evaluated(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
) -> None:
    record_event(
        OBSERVABILITY_CALL_EVALUATED,
        organization_id,
        call_short_id,
        properties={
            "workspace_id": workspace_id,
            "call_short_id": call_short_id,
        },
    )


# --- Test agents ---


def record_test_agent_conversation_started(
    organization_id: UUID,
    conversation_id: UUID,
    *,
    workspace_id: UUID,
) -> None:
    record_event(
        TEST_AGENT_CONVERSATION_STARTED,
        organization_id,
        conversation_id,
        properties={
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
        },
    )


def record_test_agent_conversation_ended(
    organization_id: UUID,
    conversation_id: UUID,
    *,
    workspace_id: UUID,
    duration_seconds: Optional[float] = None,
    turn_count: int = 0,
) -> None:
    record_event(
        TEST_AGENT_CONVERSATION_ENDED,
        organization_id,
        conversation_id,
        properties={
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "duration_seconds": duration_seconds,
            "turn_count": turn_count,
            "quantity": duration_seconds or 1,
        },
    )


# --- LLM assist ---


def record_metrics_llm_assist(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    mode: str,
) -> None:
    record_event(
        METRICS_LLM_ASSIST,
        organization_id,
        request_id,
        properties={
            "workspace_id": workspace_id,
            "mode": mode,
        },
    )


def record_chat_completion(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    model: Optional[str] = None,
) -> None:
    record_event(
        CHAT_COMPLETION,
        organization_id,
        request_id,
        properties={
            "workspace_id": workspace_id,
            "model": model,
            "quantity": 1,
        },
    )
