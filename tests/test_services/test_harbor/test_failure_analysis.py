"""Failure clusters, prompt suggestions and the PDF report for simulation runs."""

from uuid import uuid4

import pytest

from app.models.database import EvaluatorResult, Metric
from app.models.enums import EvaluatorResultStatus, ModelProvider, SimulationRunStatus
from app.models.schemas import (
    EvaluationMetricClustersState,
    EvaluationPromptImprovementsState,
    MetricCluster,
    MetricClusterEvidence,
)
from app.services import call_import_metric_clusters as clusters_module
from app.services.harbor import failure_analysis
from app.services.harbor.failure_analysis import (
    count_failed_trials,
    describe_success_rule,
    generate_simulation_metric_clusters,
    simulation_cluster_rows,
    simulation_failure_predicate,
)
from app.services.metric_cluster_rows import MetricClusterSourceRow


def _row(scores):
    return MetricClusterSourceRow(
        row_id=uuid4(),
        conversation_id="c",
        row_index=None,
        metric_scores=scores,
        status="completed",
        transcript="",
    )


def _trial(db_session, rows, *, passed, scores, status=EvaluatorResultStatus.COMPLETED.value):
    result = EvaluatorResult(
        result_id=str(200000 + db_session.query(EvaluatorResult).count()),
        organization_id=rows.run.organization_id,
        workspace_id=rows.run.workspace_id,
        agent_id=rows.agent.id,
        scenario_id=rows.scenario.id,
        persona_id=rows.persona.id,
        simulation_run_id=rows.run.id,
        harbor_trial_name=f"trial-{uuid4().hex[:6]}",
        attempt_index=1,
        status=status,
        reward=1.0 if passed else 0.0,
        passed=passed,
        metric_scores=scores,
        speaker_segments=[
            {"speaker": "Customer", "text": "My order was late, I want a refund."},
            {"speaker": "Agent", "text": "Refunds are not possible."},
        ],
    )
    db_session.add(result)
    db_session.commit()
    return result


@pytest.fixture
def rule_run(db_session, sim_rows):
    mid = str(sim_rows.metric.id)
    sim_rows.run.metric_ids = [mid]
    sim_rows.run.metric_success_criteria = [
        {"metric_id": mid, "kind": "rating", "op": "gte", "threshold": 0.8}
    ]
    sim_rows.run.status = SimulationRunStatus.COMPLETED.value
    db_session.commit()
    return sim_rows


def test_predicate_uses_success_rule_flags(rule_run):
    run, metric = rule_run.run, rule_run.metric
    mid = str(metric.id)
    failed = simulation_failure_predicate(run, {mid: metric})

    assert failed(_row({mid: {"value": 0.4, "passed": False}}), metric)
    assert not failed(_row({mid: {"value": 0.9, "passed": True}}), metric)
    assert not failed(_row({}), metric)

    other = Metric(id=uuid4(), name="Other", metric_type="rating")
    assert not failed(_row({str(other.id): {"value": 0.1, "passed": False}}), other)


def test_predicate_flags_multi_label_parent_from_children(rule_run):
    run, metric = rule_run.run, rule_run.metric
    mid = str(metric.id)
    run.metric_success_criteria = [
        {"metric_id": mid, "kind": "category_multi", "label_rules": [{"child_id": "x", "expect": "yes"}]}
    ]
    failed = simulation_failure_predicate(run, {mid: metric})
    assert failed(_row({"x": {"value": False, "parent_metric_id": mid, "passed": False}}), metric)


def test_predicate_without_rules_uses_pass_threshold(sim_rows):
    run, metric = sim_rows.run, sim_rows.metric
    mid = str(metric.id)
    failed = simulation_failure_predicate(run, {mid: metric})

    assert failed(_row({mid: {"value": 0.5, "type": "rating"}}), metric)
    assert not failed(_row({mid: {"value": 0.9, "type": "rating"}}), metric)
    assert not failed(_row({mid: {"value": 0.1, "type": "rating", "skipped": True}}), metric)


