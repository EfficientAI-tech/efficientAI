"""Per-metric failure clustering for internal call-import diagnostics."""

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
    CallImportMetricAggregate,
    DiscoveredProblemCluster,
    EvaluationMetricClustersState,
    MetricCluster,
    MetricClusterEvidence,
    MetricClusterEvidenceTurn,
    MetricClusterGroup,
    MetricClusterGapLabel,
    MetricFailurePolicy,
    MetricSubCluster,
)
from app.services.metric_clusters_rca_summary import (
    compute_rca_summary,
    enrich_metric_cluster_groups,
)
from app.services.metric_failure_policy import (
    effective_policies,
    is_metric_failure,
    policies_from_evaluation_raw,
    policy_has_failure_criteria,
)
from app.services.call_import_user_insights import (
    _call_llm,
    _parse_json_object,
    _pick_transcript,
    compute_extraction_plan,
    normalize_max_llm_calls,
)
from app.services.reporting.call_import_evaluation_pdf_report import (
    call_import_evaluation_pdf_report_service,
)

MAX_LLM_CALLS_DEFAULT = 200
DISCOVERY_CALLS = 1
METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR = (
    "Metric cluster generation cancelled by user"
)
ROW_TRANSCRIPT_CHAR_CAP = 3000
RATIONALE_CHAR_CAP = 600
EXTRACTION_MAX_TOKENS = 1800
CLUSTER_SYNTHESIS_MAX_TOKENS = 2400
DISCOVERY_MAX_TOKENS = 2000

ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def metric_clusters_raw_is_cancelled(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") or "").lower() == "cancelled":
        return True
    return raw.get("error_message") == METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR

_GAP_LABELS: Tuple[MetricClusterGapLabel, ...] = (
    "LOGIC_GAP",
    "UNDERSPEC",
    "EXISTS_NO_TRIGGER",
    "MISSING",
)

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a senior voice-bot QA engineer reviewing FAILED calls for one "
    "quality metric. Each call failed that metric. When a rationale is "
    "provided, use it to ground the failure signature. Extract a concise "
    "failure signature describing the structural problem.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "rows": [\n'
    "    {\n"
    '      "conversation_id": "<id>",\n'
    '      "signature": "<short failure signature, <=120 chars>",\n'
    '      "quote": "<verbatim transcript snippet, <=300 chars>",\n'
    '      "turns": [{"speaker": "User|Bot", "text": "..."}]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Constraints:\n"
    "- signatures must be specific and comparable across calls.\n"
    "- quote and turns must be verbatim from the supplied transcript.\n"
    "- No markdown, no preamble."
)

_CLUSTER_SYNTHESIS_PROMPT = (
    "You are clustering failed calls for a single quality metric into "
    "Level-1 problem groups and Level-2 sub-categories. You will receive "
    "failure signatures with frequencies.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "clusters": [\n'
    "    {\n"
    '      "label": "<Level-1 cluster name>",\n'
    '      "gap_label": "LOGIC_GAP|UNDERSPEC|EXISTS_NO_TRIGGER|MISSING",\n'
    '      "observation": "<1-2 sentence synthesis>",\n'
    '      "sub_clusters": [{"label": "...", "count": N}],\n'
    '      "evidence": {\n'
    '        "conversation_id": "...",\n'
    '        "quote": "...",\n'
    '        "turns": [{"speaker": "User|Bot", "text": "..."}]\n'
    "      }\n"
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Gap label definitions:\n"
    "- LOGIC_GAP: loops, wrong slot routing, state machine errors.\n"
    "- UNDERSPEC: vague/ambiguous prompt instructions.\n"
    "- EXISTS_NO_TRIGGER: coded capability did not activate in context.\n"
    "- MISSING: absent policy, fallback, or handoff rule.\n\n"
    "Constraints:\n"
    "- 2 to 8 Level-1 clusters; sub_clusters optional but encouraged.\n"
    "- sub_cluster counts should sum to <= Level-1 count.\n"
    "- gap_label must be one of the four values exactly.\n"
    "- Vendor-safe, factual language only."
)

