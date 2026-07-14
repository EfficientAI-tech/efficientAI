"""API tests for async whole-batch call-import deletion."""

import sys
import types
from uuid import UUID, uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportSchema,
    CallImportSchemaParameter,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportParameterType, CallImportStatus


@pytest.fixture(autouse=True)
def stub_call_import_worker():
    """Replace fair import dispatch scheduling so upload routes don't need Redis."""
    fake_module = types.ModuleType("app.workers.concurrency.fair_import_dispatch")
    fake_module.schedule_fair_import_dispatch = lambda *_a, **_kw: None
    previous = sys.modules.get("app.workers.concurrency.fair_import_dispatch")
    sys.modules["app.workers.concurrency.fair_import_dispatch"] = fake_module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("app.workers.concurrency.fair_import_dispatch", None)
        else:
            sys.modules["app.workers.concurrency.fair_import_dispatch"] = previous


@pytest.fixture
def exotel_integration(db_session, org_id, seed_org):
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
    db_session.commit()
    return integration


@pytest.fixture
def upload_schema(db_session, org_id, seed_org):
    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    schema = CallImportSchema(
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Async Delete Test Schema",
    )
    db_session.add(schema)
    db_session.flush()
    for idx, (name, ptype) in enumerate(
        [
            ("conversation_id", CallImportParameterType.CONVERSATION_ID),
            ("recording_date", CallImportParameterType.RECORDING_DATE),
            ("recording_url", CallImportParameterType.RECORDING_URL),
            ("transcript", CallImportParameterType.TRANSCRIPT),
        ]
    ):
        db_session.add(
            CallImportSchemaParameter(
                schema_id=schema.id,
                name=name,
                type=ptype.value,
                is_required=name in {"conversation_id", "recording_date", "recording_url"},
                ordering=idx,
            )
        )
    db_session.commit()
    db_session.refresh(schema)
    return schema


def _upload(client, *, schema_id):
    files = {"file": ("test.csv", _csv_bytes(), "text/csv")}
    first_cfg = client.get("/api/v1/telephony/configs").json()[0]
    data = {
        "schema_id": str(schema_id),
        "parameter_mapping": (
            '{"conversation_id":"CallID","recording_date":"Recording Date",'
            '"recording_url":"Recording URL","transcript":"Transcript"}'
        ),
        "skipped_columns": "[]",
        "provider": first_cfg["provider"],
        "telephony_integration_id": first_cfg["id"],
    }
    return client.post("/api/v1/call-imports/upload", files=files, data=data)


def _csv_bytes():
    return (
        "CallID,Recording Date,Recording URL,Transcript\n"
        "call-1,18/05/2026,https://example.com/r.mp3,hello\n"
    ).encode("utf-8")


def test_delete_call_import_returns_202_and_sets_deleting(
    authenticated_client,
    db_session,
    exotel_integration,
    upload_schema,
):
    enqueue_calls: list[tuple[str, str]] = []
    fake_module = sys.modules["app.workers.tasks.call_import_bulk_ops"]

    class _CaptureTask:
        @staticmethod
        def delay(call_import_id, organization_id):
            enqueue_calls.append((call_import_id, organization_id))
            return types.SimpleNamespace(id="fake-delete-task")

    fake_module.delete_call_import_task = _CaptureTask()

    uploaded = _upload(authenticated_client, schema_id=upload_schema.id)
    assert uploaded.status_code == 202
    call_import_id = uploaded.json()["id"]

    response = authenticated_client.delete(f"/api/v1/call-imports/{call_import_id}")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert body["id"] == call_import_id
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0][0] == call_import_id

    row = (
        db_session.query(CallImport)
        .filter(CallImport.id == UUID(call_import_id))
        .first()
    )
    assert row is not None
    assert row.status == CallImportStatus.DELETING


def test_delete_call_import_idempotent_while_deleting(
    authenticated_client,
    db_session,
    exotel_integration,
    upload_schema,
):
    enqueue_calls: list[str] = []
    fake_module = sys.modules["app.workers.tasks.call_import_bulk_ops"]

    class _CaptureTask:
        @staticmethod
        def delay(call_import_id, organization_id):
            enqueue_calls.append(call_import_id)
            return types.SimpleNamespace(id="fake-delete-task")

    fake_module.delete_call_import_task = _CaptureTask()

    uploaded = _upload(authenticated_client, schema_id=upload_schema.id)
    call_import_id = uploaded.json()["id"]

    first = authenticated_client.delete(f"/api/v1/call-imports/{call_import_id}")
    second = authenticated_client.delete(f"/api/v1/call-imports/{call_import_id}")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "accepted"
    assert len(enqueue_calls) == 1


def test_delete_missing_call_import_returns_completed(
    authenticated_client,
):
    missing_id = "00000000-0000-0000-0000-000000000099"
    response = authenticated_client.delete(f"/api/v1/call-imports/{missing_id}")
    assert response.status_code == 202
    assert response.json()["status"] == "completed"
