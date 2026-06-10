"""RCA executive summary and evidence enrichment for metric cluster diagnostics."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence
from uuid import UUID

from app.models.database import Metric
from app.models.schemas import (
    DiscoveredProblemCluster,
    MetricCluster,
    MetricClusterEvidence,
    MetricClusterGapLabel,
    MetricClusterGroup,
    MetricClustersRcaSummary,
    MetricFailurePolicy,
    RcaMetricHotspotRow,
    RcaPromptAreaRow,
    RcaRepeatedPatternRow,
)

_GAP_BUSINESS_LABELS: Dict[str, str] = {
    "LOGIC_GAP": "Fallback and recovery behavior",
    "UNDERSPEC": "General instruction clarity",
    "EXISTS_NO_TRIGGER": "Capability trigger rules",
    "MISSING": "Escalation criteria",
}

_GAP_HUMAN_LABELS: Dict[str, str] = {
    "LOGIC_GAP": "Logic gap (routing / loops)",
    "UNDERSPEC": "Underspecified prompt",
    "EXISTS_NO_TRIGGER": "Exists but not triggered",
    "MISSING": "Missing policy or handoff",
}

_TOP_N = 5


def gap_business_label(gap_label: str) -> str:
    key = str(gap_label or "").strip().upper().replace(" ", "_")
    return _GAP_BUSINESS_LABELS.get(key, key.replace("_", " ").title() or "Other")


def format_failure_policy_reason(
    policy: Optional[MetricFailurePolicy],
    metric: Optional[Metric],
    *,
    gap_label: Optional[str] = None,
) -> str:
    parts: List[str] = []
    if policy is not None:
        if policy.failure_values:
            parts.append(
                "Flagged when: " + ", ".join(str(v) for v in policy.failure_values)
            )
        if policy.failure_child_names:
            parts.append(
                "Flagged children: "
                + ", ".join(str(n) for n in policy.failure_child_names)
            )
        if policy.numeric_rule and isinstance(policy.numeric_rule, dict):
            op = policy.numeric_rule.get("op", "lt")
            threshold = policy.numeric_rule.get("threshold", 0.5)
            parts.append(f"Numeric rule: {op} {threshold}")
    if gap_label:
        parts.append(_GAP_HUMAN_LABELS.get(str(gap_label).upper(), str(gap_label)))
    return ". ".join(parts) if parts else "Quality metric failure"


def top_rca_patterns_text(clusters: Sequence[MetricCluster], *, limit: int = 2) -> str:
    ordered = sorted(clusters, key=lambda c: (-c.count, c.label))
    snippets: List[str] = []
    for cluster in ordered[:limit]:
        parts = [cluster.label]
        for sub in cluster.sub_clusters[:2]:
            if sub.label:
                parts.append(sub.label)
        snippets.append("; ".join(parts))
    return "; ".join(snippets) if snippets else "—"


def build_conversation_row_map(
    payloads: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for row in payloads:
        conv = str(row.get("conversation_id") or "").strip()
        row_id = row.get("evaluation_row_id")
        if conv and row_id:
            mapping[conv] = str(row_id)
    return mapping


def _resolve_row_id(
    conversation_id: Optional[str],
    conv_map: Mapping[str, str],
    extractions: Sequence[Dict[str, Any]],
) -> Optional[str]:
    conv = str(conversation_id or "").strip()
    if conv and conv in conv_map:
        return conv_map[conv]
    if conv:
        for row in extractions:
            if str(row.get("conversation_id") or "").strip() == conv:
                rid = row.get("evaluation_row_id")
                if rid:
                    return str(rid)
    for row in extractions:
        rid = row.get("evaluation_row_id")
        if rid:
            return str(rid)
    return None


def _apply_evidence_enrichment(
    evidence: MetricClusterEvidence,
    *,
    conv_map: Mapping[str, str],
    extractions: Sequence[Dict[str, Any]],
) -> MetricClusterEvidence:
    row_id_str = _resolve_row_id(evidence.conversation_id, conv_map, extractions)
    evaluation_row_id: Optional[UUID] = None
    if row_id_str:
        try:
            evaluation_row_id = UUID(row_id_str)
        except ValueError:
            evaluation_row_id = None
    if not evidence.conversation_id and extractions:
        first = extractions[0]
        return MetricClusterEvidence(
            conversation_id=str(first.get("conversation_id") or "").strip() or None,
            evaluation_row_id=evaluation_row_id,
            quote=evidence.quote or str(first.get("quote") or "")[:800],
            turns=evidence.turns,
        )
    return MetricClusterEvidence(
        conversation_id=evidence.conversation_id,
        evaluation_row_id=evaluation_row_id,
        quote=evidence.quote,
        turns=evidence.turns,
    )


def enrich_cluster_evidence(
    cluster: MetricCluster,
    *,
    conv_map: Mapping[str, str],
    extractions: Sequence[Dict[str, Any]],
) -> MetricCluster:
    cluster.evidence = _apply_evidence_enrichment(
        cluster.evidence,
        conv_map=conv_map,
        extractions=extractions,
    )
    return cluster


def enrich_metric_cluster_groups(
    groups: List[MetricClusterGroup],
    discovered: List[DiscoveredProblemCluster],
    *,
    policies: Dict[str, MetricFailurePolicy],
    metrics_by_id: Dict[str, Metric],
    payloads_by_metric: Dict[str, List[Dict[str, Any]]],
    extractions_by_metric: Dict[str, List[Dict[str, Any]]],
) -> tuple[List[MetricClusterGroup], List[DiscoveredProblemCluster]]:
    for group in groups:
        metric = metrics_by_id.get(group.metric_id)
        policy = policies.get(group.metric_id)
        group.failure_reason = format_failure_policy_reason(policy, metric)
        payloads = payloads_by_metric.get(group.metric_id, [])
        extractions = extractions_by_metric.get(group.metric_id, [])
        conv_map = build_conversation_row_map(payloads)
        enriched_clusters: List[MetricCluster] = []
        for cluster in group.clusters:
            cluster.failure_reason = format_failure_policy_reason(
                policy, metric, gap_label=cluster.gap_label
            )
            enrich_cluster_evidence(
                cluster,
                conv_map=conv_map,
                extractions=extractions,
            )
            enriched_clusters.append(cluster)
        group.clusters = enriched_clusters

    all_conv = build_conversation_row_map(
        [p for rows in payloads_by_metric.values() for p in rows]
    )
    all_extractions = [
        row for rows in extractions_by_metric.values() for row in rows
    ]
    for item in discovered:
        item.failure_reason = format_failure_policy_reason(
            None, None, gap_label=item.gap_label
        )
        item.evidence = _apply_evidence_enrichment(
            item.evidence,
            conv_map=all_conv,
            extractions=all_extractions,
        )

    return groups, discovered


def compute_rca_summary(
    groups: Sequence[MetricClusterGroup],
    discovered: Sequence[DiscoveredProblemCluster],
    *,
    metrics_by_id: Dict[str, Metric],
    analysed_calls: int,
) -> MetricClustersRcaSummary:
    total_clustered_instances = sum(
        max(0, c.count) for g in groups for c in g.clusters
    ) + sum(max(0, d.count) for d in discovered)
    total_clusters = sum(len(g.clusters) for g in groups) + len(discovered)

    pattern_rows: List[RcaRepeatedPatternRow] = []
    for group in groups:
        evidence_calls = sum(max(0, c.count) for c in group.clusters)
        share = (
            round((evidence_calls / total_clustered_instances) * 100.0, 1)
            if total_clustered_instances > 0
            else 0.0
        )
        pattern_rows.append(
            RcaRepeatedPatternRow(
                metric_id=group.metric_id,
                metric_name=group.metric_name,
                top_rca_patterns=top_rca_patterns_text(group.clusters),
                evidence_share_pct=share,
                evidence_calls=evidence_calls,
                evidence_cluster_count=len(group.clusters),
                failure_reason=group.failure_reason,
            )
        )
    pattern_rows.sort(key=lambda r: (-r.evidence_calls, r.metric_name))
    pattern_rows = pattern_rows[:_TOP_N]

    hotspot_rows: List[RcaMetricHotspotRow] = []
    for group in groups:
        rate = (
            round((group.flagged_count / analysed_calls) * 100.0, 2)
            if analysed_calls > 0
            else 0.0
        )
        hotspot_rows.append(
            RcaMetricHotspotRow(
                metric_id=group.metric_id,
                metric_name=group.metric_name,
                metric_rate_pct=rate,
                flagged_calls=group.flagged_count,
            )
        )
    hotspot_rows.sort(key=lambda r: (-r.flagged_calls, r.metric_name))
    hotspot_rows = hotspot_rows[:_TOP_N]

    gap_weights: Dict[str, int] = {}
    for group in groups:
        for cluster in group.clusters:
            gap = str(cluster.gap_label or "MISSING").upper()
            gap_weights[gap] = gap_weights.get(gap, 0) + max(0, cluster.count)
    for item in discovered:
        gap = str(item.gap_label or "MISSING").upper()
        gap_weights[gap] = gap_weights.get(gap, 0) + max(0, item.count)

    gap_total = sum(gap_weights.values()) or 1
    prompt_rows: List[RcaPromptAreaRow] = []
    for gap, weight in sorted(gap_weights.items(), key=lambda kv: (-kv[1], kv[0])):
        prompt_rows.append(
            RcaPromptAreaRow(
                label=gap_business_label(gap),
                share_pct=round((weight / gap_total) * 100.0, 1),
                gap_label=gap,  # type: ignore[arg-type]
            )
        )
    prompt_rows = prompt_rows[:_TOP_N]

    total_flagged_instances = sum(max(0, g.flagged_count) for g in groups)

    return MetricClustersRcaSummary(
        total_clusters=total_clusters,
        total_clustered_instances=total_clustered_instances,
        total_flagged_instances=total_flagged_instances,
        analysed_calls=analysed_calls,
        repeated_patterns=pattern_rows,
        metric_hotspots=hotspot_rows,
        prompt_areas=prompt_rows,
    )
