"""End-to-end tests for the discovered top-level metrics endpoints.

Covers:
  * ``GET /call-imports/{id}/evaluations/{eval_id}/discovered-metrics``
    returns an empty list when the evaluation didn't opt into
    top-level metric discovery (the panel still calls the endpoint
    unconditionally).
  * Aggregator surfaces candidates from completed-row payloads when
    the flag is on.
  * Merge rewrites per-row payloads and persists the alias.
  * Delete tombstones the slug + strips it from per-row payloads.
"""

from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import DISCOVERED_METRICS_KEY
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


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


def _seed_call_import(db_session, org_id, *, discover):
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
    return ci, evaluation


_row_seq = {"n": 0}


def _add_row(db_session, *, evaluation, call_import, payload):
    _row_seq["n"] += 1
    source = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=call_import.organization_id,
        row_index=_row_seq["n"],
        conversation_id=f"call-{_row_seq['n']}",
        raw_columns={},
    )
    db_session.add(source)
    db_session.flush()
    row = CallImportEvaluationRow(
        id=uuid4(),
        evaluation_id=evaluation.id,
        call_import_row_id=source.id,
        status=CallImportRowStatus.COMPLETED.value,
        metric_scores=payload,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_get_returns_empty_when_discover_flag_off(
    authenticated_client, db_session, org_id
):
    """The frontend calls the endpoint unconditionally; runs that
    didn't opt in must return an empty list rather than 404."""

    ci, evaluation = _seed_call_import(db_session, org_id, discover=False)
    # Even with a row that *has* a discovered_metrics payload, the
    # opt-in check short-circuits before the aggregator runs.
    _add_row(
        db_session,
        evaluation=evaluation,
        call_import=ci,
        payload={
            DISCOVERED_METRICS_KEY: [
                {"key": "anything", "name": "Anything"}
            ]
        },
    )
    response = authenticated_client.get(
        f"/api/v1/call-imports/{ci.id}/evaluations/{evaluation.id}/discovered-metrics"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []


def test_get_returns_aggregated_items_when_discover_flag_on(
    authenticated_client, db_session, org_id
):
    ci, evaluation = _seed_call_import(db_session, org_id, discover=True)
    _add_row(
        db_session,
        evaluation=evaluation,
        call_import=ci,
        payload={
            DISCOVERED_METRICS_KEY: [
                {
                    "key": "customer_satisfaction",
                    "name": "Customer Satisfaction",
                    "description": "0-1 score",
                    "suggested_type": "rating",
                    "rationale": "User said: great call",
                }
            ]
        },
    )
    response = authenticated_client.get(
        f"/api/v1/call-imports/{ci.id}/evaluations/{evaluation.id}/discovered-metrics"
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["key"] == "customer_satisfaction"
    assert items[0]["suggested_type"] == "rating"


def test_merge_rewrites_row_payloads_and_persists_alias(
    authenticated_client, db_session, org_id
):
    ci, evaluation = _seed_call_import(db_session, org_id, discover=True)
    _add_row(
        db_session,
        evaluation=evaluation,
        call_import=ci,
        payload={
            DISCOVERED_METRICS_KEY: [
                {"key": "customer_intent", "name": "Customer Intent"}
            ]
        },
    )
    _add_row(
        db_session,
        evaluation=evaluation,
        call_import=ci,
        payload={
            DISCOVERED_METRICS_KEY: [{"key": "intent", "name": "Intent"}]
        },
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{ci.id}/evaluations/{evaluation.id}/discovered-metrics/merge",
        json={"from_key": "customer_intent", "to_key": "intent"},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {i["key"] for i in items} == {"intent"}

    # Alias map persisted on the evaluation.
    db_session.expire_all()
    refreshed = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert refreshed.discovered_metric_aliases.get("customer_intent") == (
        "intent"
    )


def test_delete_tombstones_slug_and_strips_row_payloads(
    authenticated_client, db_session, org_id
):
    ci, evaluation = _seed_call_import(db_session, org_id, discover=True)
    _add_row(
        db_session,
        evaluation=evaluation,
        call_import=ci,
        payload={
            DISCOVERED_METRICS_KEY: [
                {"key": "off_topic_chatter", "name": "Off Topic"},
                {"key": "useful_metric", "name": "Useful Metric"},
            ]
        },
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{ci.id}/evaluations/{evaluation.id}/discovered-metrics/delete",
        json={"key": "off_topic_chatter"},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    keys = {i["key"] for i in items}
    assert keys == {"useful_metric"}

    # Per-row payload has the slug stripped, and the evaluation
    # carries the tombstone sentinel so workers finishing later
    # can't resurrect the deletion.
    db_session.expire_all()
    refreshed_evaluation = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert refreshed_evaluation.discovered_metric_aliases.get(
        "off_topic_chatter"
    ) == ""

    row = (
        db_session.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
        .first()
    )
    remaining = row.metric_scores.get(DISCOVERED_METRICS_KEY, [])
    assert {entry["key"] for entry in remaining} == {"useful_metric"}
