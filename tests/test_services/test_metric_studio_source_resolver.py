"""Tests for Metrics Studio source resolver."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportRowStatus,
    CallImportStatus,
)
from app.services.metric_studio.source_resolver import resolve_source


def test_resolve_unknown_source_kind_raises(db_session, org_id, default_workspace):
    with pytest.raises(HTTPException) as exc:
        resolve_source(
            db_session,
            organization_id=org_id,
            workspace_id=default_workspace.id,
            source_kind="unknown",
            source_ref="not-a-real-ref",
        )
    assert exc.value.status_code == 400


def test_resolve_call_import_row(db_session, org_id, default_workspace):
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=default_workspace.id,
        provider="exotel",
        original_filename="studio.csv",
        column_mapping={"external_call_id": "CallID", "transcript": "Transcript"},
        extra_columns=[],
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    row = CallImportRow(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        row_index=0,
        conversation_id="conv-studio-1",
        transcript="Production CSV transcript",
        status=CallImportRowStatus.COMPLETED,
    )
    db_session.add(row)
    db_session.commit()

    sample = resolve_source(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        source_kind="call_import_row",
        source_ref=str(row.id),
    )
    assert sample.transcript == "Production CSV transcript"
    assert sample.label == "conv-studio-1"
    assert sample.metadata["call_import_id"] == str(call_import.id)


def test_resolve_call_import_row_uses_locate_when_sharded(
    db_session, org_id, default_workspace, monkeypatch
):
    """When rows live on shards, catalog-only queries must not be used."""
    row_id = uuid4()
    call_import_id = uuid4()
    fake_row = CallImportRow(
        id=row_id,
        call_import_id=call_import_id,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        row_index=0,
        conversation_id="sharded-conv",
        transcript="sharded transcript",
        status=CallImportRowStatus.COMPLETED,
    )
    call_import = CallImport(
        id=call_import_id,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        provider="exotel",
        original_filename="sharded.csv",
        column_mapping={"external_call_id": "CallID"},
        extra_columns=[],
        total_rows=1,
        completed_rows=1,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.commit()

    def fake_locate(rid):
        assert rid == row_id
        return db_session, db_session, fake_row, "data-shard-01"

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: True,
    )

    sample = resolve_source(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        source_kind="call_import_row",
        source_ref=str(row_id),
    )
    assert sample.transcript == "sharded transcript"
