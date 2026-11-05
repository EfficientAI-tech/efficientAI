"""Overwrite eval runs must bulk-reset diarisation before dispatch."""

from uuid import uuid4

from app.models.database import CallImport, CallImportRow, Organization, Workspace
from app.models.enums import CallImportRowStatus, CallImportStatus


def _seed_import_with_diarised_rows(db_session, *, row_count: int = 3):
    org = Organization(id=uuid4(), name="Overwrite Org")
    db_session.add(org)
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
    call_import = CallImport(
        organization_id=org.id,
        workspace_id=workspace.id,
        original_filename="batch.csv",
        total_rows=row_count,
        completed_rows=row_count,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()
    for idx in range(row_count):
        db_session.add(
            CallImportRow(
                call_import_id=call_import.id,
                organization_id=org.id,
                workspace_id=workspace.id,
                row_index=idx,
                conversation_id=f"c-{idx}",
                recording_s3_key=f"audio/{idx}.wav",
                diarised_transcript=f"old transcript {idx}",
                diarised_transcript_status="completed",
                celery_task_id=f"stale-task-{idx}",
                status=CallImportRowStatus.COMPLETED,
            )
        )
    db_session.commit()
    return call_import


def test_bulk_reset_diarisation_for_overwrite_clears_all_rows(
    db_session, monkeypatch
):
    from app.services.call_imports.bulk_ops import bulk_reset_diarisation_for_overwrite

    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops._batch_revoke_celery_task_ids",
        lambda task_ids, **kwargs: len(task_ids),
    )

    call_import = _seed_import_with_diarised_rows(db_session, row_count=3)
    reset = bulk_reset_diarisation_for_overwrite(db_session, call_import.id)

    assert reset == 3
    rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import.id)
        .order_by(CallImportRow.row_index)
        .all()
    )
    for row in rows:
        assert row.diarised_transcript is None
        assert row.diarised_transcript_status == "pending"
        assert row.diarised_transcript_error is None
        assert row.celery_task_id is None
