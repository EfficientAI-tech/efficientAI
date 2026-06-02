"""Map-reduce LLM pipeline for call-import evaluation user insights."""

from __future__ import annotations

import json
import math
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    ModelProvider,
)
from app.models.schemas import (
    EvaluationUserInsightItem,
    EvaluationUserInsightsState,
    UserInsightCategory,
    UserInsightEvidence,
    UserInsightEvidenceTurn,
)
from app.services.ai.llm_service import llm_service

MAX_LLM_CALLS_DEFAULT = 200
MAX_LLM_CALLS_MIN = 20
MAX_LLM_CALLS_MAX = 500
SYNTHESIS_CALLS = 1
ROW_TRANSCRIPT_CHAR_CAP = 3000
RATIONALE_CHAR_CAP = 600
EXTRACTION_MAX_TOKENS = 1800
SYNTHESIS_MAX_TOKENS = 2400

ProgressCallback = Callable[[int, int], None]


def normalize_max_llm_calls(value: Optional[int]) -> int:
    """Clamp user-selected sample size to a safe LLM-call budget."""
    if value is None:
        return MAX_LLM_CALLS_DEFAULT
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return MAX_LLM_CALLS_DEFAULT
    return max(MAX_LLM_CALLS_MIN, min(parsed, MAX_LLM_CALLS_MAX))


def max_extraction_calls(max_llm_calls: Optional[int] = None) -> int:
    return normalize_max_llm_calls(max_llm_calls) - SYNTHESIS_CALLS


def compute_extraction_plan(
    n_rows: int,
    *,
    max_llm_calls: Optional[int] = None,
) -> Tuple[int, int]:
    """Return ``(batch_size, num_extraction_calls)`` for *n_rows* completed rows."""
    if n_rows <= 0:
        return 1, 0
    extraction_cap = max_extraction_calls(max_llm_calls)
    batch_size = max(1, math.ceil(n_rows / extraction_cap))
    num_batches = min(math.ceil(n_rows / batch_size), extraction_cap)
    return batch_size, num_batches


def total_llm_calls_for_rows(
    n_rows: int,
    *,
    max_llm_calls: Optional[int] = None,
) -> int:
    """Total LLM calls (extraction + synthesis) for *n_rows*."""
    _, extraction = compute_extraction_plan(n_rows, max_llm_calls=max_llm_calls)
    return extraction + (SYNTHESIS_CALLS if n_rows > 0 else 0)


_EXTRACTION_SYSTEM_PROMPT = (
    "You are a senior conversation-analytics reviewer. You will receive a "
    "batch of call transcripts with per-metric LLM rationales from a "
    "quality evaluation run. Identify user-behavior and caller-context "
    "patterns that hold within each call and across the batch.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "rows": [\n'
    "    {\n"
    '      "conversation_id": "<id>",\n'
    '      "themes": ["<short theme label>", ...],\n'
    '      "quote": "<verbatim transcript snippet, <=300 chars>",\n'
    '      "turns": [{"speaker": "User|Bot", "text": "..."}]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Constraints:\n"
    "- themes: 1-4 concise labels per row (e.g. 'First-time caller', "
    "'Status check on prior ticket').\n"
    "- quote and turns must be verbatim from the supplied transcript.\n"
    "- Use neutral, vendor-safe language.\n"
    "- No markdown, no preamble."
)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You are writing user-insight blocks for an external call quality "
    "audit report. You will receive aggregated theme frequencies from "
    "sampled calls plus metric aggregate statistics.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "overview": "<2-4 sentence high-level analysis synthesizing all insight blocks>",\n'
    '  "insights": [\n'
    "    {\n"
    '      "title": "<insight title, e.g. Caller Context Distribution>",\n'
    '      "categories": [{"label": "...", "count": N, "share_pct": P}],\n'
    '      "observation": "<1-2 sentence synthesis>",\n'
    '      "evidence": {\n'
    '        "conversation_id": "...",\n'
    '        "quote": "...",\n'
    '        "turns": [{"speaker": "User|Bot", "text": "..."}]\n'
    "      }\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Constraints:\n"
    "- Produce 3 to 8 insight blocks.\n"
    "- overview must synthesize cross-cutting patterns across ALL insight blocks.\n"
    "- Each block groups related themes into categorical distributions.\n"
    "- category share_pct values must sum to ~100 within each insight.\n"
    "- counts should reflect the supplied theme frequencies.\n"
    "- evidence must cite a real conversation_id and verbatim quote from "
    "the samples.\n"
    "- Vendor-safe, factual language only.\n"
    "- No markdown, no preamble."
)


