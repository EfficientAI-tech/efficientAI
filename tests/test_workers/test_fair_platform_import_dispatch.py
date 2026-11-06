"""Tests for platform fair import row dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus


def _seed_platform_import(db_session):
    from app.models.database import Organization, Workspace

    org = Organization(id=uuid4(), name="Platform Org")
    db_session.add(org)
    ws = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="WS",
        slug="ws",
        is_default=True,
    )
    db_session.add(ws)
    db_session.commit()
    call_import = CallImport(
        organization_id=org.id,
        workspace_id=ws.id,
        original_filename="platform.json",
        total_rows=1,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PROCESSING,
        source_format="platform",
    )
    db_session.add(call_import)
    db_session.flush()
    row = CallImportRow(
        call_import_id=call_import.id,
        organization_id=org.id,
        row_index=0,
        conversation_id="conv-1",
        recording_url="platform:vapi:abc",
        status=CallImportRowStatus.PENDING,
    )
    db_session.add(row)
    db_session.commit()
    return call_import, row


@patch(
    "app.workers.concurrency.fair_platform_import_dispatch.schedule_fair_platform_import_dispatch",
)
@patch(
    "app.workers.concurrency.fair_platform_import_dispatch._bump_platform_dispatch_backoff_level",
    return_value=2,
)
@patch(
    "app.workers.concurrency.platform_import_dispatch.try_dispatch_platform_import_row",
    return_value=False,
)
@patch(
    "app.workers.concurrency.platform_import_dispatch.clear_expired_platform_row_claims",
    return_value=0,
)
def test_platform_dispatch_at_capacity_schedules_exponential_backoff(
    _mock_clear,
    _mock_try,
    _mock_bump,
    mock_schedule,
    db_session,
):
    from app.workers.concurrency.fair_platform_import_dispatch import (
        dispatch_fair_platform_import_rows_task,
    )

    _seed_platform_import(db_session)

    with patch(
        "app.workers.concurrency.fair_platform_import_dispatch.SessionLocal",
        return_value=db_session,
    ):
        result = dispatch_fair_platform_import_rows_task.run()

    assert result["dispatched"] == 0
    mock_schedule.assert_called_once()
    assert mock_schedule.call_args.kwargs["countdown"] == 30
