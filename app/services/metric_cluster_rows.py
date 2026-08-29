"""Generic row adapter for metric failure clustering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    EvaluatorResult,
)
from app.services.call_import_user_insights import _pick_transcript
from app.services.evaluators.evaluator_results_query import classify_display_status

ROW_TRANSCRIPT_CHAR_CAP = 3000


@dataclass(frozen=True)
class MetricClusterSourceRow:
    """Unified shape for call-import and evaluator-result clustering rows."""

    row_id: UUID
    conversation_id: str
    row_index: Optional[int]
    metric_scores: Dict[str, Any]
    status: str
    transcript: str


def transcript_from_evaluator_result(result: EvaluatorResult) -> str:
    text = (result.transcription or "").strip()
    if text:
        return text[:ROW_TRANSCRIPT_CHAR_CAP]
    segments = result.speaker_segments
    if isinstance(segments, list) and segments:
        parts: List[str] = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            speaker = str(seg.get("speaker") or "Speaker").strip()
            seg_text = str(seg.get("text") or "").strip()
            if seg_text:
                parts.append(f"{speaker}: {seg_text}")
        joined = "\n".join(parts).strip()
        if joined:
            return joined[:ROW_TRANSCRIPT_CHAR_CAP]
    return ""


def evaluator_result_to_cluster_row(result: EvaluatorResult) -> MetricClusterSourceRow:
    display_status = classify_display_status(result)
    return MetricClusterSourceRow(
        row_id=result.id,
        conversation_id=result.result_id,
        row_index=None,
        metric_scores=result.metric_scores if isinstance(result.metric_scores, dict) else {},
        status=display_status,
        transcript=transcript_from_evaluator_result(result),
    )


def call_import_pair_to_cluster_row(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
) -> MetricClusterSourceRow:
    return MetricClusterSourceRow(
        row_id=eval_row.id,
        conversation_id=source_row.conversation_id or str(source_row.id),
        row_index=source_row.row_index,
        metric_scores=eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {},
        status=str(eval_row.status or ""),
        transcript=_pick_transcript(evaluation, source_row)[:ROW_TRANSCRIPT_CHAR_CAP],
    )


def filter_cluster_rows_by_ids(
    rows: Sequence[MetricClusterSourceRow],
    row_ids: Optional[Sequence[UUID]],
) -> List[MetricClusterSourceRow]:
    if not row_ids:
        return list(rows)
    allowed = {str(rid) for rid in row_ids}
    return [row for row in rows if str(row.row_id) in allowed]


def build_evaluator_results_scope_key(
    *,
    agent_id: Optional[UUID] = None,
    suite_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
) -> str:
    parts: List[str] = []
    if agent_id:
        parts.append(f"agent:{agent_id}")
    if suite_id:
        parts.append(f"suite:{suite_id}")
    if scenario_id:
        parts.append(f"scenario:{scenario_id}")
    return "|".join(parts) if parts else "all"