def _pick_transcript(
    evaluation: CallImportEvaluation,
    source_row: CallImportRow,
) -> str:
    production = (source_row.transcript or "").strip()
    diarised = (source_row.diarised_transcript or "").strip()
    raw_source = (evaluation.transcript_source or "").strip().lower()
    if raw_source:
        transcript_source = raw_source
    elif diarised:
        transcript_source = "diarised"
    else:
        transcript_source = "production"
    if transcript_source == "diarised":
        text = diarised or production
    else:
        text = production or diarised
    return text[:ROW_TRANSCRIPT_CHAR_CAP]


def _metric_name_map(metrics: Sequence[Metric]) -> Dict[str, str]:
    return {str(metric.id): metric.name for metric in metrics}


def build_row_payload(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    metric_names: Dict[str, str],
) -> Dict[str, Any]:
    """Compact per-row payload for extraction prompts."""
    scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
    metric_entries: List[Dict[str, str]] = []
    for metric_id, entry in scores.items():
        if not isinstance(entry, dict):
            continue
        name = metric_names.get(str(metric_id), str(metric_id))
        value = entry.get("value")
        rationale = entry.get("rationale")
        item: Dict[str, str] = {"metric": name}
        if value is not None:
            item["value"] = str(value)[:200]
        if isinstance(rationale, str) and rationale.strip():
            item["rationale"] = rationale.strip()[:RATIONALE_CHAR_CAP]
        if len(item) > 1:
            metric_entries.append(item)

    return {
        "conversation_id": source_row.conversation_id or str(source_row.id),
        "row_index": source_row.row_index,
        "transcript": _pick_transcript(evaluation, source_row),
        "metrics": metric_entries,
    }


def _batch_rows(
    rows: Sequence[Dict[str, Any]],
    batch_size: int,
) -> List[List[Dict[str, Any]]]:
    return [list(rows[i : i + batch_size]) for i in range(0, len(rows), batch_size)]


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return {}


