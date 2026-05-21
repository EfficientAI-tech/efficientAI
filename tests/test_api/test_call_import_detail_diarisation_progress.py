"""API tests for the diarisation-progress aggregates surfaced by
``GET /call-imports/{id}``.

The detail endpoint runs a single ``GROUP BY`` over
``CallImportRow.diarised_transcript_status`` so the UI can render a
"Transcription & diarisation" progress bar without paginating through
every row. These tests pin the contract:

* Every status bucket (``pending`` / ``running`` / ``completed`` /
  ``failed``) shows up as a top-level field, with ``0`` defaults when
  no rows fall into that bucket.
* Rows that have never been touched by the worker (``idle``) are NOT
  counted — callers derive the idle bucket from ``total_rows`` minus
  the four reported buckets.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportRow,
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


def _make_call_import_with_rows(
    db_session,
    org_id,
    *,
    diarised_statuses: list[str],
) -> CallImport:
    """Seed a CallImport whose rows carry the requested diarisation states.

    The list position is also used as ``row_index`` so the endpoint's
    default ordering stays deterministic.
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
        total_rows=len(diarised_statuses),
        completed_rows=len(diarised_statuses),
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    for idx, status in enumerate(diarised_statuses):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=idx,
            conversation_id=f"ext-{idx}",
            transcript=f"transcript {idx}",
            raw_columns={
                "CallID": f"ext-{idx}",
                "Transcript": f"transcript {idx}",
            },
            status=CallImportRowStatus.COMPLETED,
            diarised_transcript_status=status,
        )
        db_session.add(row)

    db_session.commit()
    db_session.refresh(call_import)
    return call_import


def test_detail_response_defaults_diarisation_counts_to_zero(
    authenticated_client, db_session, org_id, seed_org
):
    """A fresh batch where the diarise worker has never run should
    report zero across the board so the UI can hide its progress bar."""
    call_import = _make_call_import_with_rows(
        db_session,
        org_id,
        diarised_statuses=["idle", "idle", "idle"],
    )

    response = authenticated_client.get(f"/api/v1/call-imports/{call_import.id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_rows"] == 3
    assert body["diarised_pending_rows"] == 0
    assert body["diarised_running_rows"] == 0
    assert body["diarised_completed_rows"] == 0
    assert body["diarised_failed_rows"] == 0


def test_detail_response_buckets_each_diarisation_status(
    authenticated_client, db_session, org_id, seed_org
):
    """Mixed batch: every non-idle status bucket should be reported
    separately so the UI can derive both "in flight" (pending+running)
    and "done" (completed+failed) counts."""
    call_import = _make_call_import_with_rows(
        db_session,
        org_id,
        diarised_statuses=[
            "pending",
            "pending",
            "running",
            "completed",
            "completed",
            "completed",
            "failed",
            "idle",
        ],
    )

    response = authenticated_client.get(f"/api/v1/call-imports/{call_import.id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total_rows"] == 8
    assert body["diarised_pending_rows"] == 2
    assert body["diarised_running_rows"] == 1
    assert body["diarised_completed_rows"] == 3
    assert body["diarised_failed_rows"] == 1
    # The ``idle`` row is intentionally excluded so the UI computes the
    # idle bucket as ``total_rows - sum(reported)``.
    reported_sum = (
        body["diarised_pending_rows"]
        + body["diarised_running_rows"]
        + body["diarised_completed_rows"]
        + body["diarised_failed_rows"]
    )
    assert body["total_rows"] - reported_sum == 1  # the lone idle row


def test_detail_response_diarisation_counts_unaffected_by_row_pagination(
    authenticated_client, db_session, org_id, seed_org
):
    """``row_limit`` only paginates the embedded ``rows`` slice — it
    must NOT bias the batch-wide diarisation aggregate, otherwise the
    progress bar would jump around as the user pages."""
    call_import = _make_call_import_with_rows(
        db_session,
        org_id,
        diarised_statuses=[
            "completed",
            "completed",
            "running",
            "failed",
            "pending",
        ],
    )

    full = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}"
    ).json()
    sliced = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}",
        params={"row_limit": 1, "row_offset": 0},
    ).json()
    metadata_only = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}",
        params={"row_limit": 0},
    ).json()

    for body in (full, sliced, metadata_only):
        assert body["diarised_pending_rows"] == 1
        assert body["diarised_running_rows"] == 1
        assert body["diarised_completed_rows"] == 2
        assert body["diarised_failed_rows"] == 1
