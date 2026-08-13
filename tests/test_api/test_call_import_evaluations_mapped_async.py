"""Tests for async Run Evaluation startup from mapped call-import batches."""

import sys
import types
from unittest.mock import MagicMock
from uuid import uuid4

from app.models.database import CallImport, CallImportSchema, CallImportSchemaParameter
from app.models.enums import CallImportParameterType, CallImportStatus


def _make_mapped_call_import(db_session, org_id, workspace_id):
    schema = CallImportSchema(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        name="Test schema",
    )
    db_session.add(schema)
    db_session.flush()
    db_session.add(
        CallImportSchemaParameter(
            id=uuid4(),
            schema_id=schema.id,
            name="conversation_id",
            type=CallImportParameterType.CONVERSATION_ID.value,
            is_required=True,
            ordering=0,
        )
    )
    db_session.add(
        CallImportSchemaParameter(
            id=uuid4(),
            schema_id=schema.id,
            name="recording_url",
            type=CallImportParameterType.RECORDING_URL.value,
            is_required=True,
            ordering=1,
        )
    )
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        schema_id=schema.id,
        source_s3_key="org/test/source.csv",
        source_format="csv",
        original_filename="source.csv",
        column_mapping={},
        parameter_mapping={
            "conversation_id": "CallID",
            "recording_url": "Recording URL",
        },
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.MAPPED,
    )
    db_session.add(call_import)
    db_session.commit()
    return call_import


def _make_transcript_only_mapped_call_import(db_session, org_id, workspace_id):
    """Mapped batch whose schema omits recording_url (conversation_id only)."""
    schema = CallImportSchema(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        name="Transcript only",
    )
    db_session.add(schema)
    db_session.flush()
    db_session.add(
        CallImportSchemaParameter(
            id=uuid4(),
            schema_id=schema.id,
            name="conversation_id",
            type=CallImportParameterType.CONVERSATION_ID.value,
            is_required=True,
            ordering=0,
        )
    )
    db_session.add(
        CallImportSchemaParameter(
            id=uuid4(),
            schema_id=schema.id,
            name="transcript",
            type=CallImportParameterType.TRANSCRIPT.value,
            is_required=False,
            ordering=1,
        )
    )
    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace_id,
        schema_id=schema.id,
        source_s3_key="org/test/source.csv",
        source_format="csv",
        original_filename="source.csv",
        column_mapping={},
        parameter_mapping={
            "conversation_id": "CallID",
            "transcript": "Transcript",
        },
        total_rows=0,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.MAPPED,
    )
    db_session.add(call_import)
    db_session.commit()
    return call_import


def test_create_evaluation_from_mapped_enqueues_async_materialization(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    monkeypatch,
):
    from tests.test_api.test_call_import_evaluations import (
        _eval_body,
        _make_metric,
    )

    monkeypatch.setattr(
        "app.api.v1.routes.call_imports._ensure_blob_storage_enabled",
        lambda: None,
    )

    metric = _make_metric(db_session, org_id)
    workspace = metric.workspace_id
    call_import = _make_mapped_call_import(db_session, org_id, workspace)

    delay_mock = MagicMock(return_value=MagicMock(id="async-task"))
    fake_bulk_ops = types.ModuleType("app.workers.tasks.call_import_bulk_ops")
    fake_bulk_ops.materialize_mapped_call_import_evaluation_task = MagicMock(
        delay=delay_mock,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.workers.tasks.call_import_bulk_ops",
        fake_bulk_ops,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["total_rows"] == 0

    delay_mock.assert_called_once()
    args, kwargs = delay_mock.call_args
    assert args[0] == str(call_import.id)
    assert args[1] == str(org_id)
    assert args[2] == str(workspace)
    assert args[3] == body["id"]
    assert kwargs.get("transcribe_overwrite") is False

    db_session.expire_all()
    refreshed_import = (
        db_session.query(CallImport)
        .filter(CallImport.id == call_import.id)
        .first()
    )
    assert refreshed_import.status == CallImportStatus.PROCESSING


def test_create_diarised_evaluation_rejects_schema_without_recording_url(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
):
    from tests.test_api.test_call_import_evaluations import (
        _eval_body,
        _make_metric,
    )

    metric = _make_metric(db_session, org_id)
    workspace = metric.workspace_id
    call_import = _make_transcript_only_mapped_call_import(
        db_session, org_id, workspace
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 409, response.text
    assert "recording_url" in response.json()["detail"].lower()


def test_create_evaluation_from_mapped_stamps_parent_last_updated_by(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    monkeypatch,
):
    from tests.test_api.test_call_import_evaluations import (
        _eval_body,
        _make_metric,
    )

    monkeypatch.setattr(
        "app.api.v1.routes.call_imports._ensure_blob_storage_enabled",
        lambda: None,
    )

    metric = _make_metric(db_session, org_id)
    workspace = metric.workspace_id
    call_import = _make_mapped_call_import(db_session, org_id, workspace)
    call_import.last_updated_by_user_id = None
    db_session.commit()

    delay_mock = MagicMock(return_value=MagicMock(id="async-task"))
    fake_bulk_ops = types.ModuleType("app.workers.tasks.call_import_bulk_ops")
    fake_bulk_ops.materialize_mapped_call_import_evaluation_task = MagicMock(
        delay=delay_mock,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.workers.tasks.call_import_bulk_ops",
        fake_bulk_ops,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
    assert response.status_code == 202, response.text

    detail = authenticated_client.get(f"/api/v1/call-imports/{call_import.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["last_updated_by_email"] == "owner@example.com"

):
    from tests.test_api.test_call_import_evaluations import (
        _eval_body,
        _make_metric,
    )

<<<<<<< C:\Users\steja\AppData\Local\Temp\efficientai-merge\ours_tests_test_api_test_call_import_evaluations_mapped_async.py
    metric = _make_metric(db_session, org_id)
    workspace = metric.workspace_id
    call_import = _make_transcript_only_mapped_call_import(
        db_session, org_id, workspace
=======
    monkeypatch.setattr(
        "app.api.v1.routes.call_imports._ensure_blob_storage_enabled",
        lambda: None,
    )

    metric = _make_metric(db_session, org_id)
    workspace = metric.workspace_id
    call_import = _make_mapped_call_import(db_session, org_id, workspace)
    call_import.last_updated_by_user_id = None
    db_session.commit()

    delay_mock = MagicMock(return_value=MagicMock(id="async-task"))
    fake_bulk_ops = types.ModuleType("app.workers.tasks.call_import_bulk_ops")
    fake_bulk_ops.materialize_mapped_call_import_evaluation_task = MagicMock(
        delay=delay_mock,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.workers.tasks.call_import_bulk_ops",
        fake_bulk_ops,
>>>>>>> C:\Users\steja\AppData\Local\Temp\efficientai-merge\theirs_tests_test_api_test_call_import_evaluations_mapped_async.py
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations",
        json=_eval_body([metric.id]),
    )
<<<<<<< C:\Users\steja\AppData\Local\Temp\efficientai-merge\ours_tests_test_api_test_call_import_evaluations_mapped_async.py
    assert response.status_code == 409, response.text
    assert "recording_url" in response.json()["detail"].lower()
=======
    assert response.status_code == 202, response.text

    detail = authenticated_client.get(f"/api/v1/call-imports/{call_import.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["last_updated_by_email"] == "owner@example.com"
>>>>>>> C:\Users\steja\AppData\Local\Temp\efficientai-merge\theirs_tests_test_api_test_call_import_evaluations_mapped_async.py