def test_describe_success_rule():
    assert describe_success_rule({"kind": "rating", "op": "gte", "threshold": 0.8}) == "score ≥ 0.8"
    assert describe_success_rule({"kind": "boolean", "success_when": "no"}) == "answer is no"
    assert (
        describe_success_rule({"kind": "enum", "success_values": ["Resolved", "Escalated"]})
        == "one of: Resolved, Escalated"
    )
    assert (
        describe_success_rule(
            {"kind": "category_multi", "label_rules": [{"child_id": "c1", "expect": "no"}]},
            {"c1": "Rude"},
        )
        == "Rude = no"
    )


def test_cluster_rows_skip_errored_trials_and_label_by_combo(db_session, rule_run):
    mid = str(rule_run.metric.id)
    ok = _trial(db_session, rule_run, passed=False, scores={mid: {"value": 0.2, "passed": False}})
    _trial(
        db_session,
        rule_run,
        passed=None,
        scores=None,
        status=EvaluatorResultStatus.FAILED.value,
    )

    rows = simulation_cluster_rows(db_session, rule_run.run)

    assert [r.row_id for r in rows] == [ok.id]
    assert rows[0].conversation_id == (
        f"Refund for late order · Angry Alex · attempt 1 (#{ok.result_id})"
    )
    assert "Refunds are not possible." in rows[0].transcript
    assert count_failed_trials(db_session, rule_run.run) == 1


def test_generate_clusters_only_for_trials_that_missed_the_rule(db_session, rule_run, monkeypatch):
    mid = str(rule_run.metric.id)
    bad = _trial(db_session, rule_run, passed=False, scores={mid: {"value": 0.2, "passed": False}})
    _trial(db_session, rule_run, passed=True, scores={mid: {"value": 0.9, "passed": True}})

    seen_batches = []
    seen_credentials = []

    def fake_extraction(db, org_id, provider, model, metric_name, batch, *, credential_id=None):
        seen_batches.append(list(batch))
        seen_credentials.append(credential_id)
        return [
            {
                "conversation_id": row["conversation_id"],
                "evaluation_row_id": row["evaluation_row_id"],
                "signature": "refuses refunds",
            }
            for row in batch
        ]

    def fake_synthesis(
        db, org_id, provider, model, *, metric_name, signature_counts, sample_rows, flagged_count,
        credential_id=None,
    ):
        seen_credentials.append(credential_id)
        return [
            MetricCluster(
                id="c1",
                label="Refuses refunds",
                gap_label="MISSING",
                count=flagged_count,
                share_pct=100.0,
                evidence=MetricClusterEvidence(conversation_id=sample_rows[0]["conversation_id"]),
            )
        ]

    monkeypatch.setattr(clusters_module, "_run_extraction", fake_extraction)
    monkeypatch.setattr(clusters_module, "_synthesize_metric_clusters", fake_synthesis)
    monkeypatch.setattr(
        clusters_module,
        "_run_discovery",
        lambda *a, **k: seen_credentials.append(k.get("credential_id")) or [],
    )
    credential_id = uuid4()

    state = generate_simulation_metric_clusters(
        db_session,
        rule_run.run,
        provider=ModelProvider.OPENAI,
        model="gpt-4.1-mini",
        credential_id=credential_id,
    )

    assert state.status == "completed"
    assert [row["evaluation_row_id"] for batch in seen_batches for row in batch] == [str(bad.id)]
    # Extraction, synthesis and discovery all use the credential the user picked.
    assert seen_credentials == [credential_id, credential_id, credential_id]
    group = state.groups[0]
    assert group.metric_id == mid
    assert group.flagged_count == 1
    assert group.failure_reason == "Missed success rule: score ≥ 0.8"
    assert group.clusters[0].failure_reason.startswith("Missed success rule: score ≥ 0.8.")
    assert str(group.clusters[0].evidence.evaluation_row_id) == str(bad.id)


