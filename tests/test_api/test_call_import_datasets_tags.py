"""API tests for call-import dataset & tag flows.

Covers the additions in Part B of the multi-key/import-dataset plan:

* free-text ``dataset`` column on ``call_imports`` (high-level filter),
* many-to-many ``tags`` via ``call_import_tags`` /
  ``call_import_tag_assignments``,
* upload accepts ``dataset`` + ``tag_ids``,
* list filter supports both, with AND semantics for multiple tag ids,
* PATCH endpoint can edit dataset / tags after upload,
* ``GET /call-imports/datasets`` returns distinct labels.
"""

import io
import sys
import types
from uuid import UUID, uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportSchema,
    CallImportSchemaParameter,
    CallImportTag,
    CallImportTagAssignment,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportParameterType


@pytest.fixture(autouse=True)
def stub_call_import_worker():
    """Replace the Celery task that the upload route enqueues.

    Each test creates a CallImport via ``POST /upload``; the route then
    imports ``process_call_import_row_task`` and calls ``.delay()``. We
    swap in a no-op so the tests don't require Celery / Redis.
    """
    fake_module = types.ModuleType("app.workers.tasks.process_call_import_row")

    class _Task:
        @staticmethod
        def delay(*_args, **_kwargs):
            class _Result:
                id = "fake-task-id"

            return _Result()

    fake_module.process_call_import_row_task = _Task()
    previous = sys.modules.get("app.workers.tasks.process_call_import_row")
    sys.modules["app.workers.tasks.process_call_import_row"] = fake_module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("app.workers.tasks.process_call_import_row", None)
        else:
            sys.modules["app.workers.tasks.process_call_import_row"] = previous


@pytest.fixture
def exotel_integration(db_session, org_id, seed_org):
    """An active Exotel telephony integration is required by the upload route."""
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
    """A minimal three-parameter schema in the default workspace."""
    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    schema = CallImportSchema(
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Datasets/Tags Test Schema",
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
                is_required=name in {"conversation_id", "recording_date"},
                ordering=idx,
            )
        )
    db_session.commit()
    db_session.refresh(schema)
    return schema


def _csv_bytes(rows=None):
    if rows is None:
        rows = [("call-1", "2026-05-18", "https://example.com/r.mp3", "hello")]
    buf = io.StringIO()
    buf.write("CallID,Recording Date,Recording URL,Transcript\n")
    for call_id, recording_date, url, transcript in rows:
        buf.write(f"{call_id},{recording_date},{url},{transcript}\n")
    return buf.getvalue().encode("utf-8")


def _upload(client, *, schema_id, dataset=None, tag_ids=None, rows=None):
    files = {"file": ("test.csv", _csv_bytes(rows), "text/csv")}
    first_cfg = client.get("/api/v1/telephony/configs").json()[0]
    # New upload contract: schema_id + parameter_mapping (parameter
    # name -> CSV header). The minimal schema fixture maps the three
    # classic system fields, which line up with the CSV headers built
    # by ``_csv_bytes``.
    data = {
        "provider": first_cfg["provider"],
        "telephony_integration_id": first_cfg["id"],
        "schema_id": str(schema_id),
        "parameter_mapping": (
            '{"conversation_id":"CallID","recording_date":"Recording Date",'
            '"transcript":"Transcript",'
            '"recording_url":"Recording URL"}'
        ),
        "skipped_columns": "[]",
    }
    if dataset is not None:
        data["dataset"] = dataset
    if tag_ids:
        data.setdefault("tag_ids", []).extend(str(t) for t in tag_ids)
    response = client.post("/api/v1/call-imports/upload", files=files, data=data)
    return response


