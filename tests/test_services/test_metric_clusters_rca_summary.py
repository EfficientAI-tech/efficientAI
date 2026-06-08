"""Tests for metric cluster RCA summary computation."""

from __future__ import annotations

from uuid import uuid4

from app.models.schemas import (
    MetricCluster,
    MetricClusterEvidence,
    MetricClusterGroup,
    MetricClustersRcaSummary,
    MetricFailurePolicy,
    MetricSubCluster,
)
from app.services.call_import_metric_clusters import (
    metric_clusters_state_from_raw,
    metric_clusters_state_to_db,
)
from app.services.metric_clusters_rca_summary import (
    compute_rca_summary,
    enrich_cluster_evidence,
    format_failure_policy_reason,
    top_rca_patterns_text,
)
from app.services.reporting.call_import_evaluation_pdf_report import (
    call_import_evaluation_pdf_report_service,
)


def test_top_rca_patterns_text_joins_clusters_and_subclusters():
    clusters = [
        MetricCluster(
            id="1",
            label="Escalation gap",
            gap_label="MISSING",
            count=10,
            share_pct=50.0,
            sub_clusters=[
                MetricSubCluster(label="Handoff missing", count=4, share_pct=40.0),
            ],
        ),
        MetricCluster(
            id="2",
            label="Recovery loop",
            gap_label="LOGIC_GAP",
            count=5,
            share_pct=25.0,
            sub_clusters=[],
        ),
    ]
    text = top_rca_patterns_text(clusters)
    assert "Escalation gap" in text
    assert "Handoff missing" in text
    assert "Recovery loop" in text


def test_compute_rca_summary_orders_top_five_and_prompt_areas():
    groups = [
        MetricClusterGroup(
            metric_id="m1",
            metric_name="Asks for human",
            flagged_count=100,
            failure_reason="Flagged when: yes",
            clusters=[
                MetricCluster(
                    id="c1",
                    label="Escalation",
                    gap_label="MISSING",
                    count=40,
                    share_pct=40.0,
                ),
            ],
        ),
        MetricClusterGroup(
            metric_id="m2",
            metric_name="Dead air",
            flagged_count=50,
            failure_reason="Flagged when: yes",
            clusters=[
                MetricCluster(
                    id="c2",
                    label="Silence",
                    gap_label="LOGIC_GAP",
                    count=30,
                    share_pct=60.0,
                ),
            ],
        ),
    ]
    summary = compute_rca_summary(
        groups,
        [],
        metrics_by_id={},
        analysed_calls=200,
    )
    assert summary.total_flagged_instances == 150
    assert summary.total_clusters == 2
    assert summary.total_clustered_instances == 70
    assert summary.analysed_calls == 200
    assert len(summary.repeated_patterns) == 2
    assert summary.repeated_patterns[0].metric_name == "Asks for human"
    assert summary.repeated_patterns[0].evidence_calls == 40
    assert summary.repeated_patterns[0].evidence_cluster_count == 1
    assert abs(summary.repeated_patterns[0].evidence_share_pct - (40 / 70 * 100)) < 0.2
    assert summary.metric_hotspots[0].metric_rate_pct == 50.0
    assert summary.metric_hotspots[0].flagged_calls == 100
    assert len(summary.prompt_areas) >= 1
    assert summary.prompt_areas[0].label == "Escalation criteria"


def test_enrich_cluster_evidence_resolves_evaluation_row_id():
    conv_map = {"call-abc": str(uuid4())}
    row_id = list(conv_map.values())[0]
    cluster = MetricCluster(
        id="1",
        label="Test",
        gap_label="UNDERSPEC",
        evidence=MetricClusterEvidence(conversation_id="call-abc", quote="hi"),
    )
    enrich_cluster_evidence(
        cluster,
        conv_map=conv_map,
        extractions=[{"conversation_id": "call-abc", "evaluation_row_id": row_id}],
    )
    assert str(cluster.evidence.evaluation_row_id) == row_id


def test_format_failure_policy_reason_includes_values_and_gap():
    policy = MetricFailurePolicy(
        metric_id="m1",
        failure_values=["no", "false"],
    )
    text = format_failure_policy_reason(policy, None, gap_label="MISSING")
    assert "Flagged when: no, false" in text
    assert "Escalation" in text or "missing" in text.lower()