def test_generate_clusters_include_non_quality_gating_metrics(db_session, rule_run, monkeypatch):
    """A success rule on a user-insight metric still gets its failed trials clustered."""
    rule_run.metric.metric_category = "user_insight"
    db_session.commit()
    mid = str(rule_run.metric.id)
    _trial(db_session, rule_run, passed=False, scores={mid: {"value": 0.2, "passed": False}})

    monkeypatch.setattr(
        clusters_module,
        "_run_extraction",
        lambda *a, **k: [
            {
                "conversation_id": r["conversation_id"],
                "evaluation_row_id": r["evaluation_row_id"],
                "signature": "s",
            }
            for r in a[5]
        ],
    )
    monkeypatch.setattr(
        clusters_module,
        "_synthesize_metric_clusters",
        lambda *a, **k: [
            MetricCluster(
                id="c1", label="L", gap_label="MISSING", count=k["flagged_count"], share_pct=100.0
            )
        ],
    )
    monkeypatch.setattr(clusters_module, "_run_discovery", lambda *a, **k: [])

    state = generate_simulation_metric_clusters(
        db_session, rule_run.run, provider=ModelProvider.OPENAI, model="gpt-4.1-mini"
    )

    assert state.status == "completed"
    assert [g.metric_id for g in state.groups] == [mid]


def test_generate_clusters_reports_when_nothing_failed(db_session, rule_run):
    mid = str(rule_run.metric.id)
    _trial(db_session, rule_run, passed=True, scores={mid: {"value": 0.9, "passed": True}})

    state = generate_simulation_metric_clusters(
        db_session, rule_run.run, provider=ModelProvider.OPENAI, model="gpt-4.1-mini"
    )

    assert state.status == "failed"
    assert state.error_message.startswith("No completed trial missed a success rule")


def test_prompt_improvements_target_the_production_prompt(db_session, rule_run, monkeypatch):
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return EvaluationPromptImprovementsState(status="completed")

    monkeypatch.setattr(failure_analysis, "generate_prompt_improvements_for_prompt", fake_generate)
    raw = failure_analysis.generate_simulation_prompt_improvements(
        db_session,
        rule_run.run,
        EvaluationMetricClustersState(status="completed", generated_at_completed_rows=2),
    )

    # Chat agent without a synced provider prompt falls back to the description.
    assert captured["agent_prompt"] == "You help customers with refunds."
    assert captured["agent_name"] == "Support Bot"
    assert raw["compose_base_prompt"] == "You help customers with refunds."