def _create_tag(client, name, color=None):
    payload = {"name": name}
    if color:
        payload["color"] = color
    response = client.post("/api/v1/call-import-tags", json=payload)
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_upload_persists_dataset_and_tags(
    authenticated_client, exotel_integration, upload_schema
):
    tag_a = _create_tag(authenticated_client, "high-priority", color="#ff0000")
    tag_b = _create_tag(authenticated_client, "qa")

    response = _upload(
        authenticated_client,
        schema_id=upload_schema.id,
        dataset="march-2026",
        tag_ids=[tag_a["id"], tag_b["id"]],
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["dataset"] == "march-2026"
    returned_tag_ids = {tag["id"] for tag in body["tags"]}
    assert returned_tag_ids == {tag_a["id"], tag_b["id"]}


def test_upload_blank_dataset_normalised_to_null(
    authenticated_client, exotel_integration, upload_schema
):
    response = _upload(authenticated_client, schema_id=upload_schema.id, dataset="   ")
    assert response.status_code == 202
    assert response.json()["dataset"] is None


def test_upload_unknown_tag_id_rejected(
    authenticated_client, exotel_integration, upload_schema
):
    response = _upload(
        authenticated_client, schema_id=upload_schema.id, tag_ids=[uuid4()]
    )
    assert response.status_code == 400
    assert "Unknown call_import_tag id" in response.json()["detail"]


def test_list_filters_by_dataset(
    authenticated_client, exotel_integration, upload_schema
):
    _upload(authenticated_client, schema_id=upload_schema.id, dataset="alpha")
    _upload(authenticated_client, schema_id=upload_schema.id, dataset="beta")
    _upload(authenticated_client, schema_id=upload_schema.id)  # no dataset

    listing = authenticated_client.get(
        "/api/v1/call-imports", params={"dataset": "alpha"}
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["dataset"] == "alpha"


def test_list_filters_by_multiple_tags_and_semantics(
    authenticated_client, exotel_integration, upload_schema
):
    tag_a = _create_tag(authenticated_client, "alpha")
    tag_b = _create_tag(authenticated_client, "beta")

    _upload(authenticated_client, schema_id=upload_schema.id, tag_ids=[tag_a["id"]])
    _upload(authenticated_client, schema_id=upload_schema.id, tag_ids=[tag_b["id"]])
    both = _upload(
        authenticated_client,
        schema_id=upload_schema.id,
        tag_ids=[tag_a["id"], tag_b["id"]],
    )
    assert both.status_code == 202

    response = authenticated_client.get(
        "/api/v1/call-imports",
        params=[("tag_id", tag_a["id"]), ("tag_id", tag_b["id"])],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == both.json()["id"]


def test_datasets_endpoint_returns_distinct_sorted_labels(
    authenticated_client, exotel_integration, upload_schema
):
    _upload(authenticated_client, schema_id=upload_schema.id, dataset="z-set")
    _upload(authenticated_client, schema_id=upload_schema.id, dataset="a-set")
    _upload(authenticated_client, schema_id=upload_schema.id, dataset="a-set")
    _upload(authenticated_client, schema_id=upload_schema.id)  # NULL -> excluded

    response = authenticated_client.get("/api/v1/call-imports/datasets")
    assert response.status_code == 200
    assert response.json() == ["a-set", "z-set"]


def test_patch_updates_dataset_and_tags(
    authenticated_client, exotel_integration, upload_schema, db_session
):
    initial = _upload(
        authenticated_client, schema_id=upload_schema.id, dataset="old-set"
    ).json()
    tag_a = _create_tag(authenticated_client, "new-tag")

    response = authenticated_client.patch(
        f"/api/v1/call-imports/{initial['id']}",
        json={"dataset": "new-set", "tag_ids": [tag_a["id"]]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "new-set"
    assert {tag["id"] for tag in body["tags"]} == {tag_a["id"]}

    # Clear both via empty payloads.
    response = authenticated_client.patch(
        f"/api/v1/call-imports/{initial['id']}",
        json={"dataset": "", "tag_ids": []},
    )
    assert response.status_code == 200
    assert response.json()["dataset"] is None
    assert response.json()["tags"] == []

    # And confirm the join rows actually went away.
    leftover_assignments = (
        db_session.query(CallImportTagAssignment)
        .filter(CallImportTagAssignment.call_import_id == UUID(initial["id"]))
        .count()
    )
    assert leftover_assignments == 0


def test_tag_crud_roundtrip(authenticated_client):
    created = _create_tag(authenticated_client, "scratch", color="#abcdef")
    listed = authenticated_client.get("/api/v1/call-import-tags").json()
    assert any(tag["id"] == created["id"] for tag in listed)

    updated = authenticated_client.patch(
        f"/api/v1/call-import-tags/{created['id']}",
        json={"name": "scratch-renamed", "color": None},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "scratch-renamed"
    assert updated.json()["color"] is None

    deleted = authenticated_client.delete(f"/api/v1/call-import-tags/{created['id']}")
    assert deleted.status_code in (200, 204)

    final = authenticated_client.get("/api/v1/call-import-tags").json()
    assert all(tag["id"] != created["id"] for tag in final)