_DISCOVERY_PROMPT = (
    "You are performing proactive unsupervised problem discovery across "
    "failed calls (any metric). Identify emerging themes NOT already "
    "captured by standard quality metrics.\n\n"
    "Return STRICT JSON only:\n"
    "{\n"
    '  "discovered": [\n'
    "    {\n"
    '      "label": "<new problem theme>",\n'
    '      "gap_label": "LOGIC_GAP|UNDERSPEC|EXISTS_NO_TRIGGER|MISSING",\n'
    '      "observation": "<1-2 sentences>",\n'
    '      "evidence": {"conversation_id": "...", "quote": "..."}\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Produce 0 to 5 discovered themes. If none, return {\"discovered\": []}."
)


def _score_value(score: dict[str, Any], metric: Metric | None) -> Any:
    svc = call_import_evaluation_pdf_report_service
    return svc._score_value(score, metric)


def _metric_is_quality(metric: Metric) -> bool:
    if (getattr(metric, "metric_category", "quality") or "quality") == "user_insight":
        return False
    return not call_import_evaluation_pdf_report_service._is_user_insight_metric(metric)


def _normalize_gap_label(raw: Any) -> MetricClusterGapLabel:
    text = str(raw or "").strip().upper().replace(" ", "_")
    if text in _GAP_LABELS:
        return text  # type: ignore[return-value]
    if "LOGIC" in text:
        return "LOGIC_GAP"
    if "UNDER" in text or "SPEC" in text:
        return "UNDERSPEC"
    if "TRIGGER" in text or "EXISTS" in text:
        return "EXISTS_NO_TRIGGER"
    return "MISSING"


def filter_completed_row_pairs(
    completed_row_pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    evaluation_row_ids: Optional[Sequence[UUID]],
) -> List[Tuple[CallImportEvaluationRow, CallImportRow]]:
    """Restrict clustering to the requested evaluation row IDs."""
    pairs = list(completed_row_pairs)
    if not evaluation_row_ids:
        return pairs
    allowed = {str(rid) for rid in evaluation_row_ids}
    return [(eval_row, source_row) for eval_row, source_row in pairs if str(eval_row.id) in allowed]


def resolve_clustering_policies(
    evaluation: CallImportEvaluation,
    metrics: Sequence[Metric],
    aggregates: Sequence[CallImportMetricAggregate],
    *,
    child_names_by_parent: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, MetricFailurePolicy]:
    policies, _source = effective_policies(
        evaluation,
        metrics,
        aggregates,
        child_names_by_parent=child_names_by_parent,
    )
    return policies


def flagged_metric_names_for_row(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    metrics: Sequence[Metric],
    policies: Dict[str, MetricFailurePolicy],
) -> List[str]:
    names: List[str] = []
    for metric in metrics:
        if not _metric_is_quality(metric):
            continue
        policy = policies.get(str(metric.id))
        if policy is None:
            continue
        if _build_flagged_row_payload(
            evaluation, eval_row, source_row, metric, policy
        ):
            names.append(metric.name)
    return names