def test_format_failure_policy_reason_omits_metric_rubric_description():
    policy = MetricFailurePolicy(metric_id="m1", failure_values=["no"])
    metric = type(
        "MetricStub",
        (),
        {"description": "Long rubric text that should not appear in diagnostics."},
    )()
    text = format_failure_policy_reason(policy, metric, gap_label="MISSING")
    assert "Long rubric" not in text
    assert "Flagged when: no" in text


def test_compute_rca_summary_hotspots_omit_metric_description():
    class _Metric:
        description = "Full metric definition should not be in hotspots."

    groups = [
        MetricClusterGroup(
            metric_id="m1",
            metric_name="Test metric",
            flagged_count=10,
            clusters=[],
        ),
    ]
    summary = compute_rca_summary(
        groups,
        [],
        metrics_by_id={"m1": _Metric()},
        analysed_calls=100,
    )
    assert len(summary.metric_hotspots) == 1
    assert summary.metric_hotspots[0].description == ""


def test_rca_summary_round_trip_through_db_helpers():
    summary = MetricClustersRcaSummary(
        total_clusters=1,
        total_clustered_instances=5,
        analysed_calls=10,
        repeated_patterns=[],
        metric_hotspots=[],
        prompt_areas=[],
    )
    from app.models.schemas import EvaluationMetricClustersState

    state = EvaluationMetricClustersState(
        status="completed",
        rca_summary=summary,
    )
    raw = metric_clusters_state_to_db(state)
    restored = metric_clusters_state_from_raw(raw)
    assert restored is not None
    assert restored.rca_summary is not None
    assert restored.rca_summary.total_clusters == 1


def test_pdf_failure_diagnostics_includes_rca_subsections_and_link():
    clusters = {
        "groups": [
            {
                "metric_id": "m1",
                "metric_name": "Test metric",
                "flagged_count": 10,
                "failure_reason": "Flagged when: yes",
                "clusters": [
                    {
                        "id": "c1",
                        "label": "Cluster A",
                        "gap_label": "MISSING",
                        "count": 10,
                        "share_pct": 100.0,
                        "sub_clusters": [],
                        "observation": "obs",
                        "failure_reason": "Flagged when: yes",
                        "evidence": {
                            "conversation_id": "conv-123",
                            "evaluation_row_id": str(uuid4()),
                            "quote": "user asked for agent",
                            "turns": [],
                        },
                        "is_discovered": False,
                    }
                ],
            }
        ],
        "discovered_problems": [],
        "rca_summary": {
            "total_clusters": 1,
            "total_clustered_instances": 10,
            "total_flagged_instances": 10,
            "analysed_calls": 50,
            "repeated_patterns": [
                {
                    "metric_id": "m1",
                    "metric_name": "Test metric",
                    "top_rca_patterns": "Cluster A",
                    "evidence_share_pct": 100.0,
                    "evidence_calls": 10,
                    "evidence_cluster_count": 1,
                    "failure_reason": "Flagged when: yes",
                }
            ],
            "metric_hotspots": [
                {
                    "metric_id": "m1",
                    "metric_name": "Test metric",
                    "description": "User asks for human",
                    "metric_rate_pct": 20.0,
                    "flagged_calls": 10,
                }
            ],
            "prompt_areas": [
                {"label": "Escalation criteria", "share_pct": 100.0, "gap_label": "MISSING"}
            ],
        },
    }
    html = call_import_evaluation_pdf_report_service._failure_diagnostics_section_html(
        clusters,
        None,
        platform_base_url="https://app.example.com",
        call_import_id="import-1",
        evaluation_id="eval-1",
    )
    assert "4.2 Repeated failure patterns" in html
    assert 'class="fd-rca-col-pct">Evidence share</th>' in html
    assert 'class="fd-rca-col-count">Evidence calls</th>' in html
    assert "fd-rca-patterns-wrap" in html
    assert "1 of 1 RCA clusters" not in html
    assert "Appendix: What is a cluster?" in html
    assert "4.3 Metric hotspots" in html
    assert "User asks for human" not in html
    assert "4.4 RCA data summary" in html
    assert 'href="https://app.example.com/call-imports/import-1/evaluations/eval-1?conversation_id=conv-123"' in html
