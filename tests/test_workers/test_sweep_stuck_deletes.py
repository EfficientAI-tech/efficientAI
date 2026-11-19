"""Tests for stuck-delete sweeper (enqueue only)."""

import sys
import types
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.database import CallImport
from app.models.enums import CallImportStatus
from app.services.call_imports.delete_teardown_lock import (
    try_acquire_call_import_delete_lock,
)
from app.workers.tasks.sweep_stuck_deletes import enqueue_stuck_deletes, list_stuck_call_imports


def test_list_stuck_call_imports_respects_stale_cutoff(
    db_session, org_id, default_workspace,
):
    workspace_id = default_workspace.id
    stale = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="stale.csv",
        column_mapping={},
        status=CallImportStatus.DELETING,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    fresh = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="fresh.csv",
        column_mapping={},
        status=CallImportStatus.DELETING,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add_all([stale, fresh])
    db_session.commit()

    stuck = list_stuck_call_imports(db_session)
    stuck_ids = {row[0] for row in stuck}
    assert stale.id in stuck_ids
    assert fresh.id not in stuck_ids


def test_enqueue_skips_when_lock_held(
    db_session, org_id, default_workspace, monkeypatch,
):
    workspace_id = default_workspace.id
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        original_filename="locked.csv",
        column_mapping={},
        status=CallImportStatus.DELETING,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(call_import)
    db_session.commit()
    assert try_acquire_call_import_delete_lock(call_import.id) is not None

    enqueued: list[str] = []
    fake_module = types.ModuleType("app.workers.tasks.call_import_bulk_ops")

    class _Capture:
        @staticmethod
        def delay(call_import_id, organization_id):
            enqueued.append(call_import_id)

    fake_module.delete_call_import_task = _Capture()
    fake_module.delete_call_import_evaluation_task = _Capture()
    monkeypatch.setitem(
        sys.modules,
        "app.workers.tasks.call_import_bulk_ops",
        fake_module,
    )

    count = enqueue_stuck_deletes(db_session)
    assert count == 0
    assert enqueued == []