def test_pdf_report_renders_sections(rule_run):
    from app.services.reporting.simulation_run_pdf_report import (
        simulation_run_pdf_report_service,
    )

    mid = str(rule_run.metric.id)
    service = simulation_run_pdf_report_service
    payload = {
        "run": rule_run.run,
        "agent": rule_run.agent,
        "summary": {
            "n_trials": 2,
            "n_completed": 2,
            "n_passed": 1,
            "uses_success_criteria": True,
            "pass_rate": 0.5,
            "mean_reward": 0.5,
            "metrics": [{"metric_id": mid, "name": "Empathy", "mean": 0.5, "pass_rate": 0.5, "n": 2}],
            "combos": [
                {"scenario_name": "Refund for late order", "persona_name": "Angry Alex", "attempts": 2, "passed": 1, "mean_reward": 0.5}
            ],
        },
        "success_rules": {mid: "score ≥ 0.8"},
        "metric_clusters": {
            "status": "completed",
            "groups": [
                {
                    "metric_id": mid,
                    "metric_name": "Empathy",
                    "flagged_count": 1,
                    "clusters": [
                        {"id": "c1", "label": "Refuses refunds", "gap_label": "MISSING", "count": 1, "share_pct": 100.0}
                    ],
                }
            ],
        },
        "prompt_improvements": {
            "status": "completed",
            "imported_agent_name": "Support Bot",
            "suggestions": [
                {
                    "id": "s1",
                    "metric_name": "Empathy",
                    "cluster_label": "Refuses refunds",
                    "gap_label": "MISSING",
                    "change_type": "add",
                    "suggested_text": "Offer a refund for late orders.",
                }
            ],
        },
        "sections": {},
        "platform_base_url": "https://app.example.com",
        "generated_at_iso": "2026-10-25 00:00 UTC",
    }

    html_text = service._render_simulation_html(payload)

    assert "01 Run Summary" in html_text
    assert "score ≥ 0.8" in html_text
    assert "04 Failure Diagnostics" in html_text
    assert "Refuses refunds" in html_text
    assert "05 Prompt Improvement Recommendations" in html_text
    assert "Offer a refund for late orders." in html_text
    assert "Visualizations" not in html_text

    payload["sections"] = {"failure_diagnostics": False, "prompt_improvements": False}
    trimmed = service._render_simulation_html(payload)
    assert "04 Failure Diagnostics" not in trimmed
    assert "05 Prompt Improvement Recommendations" not in trimmed

    # The plain-text fallback (no WeasyPrint) honours the same section choices.
    full_lines = service._simulation_plain_text_lines({**payload, "sections": {}})
    assert "01 Run Summary" in full_lines
    assert "04 Failure Diagnostics" in full_lines
    assert "05 Prompt Improvement Recommendations" in full_lines
    hidden = {"run_summary": False, "failure_diagnostics": False, "prompt_improvements": False}
    plain = service._simulation_plain_text_lines({**payload, "sections": hidden})
    assert "01 Run Summary" not in plain
    assert "02 Success Rules & Metric Results" not in plain
    assert "04 Failure Diagnostics" not in plain
    assert "05 Prompt Improvement Recommendations" not in plain

    assert service._evaluation_call_deep_link(
        platform_base_url="https://app.example.com/",
        call_import_id="",
        evaluation_id=rule_run.run.run_id,
        conversation_id="x",
        evaluation_row_id="abc",
    ) == f"https://app.example.com/simulations/{rule_run.run.run_id}?tab=analysis&trial=abc"

    pdf = service.render_pdf(
        run=rule_run.run,
        agent=rule_run.agent,
        summary=payload["summary"],
        success_rules=payload["success_rules"],
        metric_clusters=payload["metric_clusters"],
        prompt_improvements=payload["prompt_improvements"],
    )
    assert pdf.startswith(b"%PDF")


