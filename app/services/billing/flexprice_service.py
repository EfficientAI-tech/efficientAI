"""Flexprice usage metering (optional; no-op when disabled).

Event naming: ``product.action`` snake_case (e.g. ``call_import.batch_created``).
Every event uses ``external_customer_id=str(organization.id)`` and a stable
``event_id`` for idempotency. ``properties`` should include ``workspace_id`` and
``feature`` (license key) when the surface is gated.

Ingest **only when value is delivered** (completed), never on ``*_started`` /
``*_created`` / ``*_requested``. Event ``properties`` include billable fields
(``workspace_id``, ``feature``, ``quantity``, ``billable_minutes``) plus audit
IDs (``evaluation_id``, ``audio_seconds``, etc.) for support — audit fields are
not used for Flexprice SUM/COUNT aggregation.

Billable events (wire plan usage charges to these meters only):

- call_imports: ``call_import.batch_created`` (``quantity`` = rows imported),
  ``call_import.evaluation_completed`` (``quantity`` = newly completed rows),
  ``call_import.recording_minutes_billed`` (``quantity`` = ``billable_minutes``),
  ``call_import.pdf_report_generated`` (``quantity`` = 1)
- agent_playground: ``playground.evaluation_completed`` (``quantity`` = ``billable_minutes``
  from call duration) **or** ``test_agent.conversation_ended`` (same minute rollup for
  standalone test-agent sessions without playground eval) — never both for the same session
- voice_playground: ``tts.sample_synthesized``, ``tts.report_completed``,
  ``blind_test.response_submitted``
- evaluators: ``evaluator.run_completed`` (``quantity`` = 1) and
  ``evaluator.recording_minutes_billed`` when the run has audio (``billable_minutes``)
- gepa_optimization: ``prompt_optimization.run_completed`` (``quantity`` = candidates)
- judge_alignment: ``judge_alignment.run_completed`` (``quantity`` = samples scored)
- metrics_ai_assist: ``metrics.ai_assist``
- metric_studio: ``metric_studio.run_completed`` (``quantity`` = completed items)
- scenario_ai: ``scenario.ai_text_generated``

Not ingested: ``*_started``, ``*_requested``, ``*_created``, ``observability.*``,
``playground.call_evaluated``, ``test_agent.conversation_started``,
``metric_studio.item_evaluated``, etc.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Union
from uuid import UUID

from loguru import logger

from app.config import settings

EVENT_SOURCE = "efficientai"
FEATURE_CALL_IMPORTS = "call_imports"
FEATURE_AGENT_PLAYGROUND = "agent_playground"
FEATURE_VOICE_PLAYGROUND = "voice_playground"
FEATURE_GEPA = "gepa_optimization"
FEATURE_EVALUATORS = "evaluators"
FEATURE_JUDGE_ALIGNMENT = "judge_alignment"
FEATURE_METRICS_AI_ASSIST = "metrics_ai_assist"
FEATURE_METRIC_STUDIO = "metric_studio"
FEATURE_SCENARIO_AI = "scenario_ai"

# Log once when metering is inactive so AWS/worker misconfig is obvious.
_disabled_skip_logged = False

# Event names
BLIND_TEST_SHARE_CREATED = "blind_test.share_created"
BLIND_TEST_RESPONSE_SUBMITTED = "blind_test.response_submitted"
TTS_GENERATION_STARTED = "tts.generation_started"
TTS_SAMPLE_SYNTHESIZED = "tts.sample_synthesized"
TTS_REPORT_REQUESTED = "tts.report_requested"
TTS_REPORT_COMPLETED = "tts.report_completed"
CALL_IMPORT_BATCH_CREATED = "call_import.batch_created"
CALL_IMPORT_EVALUATION_STARTED = "call_import.evaluation_started"
CALL_IMPORT_EVALUATION_COMPLETED = "call_import.evaluation_completed"
CALL_IMPORT_RECORDING_MINUTES_BILLED = "call_import.recording_minutes_billed"
CALL_IMPORT_AUDIO_MINUTES_BILLED = CALL_IMPORT_RECORDING_MINUTES_BILLED
CALL_IMPORT_PDF_REPORT_GENERATED = "call_import.pdf_report_generated"
PLAYGROUND_WEB_CALL_STARTED = "playground.web_call_started"
PLAYGROUND_WEBSOCKET_SESSION_STARTED = "playground.websocket_session_started"
PLAYGROUND_CALL_EVALUATED = "playground.call_evaluated"
PLAYGROUND_EVALUATION_COMPLETED = "playground.evaluation_completed"
EVALUATOR_RUN_REQUESTED = "evaluator.run_requested"
EVALUATOR_RUN_COMPLETED = "evaluator.run_completed"
EVALUATOR_RECORDING_MINUTES_BILLED = "evaluator.recording_minutes_billed"
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
METRICS_AI_ASSIST = "metrics.ai_assist"
METRIC_STUDIO_ITEM_EVALUATED = "metric_studio.item_evaluated"
METRIC_STUDIO_RUN_COMPLETED = "metric_studio.run_completed"
SCENARIO_AI_TEXT_GENERATED = "scenario.ai_text_generated"
# Legacy aliases (Flexprice meters may still exist under old names)
METRICS_LLM_ASSIST = METRICS_AI_ASSIST
CHAT_COMPLETION = SCENARIO_AI_TEXT_GENERATED


def _verbose_logging() -> bool:
    """Extra per-event logs when FLEXPRICE_VERBOSE=1 (useful on AWS)."""
    return os.getenv("FLEXPRICE_VERBOSE", "").lower() in {"1", "true", "yes"}


def _pytest_blocks_external_billing() -> bool:
    """Block real Flexprice I/O during pytest unless explicitly opted in."""
    return (
        os.environ.get("EFFICIENTAI_PYTEST") == "1"
        and os.environ.get("FLEXPRICE_TEST_ALLOW") != "1"
    )


def _mask_api_key(api_key: Optional[str]) -> str:
    if not api_key:
        return "(missing)"
    if len(api_key) <= 8:
        return "****"
    return f"****{api_key[-4:]}"


def disabled_reason() -> Optional[str]:
    """Human-readable reason metering is off, or None when active."""
    if not settings.FLEXPRICE_ENABLED:
        return "flexprice.enabled is false (or FLEXPRICE_ENABLED unset)"
    if not settings.FLEXPRICE_API_KEY:
        return "flexprice.api_key is unset (or FLEXPRICE_API_KEY env missing)"
    return None


def is_enabled() -> bool:
    """Return True only when Flexprice is explicitly enabled with an API key."""
    return disabled_reason() is None


def log_startup_status(*, component: str = "app") -> None:
    """Log Flexprice config at process start (API + Celery worker)."""
    reason = disabled_reason()
    if reason:
        logger.info(
            "Flexprice metering INACTIVE for {} — {} (api_host={})",
            component,
            reason,
            settings.FLEXPRICE_API_HOST,
        )
        return

    logger.info(
        "Flexprice metering ACTIVE for {} — api_host={} api_key={}",
        component,
        settings.FLEXPRICE_API_HOST,
        _mask_api_key(settings.FLEXPRICE_API_KEY),
    )

    connectivity_error = _verify_connectivity()
    if connectivity_error:
        logger.warning(
            "Flexprice connectivity check FAILED for {} — host={} error={}. "
            "Config looks valid but outbound calls may be blocked (check AWS egress/NAT/SG).",
            component,
            settings.FLEXPRICE_API_HOST,
            connectivity_error,
        )
    else:
        logger.info(
            "Flexprice connectivity check OK for {} — host={}",
            component,
            settings.FLEXPRICE_API_HOST,
        )


def _verify_connectivity() -> Optional[str]:
    """Best-effort reachability probe; returns error text or None when OK."""
    if _pytest_blocks_external_billing():
        return None
    try:
        import httpx

        base = settings.FLEXPRICE_API_HOST.rstrip("/")
        response = httpx.get(
            f"{base}/customers",
            headers={"x-api-key": settings.FLEXPRICE_API_KEY or ""},
            params={"limit": 1},
            timeout=10.0,
        )
        if response.status_code < 400:
            return None
        return f"HTTP {response.status_code}: {response.text[:200]}"
    except Exception as exc:
        return str(exc)


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


def _billable_minutes(duration_seconds: Optional[float]) -> int:
    if duration_seconds is None:
        return 1
    seconds = float(duration_seconds)
    if seconds <= 0:
        return 1
    import math

    return max(1, int(math.ceil(seconds / 60.0)))


def _billing_properties(
    workspace_id: UUID,
    feature: str,
    *,
    quantity: Optional[Union[int, float]] = None,
    billable_minutes: Optional[int] = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {"workspace_id": workspace_id, "feature": feature}
    if quantity is not None:
        props["quantity"] = quantity
    if billable_minutes is not None:
        props["billable_minutes"] = billable_minutes
    return props


def _event_properties(
    workspace_id: UUID,
    feature: str,
    *,
    quantity: Optional[Union[int, float]] = None,
    billable_minutes: Optional[int] = None,
    **audit: Any,
) -> dict[str, Any]:
    """Billable fields plus optional audit metadata for support traceability."""
    props = _billing_properties(
        workspace_id,
        feature,
        quantity=quantity,
        billable_minutes=billable_minutes,
    )
    for key, value in audit.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        props[key] = value
    return props


def record_event(
    event_name: str,
    organization_id: UUID,
    event_id: Union[str, UUID],
    *,
    properties: Optional[dict[str, Any]] = None,
) -> bool:
    """Ingest a usage event. No-op when Flexprice is disabled; never raises.

    Returns ``True`` when Flexprice accepted the event, ``False`` when metering
    is inactive or ingest failed (callers can retry billing later).
    """
    global _disabled_skip_logged

    if _pytest_blocks_external_billing():
        return False

    inactive_reason = disabled_reason()
    if inactive_reason:
        if not _disabled_skip_logged:
            logger.warning(
                "Flexprice metering inactive — {}. Usage events will be dropped until fixed.",
                inactive_reason,
            )
            _disabled_skip_logged = True
        if _verbose_logging():
            logger.info(
                "Flexprice SKIP {} org={} event_id={} ({})",
                event_name,
                organization_id,
                event_id,
                inactive_reason,
            )
        return False

    coerced = _coerce_properties(properties)
    quantity = coerced.get("quantity")

    try:
        from flexprice import Flexprice

        with Flexprice(
            server_url=settings.FLEXPRICE_API_HOST,
            api_key_auth=settings.FLEXPRICE_API_KEY,
        ) as client:
            payload = {
                "event_name": event_name,
                "external_customer_id": str(organization_id),
                "event_id": str(event_id),
                "source": EVENT_SOURCE,
                "properties": coerced,
            }
            _ingest_usage_event(client, payload)

        logger.info(
            "Flexprice ingested {} org={} event_id={} quantity={}",
            event_name,
            organization_id,
            event_id,
            quantity if quantity is not None else "n/a",
        )
        return True
    except Exception as exc:
        logger.warning(
            "Flexprice {} ingest FAILED org={} event_id={} host={} error={}",
            event_name,
            organization_id,
            event_id,
            settings.FLEXPRICE_API_HOST,
            exc,
        )
        return False


def ensure_customer(
    organization_id: UUID,
    *,
    name: str,
    email: Optional[str] = None,
) -> None:
    """Register an organization as a Flexprice customer. No-op when disabled."""
    if _pytest_blocks_external_billing():
        return

    inactive_reason = disabled_reason()
    if inactive_reason:
        if _verbose_logging():
            logger.info(
                "Flexprice SKIP ensure_customer org={} ({})",
                organization_id,
                inactive_reason,
            )
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
        logger.info(
            "Flexprice ensure_customer ok org={} name={}",
            organization_id,
            name,
        )
    except Exception as exc:
        if _is_customer_already_exists(exc):
            logger.debug(
                "Flexprice ensure_customer already exists org={}",
                organization_id,
            )
            return
        logger.warning(
            "Flexprice ensure_customer FAILED org={} host={} error={}",
            organization_id,
            settings.FLEXPRICE_API_HOST,
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
    """Not ingested — bill on blind_test.response_submitted instead."""


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
        properties=_event_properties(
            workspace_id,
            FEATURE_VOICE_PLAYGROUND,
            quantity=max(1, response_count),
            share_id=share_id,
            response_id=response_id,
        ),
    )


def record_tts_generation_started(
    organization_id: UUID,
    comparison_id: UUID,
    *,
    workspace_id: UUID,
    sample_count: int,
) -> None:
    """Not ingested — bill on tts.sample_synthesized per completed sample."""


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
        properties=_event_properties(
            workspace_id,
            FEATURE_VOICE_PLAYGROUND,
            quantity=1,
            comparison_id=comparison_id,
            sample_id=sample_id,
            provider=provider,
            side=side,
            duration_seconds=duration_seconds,
        ),
    )


def record_tts_report_requested(
    organization_id: UUID,
    report_job_id: UUID,
    *,
    workspace_id: UUID,
    comparison_id: UUID,
) -> None:
    """Not ingested — bill on tts.report_completed."""


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
        properties=_event_properties(
            workspace_id,
            FEATURE_VOICE_PLAYGROUND,
            quantity=1,
            comparison_id=comparison_id,
            report_job_id=report_job_id,
        ),
    )


# --- Call imports (tracking complete: batch, eval lifecycle, audio minutes, PDF) ---


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
        properties=_event_properties(
            workspace_id,
            FEATURE_CALL_IMPORTS,
            quantity=max(0, total_rows),
            call_import_id=call_import_id,
            source=source,
            provider=provider,
            total_rows=total_rows,
        ),
    )


# --- Call imports (evaluations) ---


def record_call_import_evaluation_started(
    organization_id: UUID,
    evaluation_id: UUID,
    *,
    workspace_id: UUID,
    call_import_id: UUID,
    total_rows: int,
    metric_count: int = 0,
) -> None:
    """Not ingested — bill on call_import.evaluation_completed."""


def record_call_import_evaluation_completed(
    organization_id: UUID,
    evaluation_id: UUID,
    *,
    workspace_id: UUID,
    call_import_id: UUID,
    rows_billed: int,
    completed_total: int,
    total_rows: int = 0,
    metric_count: int = 0,
) -> bool:
    """Bill one finished evaluation pass for newly completed rows (not per row)."""
    if rows_billed <= 0:
        return False
    return record_event(
        CALL_IMPORT_EVALUATION_COMPLETED,
        organization_id,
        f"{evaluation_id}:{completed_total}",
        properties=_event_properties(
            workspace_id,
            FEATURE_CALL_IMPORTS,
            quantity=rows_billed,
            evaluation_id=evaluation_id,
            call_import_id=call_import_id,
            completed_total=completed_total,
            total_rows=total_rows,
            metric_count=metric_count,
            rows_billed=rows_billed,
        ),
    )


def record_call_import_recording_minutes_billed(
    organization_id: UUID,
    evaluation_row_id: UUID,
    *,
    workspace_id: UUID,
    evaluation_id: UUID,
    call_import_id: UUID,
    audio_seconds: int,
    billable_minutes: int,
) -> bool:
    """Bill recording duration for one successfully evaluated call-import row."""
    if billable_minutes <= 0:
        return False
    return record_event(
        CALL_IMPORT_RECORDING_MINUTES_BILLED,
        organization_id,
        evaluation_row_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_CALL_IMPORTS,
            quantity=billable_minutes,
            billable_minutes=billable_minutes,
            evaluation_row_id=evaluation_row_id,
            evaluation_id=evaluation_id,
            call_import_id=call_import_id,
            audio_seconds=audio_seconds,
        ),
    )


def record_call_import_audio_minutes_billed(
    organization_id: UUID,
    evaluation_row_id: UUID,
    *,
    workspace_id: UUID,
    evaluation_id: UUID,
    call_import_id: UUID,
    audio_seconds: int,
    billable_minutes: int,
) -> bool:
    return record_call_import_recording_minutes_billed(
        organization_id,
        evaluation_row_id,
        workspace_id=workspace_id,
        evaluation_id=evaluation_id,
        call_import_id=call_import_id,
        audio_seconds=audio_seconds,
        billable_minutes=billable_minutes,
    )


def record_call_import_pdf_report_generated(
    organization_id: UUID,
    pdf_report_id: UUID,
    *,
    workspace_id: UUID,
    evaluation_id: UUID,
    call_import_id: UUID,
    report_type: str,
) -> None:
    record_event(
        CALL_IMPORT_PDF_REPORT_GENERATED,
        organization_id,
        pdf_report_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_CALL_IMPORTS,
            quantity=1,
            pdf_report_id=pdf_report_id,
            evaluation_id=evaluation_id,
            call_import_id=call_import_id,
            report_type=report_type,
        ),
    )


# --- Agent playground ---


def record_playground_web_call_started(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    agent_id: UUID,
) -> None:
    """Not ingested — bill on playground.evaluation_completed."""


def record_playground_websocket_session_started(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
) -> None:
    """Not ingested — bill on playground.evaluation_completed."""


def record_playground_call_evaluated(
    organization_id: UUID,
    evaluation_attempt_id: Union[str, UUID],
    *,
    evaluator_result_id: UUID,
    workspace_id: UUID,
    call_short_id: str,
    metric_count: int,
) -> None:
    """Not ingested — bill on playground.evaluation_completed."""


def record_playground_evaluation_completed(
    organization_id: UUID,
    evaluation_attempt_id: Union[str, UUID],
    *,
    evaluator_result_id: UUID,
    workspace_id: UUID,
    call_short_id: str,
    duration_seconds: Optional[float] = None,
    metric_count: int = 0,
) -> None:
    minutes = _billable_minutes(duration_seconds)
    record_event(
        PLAYGROUND_EVALUATION_COMPLETED,
        organization_id,
        evaluation_attempt_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_AGENT_PLAYGROUND,
            quantity=minutes,
            billable_minutes=minutes,
            evaluator_result_id=evaluator_result_id,
            call_short_id=call_short_id,
            duration_seconds=duration_seconds,
            metric_count=metric_count,
        ),
    )


# --- Evaluators ---


def record_evaluator_run_requested(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: UUID,
    quantity: int,
) -> None:
    """Not ingested — bill on evaluator.run_completed when scoring finishes."""
    del organization_id, request_id, workspace_id, quantity


def record_evaluator_run_completed(
    organization_id: UUID,
    result_id: str,
    *,
    workspace_id: UUID,
    evaluator_id: Optional[UUID] = None,
    evaluator_result_id: Optional[UUID] = None,
    call_count: int = 1,
) -> None:
    del call_count
    record_event(
        EVALUATOR_RUN_COMPLETED,
        organization_id,
        result_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_EVALUATORS,
            quantity=1,
            result_id=result_id,
            evaluator_id=evaluator_id,
            evaluator_result_id=evaluator_result_id,
        ),
    )


def record_evaluator_recording_minutes_billed(
    organization_id: UUID,
    evaluator_result_id: UUID,
    *,
    workspace_id: UUID,
    duration_seconds: Optional[float] = None,
) -> bool:
    """Bill audio duration for a completed evaluator run that includes a recording."""
    minutes = _billable_minutes(duration_seconds)
    if minutes <= 0:
        return False
    return record_event(
        EVALUATOR_RECORDING_MINUTES_BILLED,
        organization_id,
        evaluator_result_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_EVALUATORS,
            quantity=minutes,
            billable_minutes=minutes,
            evaluator_result_id=evaluator_result_id,
            duration_seconds=duration_seconds,
            audio_seconds=int(round(float(duration_seconds)))
            if duration_seconds is not None
            else None,
        ),
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
    """Not ingested — bill on evaluation.completed."""
    del organization_id, evaluation_id, workspace_id, audio_id, metrics_requested


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
        properties=_event_properties(
            workspace_id,
            FEATURE_EVALUATORS,
            quantity=1,
            evaluation_id=evaluation_id,
        ),
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
    """Not ingested — bill on prompt_optimization.run_completed."""
    del organization_id, run_id, workspace_id, agent_id, max_metric_calls


def record_prompt_optimization_run_completed(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    candidates_count: int = 0,
) -> None:
    billed = max(1, candidates_count)
    record_event(
        PROMPT_OPTIMIZATION_RUN_COMPLETED,
        organization_id,
        run_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_GEPA,
            quantity=billed,
            run_id=run_id,
            agent_id=agent_id,
            candidates_count=candidates_count,
        ),
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
    """Not ingested — bill on judge_alignment.run_completed."""
    del organization_id, run_id, workspace_id, dataset_id, sample_count


def record_judge_alignment_run_completed(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    dataset_id: UUID,
    samples_scored: int,
) -> None:
    billed = max(0, samples_scored)
    if billed <= 0:
        return
    record_event(
        JUDGE_ALIGNMENT_RUN_COMPLETED,
        organization_id,
        run_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_JUDGE_ALIGNMENT,
            quantity=billed,
            run_id=run_id,
            dataset_id=dataset_id,
            samples_scored=samples_scored,
        ),
    )


# --- Observability ---


def record_observability_call_ingested(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
    provider: Optional[str] = None,
) -> None:
    """Not ingested — bill on observability.call_evaluated."""
    del organization_id, call_short_id, workspace_id, provider


def record_observability_call_evaluated(
    organization_id: UUID,
    call_short_id: str,
    *,
    workspace_id: UUID,
) -> None:
    """Not ingested — observability is not a billable product surface."""
    del organization_id, call_short_id, workspace_id


# --- Test agents ---


def record_test_agent_conversation_started(
    organization_id: UUID,
    conversation_id: Union[str, UUID],
    *,
    workspace_id: UUID,
    result_id: Optional[str] = None,
    agent_id: Optional[UUID] = None,
    call_short_id: Optional[str] = None,
) -> None:
    """Not ingested — bill on test_agent.conversation_ended."""
    del organization_id, conversation_id, workspace_id, result_id, agent_id, call_short_id


def record_test_agent_conversation_ended(
    organization_id: UUID,
    conversation_id: Union[str, UUID],
    *,
    workspace_id: UUID,
    duration_seconds: Optional[float] = None,
    turn_count: int = 0,
    result_id: Optional[str] = None,
    agent_id: Optional[UUID] = None,
    call_short_id: Optional[str] = None,
) -> None:
    minutes = _billable_minutes(duration_seconds)
    record_event(
        TEST_AGENT_CONVERSATION_ENDED,
        organization_id,
        conversation_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_AGENT_PLAYGROUND,
            quantity=minutes,
            billable_minutes=minutes,
            conversation_id=conversation_id,
            duration_seconds=duration_seconds,
            turn_count=turn_count,
            result_id=result_id,
            agent_id=agent_id,
            call_short_id=call_short_id,
        ),
    )


# --- Metrics AI assist (metric builder) ---


def record_metrics_ai_assist(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    mode: str,
) -> None:
    if workspace_id is None:
        return
    record_event(
        METRICS_AI_ASSIST,
        organization_id,
        request_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_METRICS_AI_ASSIST,
            quantity=1,
            request_id=request_id,
            mode=mode,
        ),
    )


def record_metrics_llm_assist(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    mode: str,
) -> None:
    record_metrics_ai_assist(
        organization_id,
        request_id,
        workspace_id=workspace_id,
        mode=mode,
    )


# --- Metric Studio ---


def record_metric_studio_item_evaluated(
    organization_id: UUID,
    result_row_id: UUID,
    *,
    workspace_id: UUID,
    run_id: UUID,
    source_kind: str,
    source_ref: str,
    metric_count: int = 0,
) -> None:
    """Not ingested — bill on metric_studio.run_completed."""
    del (
        organization_id,
        result_row_id,
        workspace_id,
        run_id,
        source_kind,
        source_ref,
        metric_count,
    )


def record_metric_studio_run_completed(
    organization_id: UUID,
    run_id: UUID,
    *,
    workspace_id: UUID,
    run_status: str,
    total_items: int,
    completed_items: int,
    failed_items: int,
) -> None:
    del run_status
    billed = max(0, completed_items)
    if billed <= 0:
        return
    record_event(
        METRIC_STUDIO_RUN_COMPLETED,
        organization_id,
        run_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_METRIC_STUDIO,
            quantity=billed,
            run_id=run_id,
            total_items=total_items,
            completed_items=completed_items,
            failed_items=failed_items,
        ),
    )


# --- Scenario / assistant AI text ---


def record_scenario_ai_text_generated(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    model: Optional[str] = None,
    purpose: str = "scenario_description",
    scenario_count: Optional[int] = None,
) -> None:
    if workspace_id is None:
        return
    record_event(
        SCENARIO_AI_TEXT_GENERATED,
        organization_id,
        request_id,
        properties=_event_properties(
            workspace_id,
            FEATURE_SCENARIO_AI,
            quantity=1,
            request_id=request_id,
            model=model,
            purpose=purpose,
            scenario_count=scenario_count,
        ),
    )


def record_chat_completion(
    organization_id: UUID,
    request_id: UUID,
    *,
    workspace_id: Optional[UUID],
    model: Optional[str] = None,
    purpose: str = "scenario_description",
    scenario_count: Optional[int] = None,
) -> None:
    record_scenario_ai_text_generated(
        organization_id,
        request_id,
        workspace_id=workspace_id,
        model=model,
        purpose=purpose,
        scenario_count=scenario_count,
    )
