"""API tests for column-click sorting on
``GET /call-imports/{id}/evaluations/{eval_id}/rows``.

Covers the four supported sort keys plus the secondary
``row_index`` tiebreaker that pins pagination order:

* ``row_index`` (default — also explicitly request-able)
* ``conversation_id``
* ``status``
* ``metric:<uuid>`` (JSON-extracted ``value`` text)

The shared worker stubs from :mod:`test_call_import_evaluations` aren't
needed here because we never hit the evaluation-creation path that
would enqueue Celery tasks — we mutate ``CallImportEvaluationRow`` rows
directly so we have full control over per-row status and
``metric_scores`` payloads.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


def _ensure_default_workspace(db_session, org_id) -> Workspace:
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
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
        db_session.refresh(ws)
    return ws


def _seed_eval_with_rows(
    db_session,
    org_id,
    *,
    rows: list[dict],
) -> tuple[CallImport, CallImportEvaluation, Metric]:
    """Seed one call-import + one evaluation + N rows shaped from ``rows``.

    Each entry in ``rows`` supplies:
      * ``conversation_id`` — written to the source ``CallImportRow``
      * ``status`` — written to the ``CallImportEvaluationRow``
      * ``score_value`` — stored under ``metric_scores[<metric.id>].value``
        (set to ``None`` to omit the metric entirely so we can also
        verify NULL-last ordering on metric sorts).

    ``row_index`` is taken from the list order so callers can predict
    the secondary tiebreaker without bookkeeping.
    """
    workspace = _ensure_default_workspace(db_session, org_id)

    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="exotel",
        auth_id="enc",
        auth_token="enc",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.flush()

    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Quality",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(metric)

    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        telephony_integration_id=integration.id,
        original_filename="batch.csv",
        column_mapping={
            "external_call_id": "CallID",
            "transcript": "Transcript",
        },
        extra_columns=[],
        total_rows=len(rows),
        completed_rows=len(rows),
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        name="QA pass",
        selected_metric_ids=[str(metric.id)],
        status="completed",
        total_rows=len(rows),
        completed_rows=sum(1 for r in rows if r["status"] == "completed"),
        failed_rows=sum(1 for r in rows if r["status"] == "failed"),
    )
    db_session.add(evaluation)
    db_session.flush()

    for idx, spec in enumerate(rows):
        source_row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=idx,
            conversation_id=spec["conversation_id"],
            transcript=f"transcript-{idx}",
            raw_columns={
                "CallID": spec["conversation_id"],
                "Transcript": f"transcript-{idx}",
            },
            status=CallImportRowStatus.COMPLETED,
        )
        db_session.add(source_row)
        db_session.flush()

        metric_scores: dict = {}
        if spec.get("score_value") is not None:
            metric_scores[str(metric.id)] = {
                "value": spec["score_value"],
                "type": "rating",
                "metric_name": "Quality",
            }
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status=spec["status"],
                metric_scores=metric_scores,
            )
        )

    db_session.commit()
    db_session.refresh(evaluation)
    return call_import, evaluation, metric


def _ids(items: list[dict]) -> list[str]:
    """Return ``conversation_id`` per row in response order."""
    return [item["conversation_id"] for item in items]


def test_default_order_is_row_index_ascending(
    authenticated_client, db_session, org_id, seed_org
):
    """No sort param → server falls back to ``row_index ASC`` so the
    existing UI keeps the same default behaviour."""
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "call-zeta", "status": "completed", "score_value": 0.4},
            {"conversation_id": "call-alpha", "status": "completed", "score_value": 0.9},
            {"conversation_id": "call-beta", "status": "failed", "score_value": None},
        ],
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows"
    )
    assert response.status_code == 200, response.text
    assert _ids(response.json()["items"]) == [
        "call-zeta",
        "call-alpha",
        "call-beta",
    ]


def test_sort_by_conversation_id_asc_and_desc(
    authenticated_client, db_session, org_id, seed_org
):
    """``sort_by=conversation_id`` sorts the rows by the source
    conversation id in either direction."""
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "call-zeta", "status": "completed", "score_value": 0.4},
            {"conversation_id": "call-alpha", "status": "completed", "score_value": 0.9},
            {"conversation_id": "call-beta", "status": "failed", "score_value": 0.1},
        ],
    )

    asc = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "conversation_id", "sort_dir": "asc"},
    )
    assert _ids(asc.json()["items"]) == [
        "call-alpha",
        "call-beta",
        "call-zeta",
    ]

    desc = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "conversation_id", "sort_dir": "desc"},
    )
    assert _ids(desc.json()["items"]) == [
        "call-zeta",
        "call-beta",
        "call-alpha",
    ]


def test_sort_by_status_groups_same_status_together(
    authenticated_client, db_session, org_id, seed_org
):
    """Sorting by ``status`` should group the eval-row statuses
    alphabetically and use ``row_index`` as the tiebreaker so the
    relative order within a group stays predictable."""
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "row-0", "status": "failed", "score_value": 0.2},
            {"conversation_id": "row-1", "status": "completed", "score_value": 0.7},
            {"conversation_id": "row-2", "status": "failed", "score_value": 0.3},
            {"conversation_id": "row-3", "status": "completed", "score_value": 0.6},
        ],
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "status", "sort_dir": "asc"},
    )
    statuses = [item["status"] for item in response.json()["items"]]
    # Alphabetic: "completed" < "failed".
    assert statuses == ["completed", "completed", "failed", "failed"]
    # Inside each status the secondary ``row_index`` tiebreaker holds.
    assert _ids(response.json()["items"]) == [
        "row-1",
        "row-3",
        "row-0",
        "row-2",
    ]


def test_sort_by_metric_value_orders_by_extracted_json(
    authenticated_client, db_session, org_id, seed_org
):
    """``sort_by=metric:<uuid>`` reads ``metric_scores[<uuid>].value`` and
    orders by it. Rows where the metric is missing must sort to the end
    so ``ascending`` ordering doesn't crowd the top of the table with
    blanks."""
    call_import, evaluation, metric = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "row-low", "status": "completed", "score_value": 0.2},
            {"conversation_id": "row-mid", "status": "completed", "score_value": 0.5},
            {"conversation_id": "row-high", "status": "completed", "score_value": 0.9},
            {"conversation_id": "row-null", "status": "completed", "score_value": None},
        ],
    )

    asc = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": f"metric:{metric.id}", "sort_dir": "asc"},
    )
    assert _ids(asc.json()["items"]) == [
        "row-low",
        "row-mid",
        "row-high",
        # NULL bucket sorted last regardless of direction.
        "row-null",
    ]

    desc = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": f"metric:{metric.id}", "sort_dir": "desc"},
    )
    assert _ids(desc.json()["items"]) == [
        "row-high",
        "row-mid",
        "row-low",
        "row-null",
    ]


def test_invalid_sort_key_falls_back_to_row_index(
    authenticated_client, db_session, org_id, seed_org
):
    """A malformed ``sort_by`` (unknown column, garbage metric uuid)
    must NOT 500 — the route falls back to the default ``row_index``
    ordering so the table stays usable."""
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "row-0", "status": "completed", "score_value": 0.5},
            {"conversation_id": "row-1", "status": "completed", "score_value": 0.6},
        ],
    )

    bogus_column = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "this-column-does-not-exist", "sort_dir": "desc"},
    )
    assert bogus_column.status_code == 200, bogus_column.text
    assert _ids(bogus_column.json()["items"]) == ["row-0", "row-1"]

    bogus_metric = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "metric:not-a-uuid", "sort_dir": "asc"},
    )
    assert bogus_metric.status_code == 200, bogus_metric.text
    assert _ids(bogus_metric.json()["items"]) == ["row-0", "row-1"]


def test_sort_by_row_index_desc_uses_requested_direction(
    authenticated_client, db_session, org_id, seed_org
):
    """``sort_by=row_index`` is also explicitly request-able — and when
    paired with ``sort_dir=desc`` it must honour the direction (not
    silently fall back to the implicit ``asc`` default)."""
    call_import, evaluation, _ = _seed_eval_with_rows(
        db_session,
        org_id,
        rows=[
            {"conversation_id": "row-0", "status": "completed", "score_value": 0.5},
            {"conversation_id": "row-1", "status": "completed", "score_value": 0.6},
            {"conversation_id": "row-2", "status": "completed", "score_value": 0.7},
        ],
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"sort_by": "row_index", "sort_dir": "desc"},
    )
    assert _ids(response.json()["items"]) == ["row-2", "row-1", "row-0"]