def test_failure_analysis_routes(authenticated_client, db_session, rule_run, monkeypatch):
    from app.workers.tasks import analyze_simulation_run_failures as task_module

    mid = str(rule_run.metric.id)
    run_ref = rule_run.run.run_id
    base = f"/api/v1/simulation-runs/{run_ref}"

    _trial(db_session, rule_run, passed=True, scores={mid: {"value": 0.9, "passed": True}})
    response = authenticated_client.post(f"{base}/failure-analysis")
    assert response.status_code == 400, response.text

    _trial(db_session, rule_run, passed=False, scores={mid: {"value": 0.2, "passed": False}})
    queued = []
    monkeypatch.setattr(
        task_module.analyze_simulation_run_failures_task,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )
    response = authenticated_client.post(f"{base}/failure-analysis", json={"model": "gpt-4.1-mini"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["failed_trials"] == 1
    assert body["success_rules"] == {mid: "score ≥ 0.8"}
    assert body["metric_clusters"]["status"] == "running"
    assert queued[0][0] == (str(rule_run.run.id),)
    assert queued[0][1]["model"] == "gpt-4.1-mini"
    db_session.refresh(rule_run.run)
    assert queued[0][1]["analysis_id"]
    assert queued[0][1]["analysis_id"] == rule_run.run.metric_clusters["analysis_id"]

    assert authenticated_client.post(f"{base}/failure-analysis").status_code == 409
    response = authenticated_client.post(f"{base}/failure-analysis/cancel")
    assert response.json()["metric_clusters"]["status"] == "cancelled"

    rule_run.run.prompt_improvements = {
        "status": "completed",
        "compose_base_prompt": "You help customers with refunds.",
        "suggestions": [
            {
                "id": "s1",
                "metric_id": mid,
                "metric_name": "Empathy",
                "cluster_id": "c1",
                "cluster_label": "Refuses refunds",
                "gap_label": "MISSING",
                "change_type": "edit",
                "anchor_excerpt": "refunds",
                "suggested_text": "refunds, and apologise for late orders",
            }
        ],
    }
    db_session.commit()

    response = authenticated_client.patch(
        f"{base}/prompt-improvements/review",
        json={"suggestion_id": "s1", "review_status": "accepted"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"][0]["review_status"] == "accepted"
    assert (
        authenticated_client.patch(
            f"{base}/prompt-improvements/review",
            json={"suggestion_id": "missing", "review_status": "accepted"},
        ).status_code
        == 404
    )

    composed = authenticated_client.get(f"{base}/prompt-improvements/composed").json()
    assert composed["accepted_count"] == 1
    assert composed["composed_prompt"] == (
        "You help customers with refunds, and apologise for late orders."
    )

    response = authenticated_client.post(f"{base}/pdf-report", json={"sections": {"methodology": False}})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_pdf_report_waits_for_run_to_finish(authenticated_client, sim_rows):
    response = authenticated_client.post(f"/api/v1/simulation-runs/{sim_rows.run.run_id}/pdf-report")
    assert response.status_code == 409


class _NonClosingSession:
    def __init__(self, session):
        self._session = session

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._session, name)


def _run_task(task_module, *args, **kwargs):
    """Call the task body whether Celery binds ``self`` or the suite stubbed Celery out."""
    import inspect

    task = task_module.analyze_simulation_run_failures_task
    fn = getattr(task, "run", task)
    if next(iter(inspect.signature(fn).parameters), None) == "self":
        return fn(None, *args, **kwargs)
    return fn(*args, **kwargs)


def test_superseded_worker_does_not_overwrite_new_analysis(db_session, rule_run, monkeypatch):
    """An older worker returning from an LLM call must not write over a regenerated analysis."""
    from app.services.harbor import failure_analysis as fa_module
    from app.workers.tasks import analyze_simulation_run_failures as task_module

    run = rule_run.run
    run.metric_clusters = task_module.new_failure_analysis_state()
    old_id = run.metric_clusters["analysis_id"]
    db_session.commit()
    replacement = {"status": "running", "analysis_id": "newer"}

    def fake_clusters(db, run_obj, **kwargs):
        # The user cancels and regenerates while this worker is mid-LLM call.
        run_obj.metric_clusters = dict(replacement)
        db.commit()
        assert kwargs["is_cancelled"]() is True
        kwargs["on_progress"]({"completed_llm_calls": 1})
        return EvaluationMetricClustersState(status="completed")

    def fail_prompts(*a, **k):
        raise AssertionError("superseded worker must not generate prompt suggestions")

    monkeypatch.setattr(task_module, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(
        "app.services.ai.llm_resolver.get_llm_provider_and_model_for_request",
        lambda *a, **k: (ModelProvider.OPENAI, "gpt-4.1-mini"),
    )
    monkeypatch.setattr(fa_module, "generate_simulation_metric_clusters", fake_clusters)
    monkeypatch.setattr(fa_module, "generate_simulation_prompt_improvements", fail_prompts)

    _run_task(task_module, str(run.id), analysis_id=old_id)

    db_session.expire_all()
    assert run.metric_clusters == replacement
    assert run.prompt_improvements is None

    # A task for an analysis that was already replaced exits before doing anything.
    monkeypatch.setattr(fa_module, "generate_simulation_metric_clusters", fail_prompts)
    _run_task(task_module, str(run.id), analysis_id=old_id)
