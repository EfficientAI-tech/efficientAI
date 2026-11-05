"""Import list progress must not double-count catalog + stale Redis during processing."""

from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportRow,
    Organization,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


def _seed_csv_import(db_session):
    org = Organization(id=uuid4(), name="Progress UI Org")
    db_session.add(org)
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
    db_session.commit()

    call_import = CallImport(
        organization_id=org.id,
        workspace_id=workspace.id,
        original_filename="batch.csv",
        source_format="csv",
        total_rows=2,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.PROCESSING,
    )
    db_session.add(call_import)
    db_session.flush()

    for idx in range(2):
        db_session.add(
            CallImportRow(
                call_import_id=call_import.id,
                organization_id=org.id,
                workspace_id=workspace.id,
                row_index=idx,
                conversation_id=f"c-{idx}",
                status=(
                    CallImportRowStatus.COMPLETED
                    if idx == 0
                    else CallImportRowStatus.PENDING
                ),
            )
        )
    db_session.commit()
    return call_import


def test_serialize_processing_import_uses_row_aggregate_over_stale_redis(
    db_session, monkeypatch
):
    from app.services.call_imports.present import _serialize_call_import
    from app.services.call_imports.progress_counters import record_import_row_terminal

    call_import = _seed_csv_import(db_session)
    record_import_row_terminal(call_import.id, completed_delta=1)

    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )

    response = _serialize_call_import(
        db_session,
        call_import,
        refresh_import_progress_from_rows=True,
    )

    assert response.completed_rows == 1
    assert response.failed_rows == 0
    assert response.total_rows == 2