def list_eligible_cluster_rows(
    evaluation: CallImportEvaluation,
    completed_row_pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    metrics: Sequence[Metric],
    policies: Dict[str, MetricFailurePolicy],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for eval_row, source_row in completed_row_pairs:
        flagged_names = flagged_metric_names_for_row(
            evaluation, eval_row, source_row, metrics, policies
        )
        if not flagged_names:
            continue
        items.append(
            {
                "evaluation_row_id": eval_row.id,
                "conversation_id": source_row.conversation_id,
                "row_index": source_row.row_index,
                "flagged_metric_names": flagged_names,
            }
        )
    items.sort(
        key=lambda row: (
            row.get("row_index") is None,
            row.get("row_index") if row.get("row_index") is not None else 0,
            str(row.get("conversation_id") or ""),
        )
    )
    return items


def _build_flagged_row_payload(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    source_row: CallImportRow,
    metric: Metric,
    policy: MetricFailurePolicy,
) -> Optional[Dict[str, Any]]:
    scores = eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
    entry = scores.get(str(metric.id))
    derived_from_children = False
    if not isinstance(entry, dict):
        entry = None

    if isinstance(entry, dict) and (entry.get("skipped") or entry.get("error")):
        return None

    if not is_metric_failure(eval_row, metric, policy):
        return None

    value = _score_value(entry, metric) if isinstance(entry, dict) else None
    selected_child_names: List[str] = []

    if isinstance(entry, dict) and (metric.selection_mode and not metric.parent_metric_id):
        if (metric.selection_mode or "").lower() == "single_choice":
            chosen_name = entry.get("chosen_child_name") or entry.get("value")
            chosen_text = str(chosen_name or "").strip()
            if chosen_text:
                value = chosen_text
                selected_child_names = [chosen_text]
        else:
            selected_raw = entry.get("selected_child_names")
            if isinstance(selected_raw, list):
                selected_child_names = [
                    str(name).strip() for name in selected_raw if str(name).strip()
                ]
            if selected_child_names:
                value = ", ".join(selected_child_names)
            elif not value:
                child_names: List[str] = []
                for child_entry_raw in scores.values():
                    if not isinstance(child_entry_raw, dict):
                        continue
                    if child_entry_raw.get("skipped") or child_entry_raw.get("error"):
                        continue
                    if (
                        str(child_entry_raw.get("parent_metric_id") or "")
                        != str(metric.id)
                    ):
                        continue
                    if child_entry_raw.get("value") is not True:
                        continue
                    child_name = str(child_entry_raw.get("metric_name") or "").strip()
                    if child_name:
                        child_names.append(child_name)
                if child_names:
                    derived_from_children = True
                    selected_child_names = child_names
                    value = ", ".join(child_names)

    if value is None:
        value = "failure"

    rationale = entry.get("rationale") if isinstance(entry, dict) else None
    if (not isinstance(rationale, str) or not rationale.strip()) and derived_from_children:
        # Parent entry is absent in this legacy shape; surface one child rationale
        # so cluster prompts still receive failure context.
        for child_entry_raw in scores.values():
            if not isinstance(child_entry_raw, dict):
                continue
            if str(child_entry_raw.get("parent_metric_id") or "") != str(metric.id):
                continue
            child_rationale = child_entry_raw.get("rationale")
            if isinstance(child_rationale, str) and child_rationale.strip():
                rationale = child_rationale
                break

    rationale_text = (
        rationale.strip()[:RATIONALE_CHAR_CAP]
        if isinstance(rationale, str) and rationale.strip()
        else ""
    )
    return {
        "conversation_id": source_row.conversation_id or str(source_row.id),
        "evaluation_row_id": str(eval_row.id),
        "row_index": source_row.row_index,
        "metric_name": metric.name,
        "metric_id": str(metric.id),
        "value": str(value)[:120],
        "rationale": rationale_text,
        "transcript": _pick_transcript(evaluation, source_row)[:ROW_TRANSCRIPT_CHAR_CAP],
    }


def _batch_rows(
    rows: Sequence[Dict[str, Any]],
    batch_size: int,
) -> List[List[Dict[str, Any]]]:
    return [list(rows[i : i + batch_size]) for i in range(0, len(rows), batch_size)]


def _run_extraction(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    metric_name: str,
    batch: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not batch:
        return []
    conv_to_row = {
        str(row.get("conversation_id") or "").strip(): str(row.get("evaluation_row_id"))
        for row in batch
        if str(row.get("conversation_id") or "").strip()
        and row.get("evaluation_row_id")
    }
    user_content = json.dumps(
        {"metric": metric_name, "failed_calls": list(batch)},
        ensure_ascii=False,
        default=str,
    )
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
        signature = str(item.get("signature") or "").strip()
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
        if conversation_id and (signature or quote):
            row_id = conv_to_row.get(conversation_id)
            out.append(
                {
                    "conversation_id": conversation_id,
                    "evaluation_row_id": row_id,
                    "signature": signature,
                    "quote": quote[:500],
                    "turns": turns,
                }
            )
    return out


def _aggregate_signatures(extractions: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in extractions:
        sig = str(row.get("signature") or "").strip()
        if sig:
            counts[sig] = counts.get(sig, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _parse_evidence(raw: Any) -> MetricClusterEvidence:
    if not isinstance(raw, dict):
        return MetricClusterEvidence()
    turns: List[MetricClusterEvidenceTurn] = []
    turns_raw = raw.get("turns")
    if isinstance(turns_raw, list):
        for turn in turns_raw:
            if isinstance(turn, dict):
                text = str(turn.get("text") or "").strip()
                if text:
                    turns.append(
                        MetricClusterEvidenceTurn(
                            speaker=str(turn.get("speaker") or "User").strip(),
                            text=text,
                        )
                    )
    return MetricClusterEvidence(
        conversation_id=str(raw.get("conversation_id") or "").strip() or None,
        quote=str(raw.get("quote") or "").strip()[:800],
        turns=turns,
    )


def _normalize_counts_to_total(
    counts: Sequence[int],
    total: int,
) -> List[int]:
    """Scale integer counts so they sum to ``total`` exactly."""
    n = len(counts)
    if n == 0:
        return []
    if total <= 0:
        return [0] * n

    weights = [max(0, int(c)) for c in counts]
    if sum(weights) <= 0:
        weights = [1] * n

    raw = [(w / sum(weights)) * total for w in weights]
    base = [int(math.floor(v)) for v in raw]
    remainder = total - sum(base)
    if remainder > 0:
        order = sorted(
            range(n),
            key=lambda idx: (raw[idx] - base[idx], weights[idx]),
            reverse=True,
        )
        for idx in order[:remainder]:
            base[idx] += 1
    elif remainder < 0:
        order = sorted(
            range(n),
            key=lambda idx: (raw[idx] - base[idx], weights[idx]),
        )
        for idx in order[: abs(remainder)]:
            if base[idx] > 0:
                base[idx] -= 1
    return base


def _synthesize_metric_clusters(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    *,
    metric_name: str,
    signature_counts: Dict[str, int],
    sample_rows: Sequence[Dict[str, Any]],
    flagged_count: int,
) -> List[MetricCluster]:
    if not signature_counts:
        return []
    payload = {
        "metric_name": metric_name,
        "flagged_count": flagged_count,
        "signature_frequencies": signature_counts,
        "samples": list(sample_rows)[:30],
    }
    text = _call_llm(
        db,
        organization_id,
        provider,
        model,
        [
            {"role": "system", "content": _CLUSTER_SYNTHESIS_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.25,
        max_tokens=CLUSTER_SYNTHESIS_MAX_TOKENS,
    )
    parsed = _parse_json_object(text)
    clusters_raw = parsed.get("clusters")
    if not isinstance(clusters_raw, list):
        return []

    items: List[MetricCluster] = []
    provisional_counts: List[int] = []
    for raw in clusters_raw:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        sub_clusters: List[MetricSubCluster] = []
        sub_raw = raw.get("sub_clusters")
        if isinstance(sub_raw, list):
            for sub in sub_raw:
                if not isinstance(sub, dict):
                    continue
                sub_label = str(sub.get("label") or "").strip()
                if not sub_label:
                    continue
                sub_count = int(sub.get("count") or 0)
                sub_clusters.append(
                    MetricSubCluster(
                        label=sub_label,
                        count=sub_count,
                        share_pct=0.0,
                    )
                )
        declared_count = max(0, int(raw.get("count") or 0))
        declared_share = float(raw.get("share_pct") or 0.0)
        count = declared_count
        if count <= 0 and declared_share > 0 and flagged_count > 0:
            count = max(1, int(round((declared_share / 100.0) * flagged_count)))
        if count <= 0 and sub_clusters:
            count = max(1, sum(max(0, s.count) for s in sub_clusters))
        if count <= 0:
            # Fallback for malformed/underspecified model output.
            count = max(1, int(signature_counts.get(label, 0)))
        items.append(
            MetricCluster(
                id=str(uuid.uuid4()),
                label=label,
                gap_label=_normalize_gap_label(raw.get("gap_label")),
                level=1,
                count=count,
                share_pct=0.0,
                sub_clusters=sub_clusters,
                observation=str(raw.get("observation") or "").strip(),
                evidence=_parse_evidence(raw.get("evidence")),
                is_discovered=False,
            )
        )
        provisional_counts.append(count)

    if items and flagged_count > 0:
        normalized_cluster_counts = _normalize_counts_to_total(
            provisional_counts,
            flagged_count,
        )
        adjusted_items: List[MetricCluster] = []
        for cluster, normalized_count in zip(items, normalized_cluster_counts):
            if normalized_count <= 0:
                continue
            cluster.count = normalized_count
            cluster.share_pct = round((normalized_count / flagged_count) * 100.0, 1)

            if cluster.sub_clusters:
                sub_counts = [max(0, sub.count) for sub in cluster.sub_clusters]
                normalized_sub_counts = _normalize_counts_to_total(
                    sub_counts,
                    normalized_count,
                )
                new_subs: List[MetricSubCluster] = []
                for sub, sub_count in zip(cluster.sub_clusters, normalized_sub_counts):
                    if sub_count <= 0:
                        continue
                    new_subs.append(
                        MetricSubCluster(
                            label=sub.label,
                            count=sub_count,
                            share_pct=round((sub_count / normalized_count) * 100.0, 1),
                        )
                    )
                cluster.sub_clusters = new_subs
            adjusted_items.append(cluster)
        items = adjusted_items
    elif items:
        total = sum(c.count for c in items) or 1
        for cluster in items:
            cluster.share_pct = round(cluster.count / total * 100.0, 1)
    return items


def _run_discovery(
    db: Session,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    sample_payloads: Sequence[Dict[str, Any]],
    *,
    total_flagged: int,
) -> List[DiscoveredProblemCluster]:
    if not sample_payloads or total_flagged <= 0:
        return []
    payload = {
        "sample_failed_calls": list(sample_payloads)[:40],
        "total_flagged_calls": total_flagged,
    }
    text = _call_llm(
        db,
        organization_id,
        provider,
        model,
        [
            {"role": "system", "content": _DISCOVERY_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.35,
        max_tokens=DISCOVERY_MAX_TOKENS,
    )
    parsed = _parse_json_object(text)
    discovered_raw = parsed.get("discovered")
    if not isinstance(discovered_raw, list):
        return []
    items: List[DiscoveredProblemCluster] = []
    for raw in discovered_raw:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        count = max(1, int(raw.get("count") or 1))
        share = min(100.0, round(count / total_flagged * 100.0, 1))
        items.append(
            DiscoveredProblemCluster(
                id=str(uuid.uuid4()),
                label=label,
                gap_label=_normalize_gap_label(raw.get("gap_label")),
                count=count,
                share_pct=share,
                observation=str(raw.get("observation") or "").strip(),
                evidence=_parse_evidence(raw.get("evidence")),
            )
        )
    return items


def estimate_metric_clusters_llm_calls(
    evaluation: CallImportEvaluation,
    metrics: Sequence[Metric],
    completed_row_pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    policies: Dict[str, MetricFailurePolicy],
    *,
    max_llm_calls: Optional[int] = None,
) -> Tuple[int, int]:
    """Return ``(flagged_metric_count, total_estimated_llm_calls)``."""
    llm_budget = normalize_max_llm_calls(max_llm_calls)
    quality_metrics = [m for m in metrics if _metric_is_quality(m)]
    flagged_metric_count = 0
    extraction_calls = 0

    extraction_cap = max(1, llm_budget - DISCOVERY_CALLS - len(quality_metrics))

    for metric in quality_metrics:
        policy = policies.get(str(metric.id))
        if policy is None or not policy_has_failure_criteria(policy, metric):
            continue
        flagged_count = 0
        for eval_row, source_row in completed_row_pairs:
            if eval_row.status != "completed":
                continue
            if _build_flagged_row_payload(
                evaluation, eval_row, source_row, metric, policy
            ):
                flagged_count += 1
        if flagged_count <= 0:
            continue
        flagged_metric_count += 1
        per_metric_cap = max(20, extraction_cap // max(len(quality_metrics), 1))
        _, num_batches = compute_extraction_plan(
            flagged_count, max_llm_calls=per_metric_cap
        )
        extraction_calls += num_batches + 1  # extraction batches + synthesis

    discovery = 1 if flagged_metric_count > 0 else 0
    total = extraction_calls + discovery
    return flagged_metric_count, max(total, 1)


def _selected_evaluation_row_ids(evaluation: CallImportEvaluation) -> List[str]:
    raw = evaluation.metric_clusters
    if not isinstance(raw, dict):
        return []
    ids_raw = raw.get("selected_evaluation_row_ids")
    if not isinstance(ids_raw, list):
        return []
    return [str(rid) for rid in ids_raw if rid]


def generate_metric_clusters(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    provider: ModelProvider,
    model: str,
    *,
    completed_row_pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    metrics: Sequence[Metric],
    policies: Dict[str, MetricFailurePolicy],
    on_progress: Optional[ProgressCallback] = None,
    max_llm_calls: Optional[int] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> EvaluationMetricClustersState:
    """Run per-metric clustering + proactive discovery for internal diagnostics."""
    llm_budget = normalize_max_llm_calls(max_llm_calls)
    quality_metrics = [m for m in metrics if _metric_is_quality(m)]
    selected_row_ids = _selected_evaluation_row_ids(evaluation)
    stored_policies, policy_source = policies_from_evaluation_raw(
        evaluation.metric_clusters
    )
    failure_policies = policies or stored_policies
    policies_updated_raw = None
    raw_mc = evaluation.metric_clusters
    if isinstance(raw_mc, dict) and raw_mc.get("failure_policies_updated_at"):
        try:
            policies_updated_raw = datetime.fromisoformat(
                str(raw_mc["failure_policies_updated_at"])
            )
        except ValueError:
            policies_updated_raw = None

    groups: List[MetricClusterGroup] = []
    all_flagged_samples: List[Dict[str, Any]] = []
    payloads_by_metric: Dict[str, List[Dict[str, Any]]] = {}
    extractions_by_metric: Dict[str, List[Dict[str, Any]]] = {}
    metrics_by_id: Dict[str, Metric] = {str(m.id): m for m in metrics}
    total_flagged = 0
    analysed_calls = sum(
        1
        for eval_row, _source in completed_row_pairs
        if eval_row.status == "completed"
    )

    flagged_metric_count, total_calls_estimate = estimate_metric_clusters_llm_calls(
        evaluation,
        metrics,
        completed_row_pairs,
        policies,
        max_llm_calls=llm_budget,
    )
    if flagged_metric_count <= 0:
        return EvaluationMetricClustersState(
            status="failed",
            error_message=(
                "No flagged calls found for any enabled quality metric. "
                "Clustering runs only on metrics with at least one row matching "
                "the configured failure policy."
            ),
            generated_at=datetime.now(timezone.utc),
            max_llm_calls=llm_budget,
            selected_evaluation_row_ids=selected_row_ids,
            failure_policies=failure_policies,
            failure_policies_source=policy_source,  # type: ignore[arg-type]
            failure_policies_updated_at=policies_updated_raw,
        )

    extraction_cap = max(1, llm_budget - DISCOVERY_CALLS - flagged_metric_count)
    completed_calls = 0

    def _check_cancelled() -> Optional[EvaluationMetricClustersState]:
        if is_cancelled is None or not is_cancelled():
            return None
        return EvaluationMetricClustersState(
            status="cancelled",
            groups=groups,
            discovered_problems=[],
            error_message=METRIC_CLUSTERS_CANCELLED_BY_USER_ERROR,
            generated_at=datetime.now(timezone.utc),
            generated_at_completed_rows=evaluation.completed_rows,
            max_llm_calls=llm_budget,
            progress={
                "completed_llm_calls": completed_calls,
                "total_llm_calls": total_calls_estimate,
            },
            provider=provider.value if hasattr(provider, "value") else str(provider),
            model=model,
            llm_calls_used=completed_calls,
            selected_evaluation_row_ids=selected_row_ids,
        )

    for metric in quality_metrics:
        cancelled_state = _check_cancelled()
        if cancelled_state is not None:
            return cancelled_state
        policy = policies.get(str(metric.id))
        if policy is None or not policy_has_failure_criteria(policy, metric):
            continue
        flagged_payloads: List[Dict[str, Any]] = []
        for eval_row, source_row in completed_row_pairs:
            if eval_row.status != "completed":
                continue
            payload = _build_flagged_row_payload(
                evaluation, eval_row, source_row, metric, policy
            )
            if payload:
                flagged_payloads.append(payload)
                all_flagged_samples.append(payload)

        if not flagged_payloads:
            continue

        flagged_count = len(flagged_payloads)
        total_flagged += flagged_count

        batch_size, num_batches = compute_extraction_plan(
            flagged_count, max_llm_calls=max(20, extraction_cap // max(len(quality_metrics), 1))
        )
        rng = random.Random(f"{evaluation.id}:{metric.id}")
        shuffled = list(flagged_payloads)
        rng.shuffle(shuffled)
        batches = _batch_rows(shuffled, batch_size)[:num_batches]

        extractions: List[Dict[str, Any]] = []
        for batch in batches:
            cancelled_state = _check_cancelled()
            if cancelled_state is not None:
                return cancelled_state
            try:
                extracted = _run_extraction(
                    db,
                    organization_id,
                    provider,
                    model,
                    metric.name,
                    batch,
                )
                extractions.extend(extracted)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Metric cluster extraction failed for {} / {}: {}",
                    evaluation.id,
                    metric.id,
                    exc,
                )
            completed_calls += 1
            if on_progress:
                on_progress(completed_calls, total_calls_estimate)

        cancelled_state = _check_cancelled()
        if cancelled_state is not None:
            return cancelled_state

        signature_counts = _aggregate_signatures(extractions)
        try:
            clusters = _synthesize_metric_clusters(
                db,
                organization_id,
                provider,
                model,
                metric_name=metric.name,
                signature_counts=signature_counts,
                sample_rows=extractions,
                flagged_count=flagged_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Metric cluster synthesis failed for {} / {}: {}",
                evaluation.id,
                metric.id,
                exc,
            )
            clusters = []

        completed_calls += 1
        if on_progress:
            on_progress(completed_calls, total_calls_estimate)

        metric_id_str = str(metric.id)
        payloads_by_metric[metric_id_str] = list(flagged_payloads)
        extractions_by_metric[metric_id_str] = list(extractions)
        if clusters:
            groups.append(
                MetricClusterGroup(
                    metric_id=metric_id_str,
                    metric_name=metric.name,
                    flagged_count=flagged_count,
                    clusters=clusters,
                )
            )

    cancelled_state = _check_cancelled()
    if cancelled_state is not None:
        return cancelled_state

    discovered: List[DiscoveredProblemCluster] = []
    try:
        discovered = _run_discovery(
            db,
            organization_id,
            provider,
            model,
            all_flagged_samples,
            total_flagged=max(total_flagged, 1),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Proactive discovery failed for evaluation {}: {}",
            evaluation.id,
            exc,
        )
    completed_calls += 1
    if on_progress:
        on_progress(completed_calls, total_calls_estimate)

    if not groups and not discovered:
        return EvaluationMetricClustersState(
            status="failed",
            error_message="No flagged quality metrics or clusters produced.",
            generated_at=datetime.now(timezone.utc),
            llm_calls_used=completed_calls,
            max_llm_calls=llm_budget,
            selected_evaluation_row_ids=selected_row_ids,
        )

    groups, discovered = enrich_metric_cluster_groups(
        groups,
        discovered,
        policies=failure_policies,
        metrics_by_id=metrics_by_id,
        payloads_by_metric=payloads_by_metric,
        extractions_by_metric=extractions_by_metric,
    )
    rca_summary = compute_rca_summary(
        groups,
        discovered,
        metrics_by_id=metrics_by_id,
        analysed_calls=max(analysed_calls, 1),
    )

    overview_parts = [
        f"{g.metric_name}: {len(g.clusters)} cluster(s) across {g.flagged_count} flagged calls"
        for g in groups
    ]
    if discovered:
        overview_parts.append(
            f"{len(discovered)} proactively discovered theme(s)"
        )

    return EvaluationMetricClustersState(
        status="completed",
        groups=groups,
        discovered_problems=discovered,
        rca_summary=rca_summary,
        overview="; ".join(overview_parts) if overview_parts else None,
        generated_at=datetime.now(timezone.utc),
        generated_at_completed_rows=evaluation.completed_rows,
        max_llm_calls=llm_budget,
        progress={
            "completed_llm_calls": completed_calls,
            "total_llm_calls": total_calls_estimate,
        },
        provider=provider.value if hasattr(provider, "value") else str(provider),
        model=model,
        llm_calls_used=completed_calls,
        is_stale=False,
        selected_evaluation_row_ids=selected_row_ids,
        failure_policies=failure_policies,
        failure_policies_source=policy_source,  # type: ignore[arg-type]
        failure_policies_updated_at=policies_updated_raw,
    )


def metric_clusters_state_from_raw(
    raw: Any,
    *,
    completed_rows: int = 0,
) -> Optional[EvaluationMetricClustersState]:
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status not in {"idle", "running", "completed", "failed", "cancelled"}:
        status = "idle"

    groups: List[MetricClusterGroup] = []
    groups_raw = raw.get("groups")
    if isinstance(groups_raw, list):
        for item in groups_raw:
            if isinstance(item, dict):
                try:
                    groups.append(MetricClusterGroup.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue

    discovered: List[DiscoveredProblemCluster] = []
    disc_raw = raw.get("discovered_problems")
    if isinstance(disc_raw, list):
        for item in disc_raw:
            if isinstance(item, dict):
                try:
                    discovered.append(DiscoveredProblemCluster.model_validate(item))
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

    rca_summary = None
    rca_raw = raw.get("rca_summary")
    if isinstance(rca_raw, dict):
        try:
            from app.models.schemas import MetricClustersRcaSummary as _RcaSummary

            rca_summary = _RcaSummary.model_validate(rca_raw)
        except Exception:  # noqa: BLE001
            rca_summary = None

    return EvaluationMetricClustersState(
        status=status,
        groups=groups,
        discovered_problems=discovered,
        rca_summary=rca_summary,
        overview=raw.get("overview") if isinstance(raw.get("overview"), str) else None,
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
        error_message=(
            raw.get("error_message") if isinstance(raw.get("error_message"), str) else None
        ),
        is_stale=completed_rows > snapshot_int and status == "completed",
        selected_evaluation_row_ids=[
            str(rid)
            for rid in (raw.get("selected_evaluation_row_ids") or [])
            if rid
        ]
        if isinstance(raw.get("selected_evaluation_row_ids"), list)
        else [],
        failure_policies=policies_from_evaluation_raw(raw)[0],
        failure_policies_source=(
            "user"
            if str(raw.get("failure_policies_source") or "").lower() == "user"
            else "inferred"
        ),
        failure_policies_updated_at=(
            datetime.fromisoformat(str(raw["failure_policies_updated_at"]))
            if isinstance(raw.get("failure_policies_updated_at"), str)
            else None
        ),
    )


def metric_clusters_state_to_db(state: EvaluationMetricClustersState) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": state.status,
        "groups": [g.model_dump(mode="json") for g in state.groups],
        "discovered_problems": [
            d.model_dump(mode="json") for d in state.discovered_problems
        ],
        "overview": state.overview,
        "generated_at": (
            state.generated_at.isoformat() if state.generated_at else None
        ),
        "generated_at_completed_rows": state.generated_at_completed_rows,
        "progress": state.progress,
        "provider": state.provider,
        "model": state.model,
        "llm_calls_used": state.llm_calls_used,
        "max_llm_calls": state.max_llm_calls,
        "error_message": state.error_message,
        "selected_evaluation_row_ids": list(state.selected_evaluation_row_ids),
        "failure_policies": {
            mid: pol.model_dump(mode="json")
            for mid, pol in (state.failure_policies or {}).items()
        },
        "failure_policies_source": state.failure_policies_source,
        "failure_policies_updated_at": (
            state.failure_policies_updated_at.isoformat()
            if state.failure_policies_updated_at
            else None
        ),
        "rca_summary": (
            state.rca_summary.model_dump(mode="json")
            if state.rca_summary is not None
            else None
        ),
    }
    return payload
