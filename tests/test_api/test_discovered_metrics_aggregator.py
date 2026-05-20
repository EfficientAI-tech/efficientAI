"""Tests for ``_get_running_discovered_metrics`` (top-level metric discovery).

Parallel to ``test_discovered_running_aggregator.py`` but the candidates
live flat under ``metric_scores["__discovered_metrics__"]`` rather than
nested under a parent metric. Verifies:

* slug-dedup + counting across rows,
* suggestion-type fallback when the LLM omits or garbles the field,
* non-completed rows are skipped,
* alias map (merge/tombstone) is applied,
* slugs already matching a real top-level Metric are hidden so we
  don't keep nagging the user about a candidate they've already
  promoted.
"""

from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import (
    DISCOVERED_METRICS_KEY,
    _get_running_discovered_metrics,
)
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    MetricTrigger,
    MetricType,
    Workspace,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
)


def _ensure_default_workspace(db_session, org_id):
    ws = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db_session.add(ws)
        db_session.commit()
    return ws


def _seed_call_import_and_eval(db_session, org_id, *, discover=True):
    workspace = _ensure_default_workspace(db_session, org_id)
    ci = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        column_mapping={},
        extra_columns=[],
        custom_column_mapping={},
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(ci)
    db_session.commit()
    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=ci.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Discovery Run",
        selected_metric_ids=[],
        status="completed",
        discover_new_metrics=discover,
    )
    db_session.add(evaluation)
    db_session.commit()
    return ci, evaluation, workspace


_row_counter = {"n": 0}


def _add_eval_row(
    db_session,
    *,
    evaluation,
    call_import,
    metric_scores,
    status=CallImportRowStatus.COMPLETED.value,
):
    _row_counter["n"] += 1
    source = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        row_index=_row_counter["n"],
        conversation_id=f"call-{_row_counter['n']}",
        raw_columns={},
    )
    db_session.add(source)
    db_session.flush()
    row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source.id,
        status=status,
        metric_scores=metric_scores,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_aggregator_dedupes_top_level_metric_slugs_across_rows(
    db_session, org_id, seed_org
):
    call_import, evaluation, _ = _seed_call_import_and_eval(db_session, org_id)

    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {
                    "key": "Customer Satisfaction",
                    "name": "Customer Satisfaction",
                    "description": "how happy the customer was",
                    "suggested_type": "rating",
                    "rationale": "User: great call!",
                }
            ]
        },
    )
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {
                    "key": "customer_satisfaction",
                    "name": "Sat",
                    "suggested_type": "rating",
                }
            ]
        },
    )
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {
                    "key": "needs_human_handoff",
                    "name": "Needs Human Handoff",
                    # Garbled type clamps to boolean.
                    "suggested_type": "weird",
                }
            ]
        },
    )

    items = _get_running_discovered_metrics(db_session, evaluation.id)
    by_key = {item["key"]: item for item in items}
    assert set(by_key.keys()) == {"customer_satisfaction", "needs_human_handoff"}
    assert by_key["customer_satisfaction"]["count"] == 2
    assert by_key["customer_satisfaction"]["suggested_type"] == "rating"
    # Description + rationale survive from the first occurrence even
    # when later rows omit them.
    assert by_key["customer_satisfaction"]["description"] == (
        "how happy the customer was"
    )
    assert by_key["customer_satisfaction"]["sample_rationale"].startswith(
        "User:"
    )
    # Clamped fallback.
    assert by_key["needs_human_handoff"]["suggested_type"] == "boolean"
    # Sorted by descending count then key.
    assert items[0]["key"] == "customer_satisfaction"


def test_aggregator_ignores_non_completed_rows(db_session, org_id, seed_org):
    call_import, evaluation, _ = _seed_call_import_and_eval(db_session, org_id)
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        status="running",
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {"key": "in_flight", "name": "In Flight"}
            ]
        },
    )
    assert _get_running_discovered_metrics(db_session, evaluation.id) == []


def test_aggregator_returns_empty_when_no_discovered_payload(
    db_session, org_id, seed_org
):
    call_import, evaluation, _ = _seed_call_import_and_eval(db_session, org_id)
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={"some_metric_uuid": {"value": 0.5}},
    )
    assert _get_running_discovered_metrics(db_session, evaluation.id) == []


def test_aggregator_applies_merge_alias_map(db_session, org_id, seed_org):
    call_import, evaluation, _ = _seed_call_import_and_eval(db_session, org_id)
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {"key": "customer_intent", "name": "Customer Intent"}
            ]
        },
    )
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [{"key": "intent", "name": "Intent"}]
        },
    )

    # Merge customer_intent -> intent: aggregator should fold the
    # ``from`` slug into the canonical target instead of double-counting.
    items = _get_running_discovered_metrics(
        db_session,
        evaluation.id,
        alias_map={"customer_intent": "intent"},
    )
    by_key = {item["key"]: item for item in items}
    assert set(by_key.keys()) == {"intent"}
    assert by_key["intent"]["count"] == 2


def test_aggregator_drops_tombstoned_alias(db_session, org_id, seed_org):
    call_import, evaluation, _ = _seed_call_import_and_eval(db_session, org_id)
    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {"key": "off_topic_chatter", "name": "Off Topic"}
            ]
        },
    )
    items = _get_running_discovered_metrics(
        db_session,
        evaluation.id,
        # Empty-string sentinel = tombstone.
        alias_map={"off_topic_chatter": ""},
    )
    assert items == []


def test_aggregator_hides_slugs_already_present_as_real_metric(
    db_session, org_id, seed_org
):
    """A candidate whose slug matches an existing top-level Metric is
    suppressed once the org id is passed — the user has already
    promoted (or independently created) the metric."""

    call_import, evaluation, workspace = _seed_call_import_and_eval(
        db_session, org_id
    )

    # Existing standalone Metric with name "Customer Satisfaction" —
    # slug("Customer Satisfaction") == "customer_satisfaction".
    existing = Metric(
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Customer Satisfaction",
        description="...",
        metric_type=MetricType.RATING.value,
        trigger=MetricTrigger.ALWAYS.value,
        enabled=True,
        is_default=False,
        metric_origin="custom",
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(existing)
    db_session.commit()

    _add_eval_row(
        db_session,
        evaluation=evaluation,
        call_import=call_import,
        metric_scores={
            DISCOVERED_METRICS_KEY: [
                {"key": "customer_satisfaction", "name": "Sat"},
                {"key": "needs_human_handoff", "name": "Handoff"},
            ]
        },
    )

    items = _get_running_discovered_metrics(
        db_session, evaluation.id, organization_id=org_id
    )
    keys = {item["key"] for item in items}
    # The already-promoted slug is hidden; the genuinely-new one stays.
    assert keys == {"needs_human_handoff"}