def _call_llm(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    messages: List[Dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    result = llm_service.generate_response(
        messages=messages,
        llm_provider=provider,
        llm_model=model,
        organization_id=organization_id,
        db=db,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return str(result.get("text") or "")


def run_extraction_batch(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    batch: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract per-row themes and quotes from one batch."""
    if not batch:
        return []
    user_content = json.dumps({"calls": list(batch)}, ensure_ascii=False, default=str)
    text = _call_llm(
        db,
        organization_id,
        provider,
        model,
        [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=EXTRACTION_MAX_TOKENS,
    )
    parsed = _parse_json_object(text)
    rows_raw = parsed.get("rows")
    if not isinstance(rows_raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        conversation_id = str(item.get("conversation_id") or "").strip()
        themes_raw = item.get("themes")
        themes = (
            [str(t).strip() for t in themes_raw if str(t).strip()]
            if isinstance(themes_raw, list)
            else []
        )
        quote = str(item.get("quote") or "").strip()
        turns_raw = item.get("turns")
        turns: List[Dict[str, str]] = []
        if isinstance(turns_raw, list):
            for turn in turns_raw:
                if isinstance(turn, dict):
                    speaker = str(turn.get("speaker") or "User").strip()
                    turn_text = str(turn.get("text") or "").strip()
                    if turn_text:
                        turns.append({"speaker": speaker, "text": turn_text})
        if conversation_id and (themes or quote):
            out.append(
                {
                    "conversation_id": conversation_id,
                    "themes": themes,
                    "quote": quote[:500],
                    "turns": turns,
                }
            )
    return out


def _aggregate_themes(extractions: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in extractions:
        for theme in row.get("themes") or []:
            label = str(theme).strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def run_synthesis(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    *,
    theme_counts: Dict[str, int],
    sample_quotes: Sequence[Dict[str, Any]],
    aggregate_summary: str,
    total_sampled_rows: int,
) -> Tuple[List[EvaluationUserInsightItem], Optional[str]]:
    """Synthesize final insight blocks and section overview from extractions."""
    payload = {
        "total_sampled_rows": total_sampled_rows,
        "theme_frequencies": theme_counts,
        "sample_quotes": list(sample_quotes)[:40],
        "metric_aggregates": aggregate_summary,
    }
    text = _call_llm(
        db,
        organization_id,
        provider,
        model,
        [
            {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.25,
        max_tokens=SYNTHESIS_MAX_TOKENS,
    )
    parsed = _parse_json_object(text)
    overview_raw = parsed.get("overview")
    overview = (
        str(overview_raw).strip()
        if isinstance(overview_raw, str) and str(overview_raw).strip()
        else None
    )
    insights_raw = parsed.get("insights")
    if not isinstance(insights_raw, list):
        return [], overview

    items: List[EvaluationUserInsightItem] = []
    for raw in insights_raw:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        observation = str(raw.get("observation") or "").strip()
        if not title or not observation:
            continue

        categories: List[UserInsightCategory] = []
        categories_raw = raw.get("categories")
        if isinstance(categories_raw, list):
            for cat in categories_raw:
                if not isinstance(cat, dict):
                    continue
                label = str(cat.get("label") or "").strip()
                if not label:
                    continue
                count = int(cat.get("count") or 0)
                share = float(cat.get("share_pct") or 0.0)
                categories.append(
                    UserInsightCategory(label=label, count=count, share_pct=share)
                )

        evidence_raw = raw.get("evidence")
        evidence = UserInsightEvidence(quote="", conversation_id=None, turns=[])
        if isinstance(evidence_raw, dict):
            turns: List[UserInsightEvidenceTurn] = []
            turns_raw = evidence_raw.get("turns")
            if isinstance(turns_raw, list):
                for turn in turns_raw:
                    if isinstance(turn, dict):
                        speaker = str(turn.get("speaker") or "User").strip()
                        turn_text = str(turn.get("text") or "").strip()
                        if turn_text:
                            turns.append(
                                UserInsightEvidenceTurn(
                                    speaker=speaker, text=turn_text
                                )
                            )
            evidence = UserInsightEvidence(
                conversation_id=str(evidence_raw.get("conversation_id") or "").strip()
                or None,
                quote=str(evidence_raw.get("quote") or "").strip()[:800],
                turns=turns,
            )

        items.append(
            EvaluationUserInsightItem(
                id=str(uuid.uuid4()),
                title=title,
                categories=categories,
                observation=observation,
                evidence=evidence,
            )
        )
    if not overview and items:
        overview = _fallback_insights_overview(items)
    return items, overview


def _fallback_insights_overview(items: Sequence[EvaluationUserInsightItem]) -> str:
    """Deterministic overview when the synthesis LLM omits one."""
    parts = [
        f"{item.title}: {item.observation.strip()}"
        for item in items
        if item.title.strip() and item.observation.strip()
    ]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " ".join(parts[:3])


def _format_aggregate_summary(aggregate: Sequence[Any]) -> str:
    lines: List[str] = []
    for agg in aggregate[:25]:
        name = getattr(agg, "metric_name", None) or "Unknown"
        count = getattr(agg, "count", 0)
        line = f"- {name} (n={count})"
        value_counts = getattr(agg, "value_counts", None)
        if value_counts:
            top = value_counts[:3]
            shares = ", ".join(f'"{v.label}"={v.count}' for v in top)
            line += f" | top={shares}"
        mean = getattr(agg, "mean", None)
        if mean is not None:
            line += f" | mean={mean:.2f}"
        lines.append(line)
    return "\n".join(lines)


def generate_user_insights(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    *,
    completed_row_pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    metrics: Sequence[Metric],
    aggregate: Sequence[Any],
    on_progress: Optional[ProgressCallback] = None,
    max_llm_calls: Optional[int] = None,
) -> EvaluationUserInsightsState:
    """Run the full map-reduce pipeline and return the final state."""
    llm_budget = normalize_max_llm_calls(max_llm_calls)
    metric_names = _metric_name_map(metrics)
    row_payloads = [
        build_row_payload(evaluation, eval_row, source_row, metric_names)
        for eval_row, source_row in completed_row_pairs
        if eval_row.status == "completed"
    ]

    n_rows = len(row_payloads)
    if n_rows == 0:
        return EvaluationUserInsightsState(
            status="failed",
            error_message="No completed rows with metric scores to analyze.",
            generated_at=datetime.now(timezone.utc),
        )

    batch_size, num_extraction = compute_extraction_plan(
        n_rows, max_llm_calls=llm_budget
    )
    total_calls = num_extraction + SYNTHESIS_CALLS

    rng = random.Random(str(evaluation.id))
    shuffled = list(row_payloads)
    rng.shuffle(shuffled)
    batches = _batch_rows(shuffled, batch_size)[:num_extraction]

    all_extractions: List[Dict[str, Any]] = []
    completed_calls = 0

    for batch in batches:
        try:
            extracted = run_extraction_batch(
                db, organization_id, provider, model, batch
            )
            all_extractions.extend(extracted)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "User insights extraction batch failed for evaluation {}: {}",
                evaluation.id,
                exc,
            )
        completed_calls += 1
        if on_progress:
            on_progress(completed_calls, total_calls)

    theme_counts = _aggregate_themes(all_extractions)
    aggregate_summary = _format_aggregate_summary(aggregate)

    try:
        insights, overview = run_synthesis(
            db,
            organization_id,
            provider,
            model,
            theme_counts=theme_counts,
            sample_quotes=all_extractions,
            aggregate_summary=aggregate_summary,
            total_sampled_rows=n_rows,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "User insights synthesis failed for evaluation {}: {}",
            evaluation.id,
            exc,
        )
        return EvaluationUserInsightsState(
            status="failed",
            error_message=f"Synthesis failed: {exc}",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            max_llm_calls=llm_budget,
            progress={
                "completed_llm_calls": completed_calls,
                "total_llm_calls": total_calls,
            },
        )

    completed_calls += 1
    if on_progress:
        on_progress(completed_calls, total_calls)

    if not insights:
        return EvaluationUserInsightsState(
            status="failed",
            error_message="LLM returned no insight blocks.",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            max_llm_calls=llm_budget,
            progress={
                "completed_llm_calls": completed_calls,
                "total_llm_calls": total_calls,
            },
        )

    return EvaluationUserInsightsState(
        status="completed",
        insights=insights,
        overview=overview,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        max_llm_calls=llm_budget,
        progress={
            "completed_llm_calls": completed_calls,
            "total_llm_calls": total_calls,
        },
        provider=provider.value if hasattr(provider, "value") else str(provider),
        model=model,
        llm_calls_used=completed_calls,
        is_stale=False,
    )


def user_insights_state_from_raw(
    raw: Any,
    *,
    completed_rows: int = 0,
) -> Optional[EvaluationUserInsightsState]:
    """Parse DB JSON into ``EvaluationUserInsightsState``."""
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status not in {"idle", "running", "completed", "failed"}:
        status = "idle"

    insights: List[EvaluationUserInsightItem] = []
    insights_raw = raw.get("insights")
    if isinstance(insights_raw, list):
        for item in insights_raw:
            if not isinstance(item, dict):
                continue
            try:
                insights.append(EvaluationUserInsightItem.model_validate(item))
            except Exception:  # noqa: BLE001
                continue

    generated_at_raw = raw.get("generated_at")
    generated_at: Optional[datetime] = None
    if isinstance(generated_at_raw, str):
        try:
            generated_at = datetime.fromisoformat(generated_at_raw)
        except ValueError:
            generated_at = None

    snapshot = raw.get("generated_at_completed_rows")
    snapshot_int = int(snapshot) if isinstance(snapshot, (int, float)) else 0
    progress_raw = raw.get("progress")
    progress = (
        {
            "completed_llm_calls": int(progress_raw.get("completed_llm_calls") or 0),
            "total_llm_calls": int(progress_raw.get("total_llm_calls") or 0),
        }
        if isinstance(progress_raw, dict)
        else None
    )

    return EvaluationUserInsightsState(
        status=status,
        insights=insights,
        generated_at=generated_at,
        generated_at_completed_rows=snapshot_int,
        progress=progress,
        provider=raw.get("provider") if isinstance(raw.get("provider"), str) else None,
        model=raw.get("model") if isinstance(raw.get("model"), str) else None,
        llm_calls_used=int(raw.get("llm_calls_used") or 0),
        max_llm_calls=(
            int(raw.get("max_llm_calls"))
            if isinstance(raw.get("max_llm_calls"), (int, float))
            else None
        ),
        overview=raw.get("overview") if isinstance(raw.get("overview"), str) else None,
        error_message=(
            raw.get("error_message") if isinstance(raw.get("error_message"), str) else None
        ),
        is_stale=completed_rows > snapshot_int and status == "completed",
    )


def user_insights_state_to_db(state: EvaluationUserInsightsState) -> Dict[str, Any]:
    """Serialize state for the JSON column."""
    return {
        "status": state.status,
        "insights": [item.model_dump(mode="json") for item in state.insights],
        "generated_at": (
            state.generated_at.isoformat() if state.generated_at else None
        ),
        "generated_at_completed_rows": state.generated_at_completed_rows,
        "progress": state.progress,
        "provider": state.provider,
        "model": state.model,
        "llm_calls_used": state.llm_calls_used,
        "max_llm_calls": state.max_llm_calls,
        "overview": state.overview,
        "error_message": state.error_message,
    }
