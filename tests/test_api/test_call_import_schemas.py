"""API tests for the Call Import Schemas CRUD router.

Covers the contract surfaced by ``app/api/v1/routes/call_import_schemas.py``:

* schema list / detail responses include parameters + ``usage_count``,
* create rejects payloads missing the mandatory ``conversation_id``
  parameter or carrying duplicate parameter names,
* update fully replaces the parameter list,
* delete refuses (by default) to drop a schema that's still wired to a
  CallImport batch, but ``?force=true`` detaches those batches and
  removes the schema + its parameters.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.models.database import (
    CallImport,
    CallImportSchema,
    CallImportSchemaParameter,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportStatus


def _default_workspace(db_session, org_id) -> Workspace:
    ws = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    assert ws is not None, "default workspace must be seeded by conftest"
    return ws


def _minimal_payload(name: str = "Standard QA") -> dict:
    """Standard schema (conv id + recording date/url + transcript)."""
    return {
        "name": name,
        "description": "For voice QA pipelines",
        "parameters": [
            {
                "name": "conversation_id",
                "type": "conversation_id",
                "description": "External call id",
                "is_required": True,
            },
            {
                "name": "recording_url",
                "type": "recording_url",
                "is_required": False,
            },
            {
                "name": "recording_date",
                "type": "recording_date",
                "is_required": True,
            },
            {
                "name": "transcript",
                "type": "transcript",
                "is_required": False,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_schema_happy_path(authenticated_client, db_session, org_id, seed_org):
    response = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Standard QA"
    assert body["description"] == "For voice QA pipelines"
    assert body["usage_count"] == 0
    # Parameters come back in the order they were submitted; ordering is
    # stamped server-side.
    names = [p["name"] for p in body["parameters"]]
    assert names == [
        "conversation_id",
        "recording_url",
        "recording_date",
        "transcript",
    ]
    assert [p["ordering"] for p in body["parameters"]] == [0, 1, 2, 3]
    # The DB row is real (UUID parses, parameters persisted).
    schema = (
        db_session.query(CallImportSchema)
        .filter(CallImportSchema.id == UUID(body["id"]))
        .one()
    )
    assert len(schema.parameters) == 4


def test_create_schema_forces_conversation_id_required(
    authenticated_client, db_session, org_id, seed_org
):
    """Even if the client sends is_required=False for conversation_id,
    the server stamps it back to True (the parameter is mandatory by
    definition). recording_date stays optional when the client omits it."""
    payload = _minimal_payload()
    payload["parameters"][0]["is_required"] = False
    payload["parameters"][2]["is_required"] = False

    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    conv_param = next(
        p for p in body["parameters"] if p["type"] == "conversation_id"
    )
    date_param = next(
        p for p in body["parameters"] if p["type"] == "recording_date"
    )
    assert conv_param["is_required"] is True
    assert date_param["is_required"] is False


def test_create_schema_rejects_missing_conversation_id(
    authenticated_client, db_session, org_id, seed_org
):
    payload = {
        "name": "Bad Schema",
        "parameters": [
            {"name": "recording_date", "type": "recording_date", "is_required": True},
            {"name": "transcript", "type": "transcript", "is_required": True},
            {"name": "audio", "type": "recording_url"},
        ],
    }
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 422
    assert "conversation_id" in response.text.lower()


def test_create_schema_accepts_missing_recording_date(
    authenticated_client, db_session, org_id, seed_org
):
    payload = _minimal_payload()
    payload["parameters"] = [
        p for p in payload["parameters"] if p["type"] != "recording_date"
    ]
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 201, response.text
    names = [p["name"] for p in response.json()["parameters"]]
    assert "recording_date" not in names


def test_create_schema_rejects_two_recording_date_params(
    authenticated_client, db_session, org_id, seed_org
):
    payload = _minimal_payload()
    payload["parameters"].append(
        {"name": "call_date", "type": "recording_date"}
    )
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 422
    assert "recording_date" in response.text.lower()


def test_create_schema_rejects_duplicate_conversation_id(
    authenticated_client, db_session, org_id, seed_org
):
    payload = _minimal_payload()
    payload["parameters"].append(
        {"name": "external_id", "type": "conversation_id", "is_required": True}
    )
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 422
    assert "conversation_id" in response.text.lower()


def test_create_schema_rejects_duplicate_parameter_names(
    authenticated_client, db_session, org_id, seed_org
):
    payload = _minimal_payload()
    # Case-insensitive collision: "Transcript" vs the already-present
    # "transcript" entry.
    payload["parameters"].append(
        {"name": "Transcript", "type": "text"}
    )
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 422
    assert "duplicate parameter name" in response.text.lower()


def test_create_schema_rejects_two_recording_url_params(
    authenticated_client, db_session, org_id, seed_org
):
    payload = _minimal_payload()
    payload["parameters"].append(
        {"name": "backup_recording", "type": "recording_url"}
    )
    response = authenticated_client.post("/api/v1/call-import-schemas", json=payload)
    assert response.status_code == 422
    assert "recording_url" in response.text.lower()


def test_create_schema_rejects_empty_parameter_list(
    authenticated_client, db_session, org_id, seed_org
):
    response = authenticated_client.post(
        "/api/v1/call-import-schemas",
        json={"name": "Empty", "parameters": []},
    )
    assert response.status_code == 422


def test_create_schema_rejects_duplicate_name_in_workspace(
    authenticated_client, db_session, org_id, seed_org
):
    first = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload("Twin")
    )
    assert first.status_code == 201
    second = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload("Twin")
    )
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"].lower()


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------


def test_list_schemas_returns_alphabetical_with_usage(
    authenticated_client, db_session, org_id, seed_org
):
    authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload("Zeta")
    )
    alpha = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload("Alpha")
    ).json()

    # Wire a CallImport batch to the Alpha schema so usage_count becomes 1.
    workspace = _default_workspace(db_session, org_id)
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
    db_session.add(
        CallImport(
            id=uuid4(),
            organization_id=org_id,
            workspace_id=workspace.id,
            schema_id=UUID(alpha["id"]),
            provider="exotel",
            telephony_integration_id=integration.id,
            original_filename="x.csv",
            total_rows=0,
            completed_rows=0,
            failed_rows=0,
            status=CallImportStatus.COMPLETED,
        )
    )
    db_session.commit()

    response = authenticated_client.get("/api/v1/call-import-schemas")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    names = [item["name"] for item in body["items"]]
    assert names == ["Alpha", "Zeta"]
    usage_by_name = {item["name"]: item["usage_count"] for item in body["items"]}
    assert usage_by_name == {"Alpha": 1, "Zeta": 0}


def test_get_schema_detail_returns_parameters(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()
    response = authenticated_client.get(
        f"/api/v1/call-import-schemas/{created['id']}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert [p["name"] for p in body["parameters"]] == [
        "conversation_id",
        "recording_url",
        "recording_date",
        "transcript",
    ]


def test_get_schema_404_for_unknown_id(authenticated_client, db_session, org_id, seed_org):
    response = authenticated_client.get(f"/api/v1/call-import-schemas/{uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_schema_replaces_parameters(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()

    new_params = [
        {"name": "conversation_id", "type": "conversation_id", "is_required": True},
        {"name": "recording_date", "type": "recording_date", "is_required": True},
        {"name": "agent_name", "type": "text"},
        {"name": "latency_ms", "type": "number"},
    ]
    response = authenticated_client.patch(
        f"/api/v1/call-import-schemas/{created['id']}",
        json={"name": "Renamed", "parameters": new_params},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Renamed"
    names = [p["name"] for p in body["parameters"]]
    assert names == ["conversation_id", "recording_date", "agent_name", "latency_ms"]

    # The old parameters were actually deleted, not appended.
    persisted = (
        db_session.query(CallImportSchemaParameter)
        .filter(CallImportSchemaParameter.schema_id == UUID(created["id"]))
        .all()
    )
    assert len(persisted) == 4
    assert {p.name for p in persisted} == {
        "conversation_id",
        "recording_date",
        "agent_name",
        "latency_ms",
    }


def test_update_schema_metadata_only_keeps_parameters(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()

    response = authenticated_client.patch(
        f"/api/v1/call-import-schemas/{created['id']}",
        json={"description": "Updated description"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated description"
    # Parameters untouched.
    assert [p["name"] for p in body["parameters"]] == [
        "conversation_id",
        "recording_url",
        "recording_date",
        "transcript",
    ]


def test_update_schema_rejects_dropping_conversation_id(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()

    response = authenticated_client.patch(
        f"/api/v1/call-import-schemas/{created['id']}",
        json={
            "parameters": [
                {"name": "transcript", "type": "transcript"},
                {"name": "recording_date", "type": "recording_date"},
                {"name": "agent_name", "type": "text"},
            ]
        },
    )
    assert response.status_code == 422
    assert "conversation_id" in response.text.lower()


def test_update_schema_accepts_dropping_recording_date(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()

    response = authenticated_client.patch(
        f"/api/v1/call-import-schemas/{created['id']}",
        json={
            "parameters": [
                {"name": "conversation_id", "type": "conversation_id"},
                {"name": "agent_name", "type": "text"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    names = [p["name"] for p in response.json()["parameters"]]
    assert names == ["conversation_id", "agent_name"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_schema_succeeds_when_not_in_use(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()
    schema_id = UUID(created["id"])

    response = authenticated_client.delete(
        f"/api/v1/call-import-schemas/{created['id']}"
    )
    assert response.status_code == 204

    assert (
        db_session.query(CallImportSchema)
        .filter(CallImportSchema.id == schema_id)
        .first()
        is None
    )
    # Children went away via the FK cascade.
    assert (
        db_session.query(CallImportSchemaParameter)
        .filter(CallImportSchemaParameter.schema_id == schema_id)
        .count()
        == 0
    )


def test_delete_schema_refuses_when_referenced_by_call_import(
    authenticated_client, db_session, org_id, seed_org
):
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()

    workspace = _default_workspace(db_session, org_id)
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
    db_session.add(
        CallImport(
            id=uuid4(),
            organization_id=org_id,
            workspace_id=workspace.id,
            schema_id=UUID(created["id"]),
            provider="exotel",
            telephony_integration_id=integration.id,
            original_filename="batch.csv",
            total_rows=0,
            completed_rows=0,
            failed_rows=0,
            status=CallImportStatus.COMPLETED,
        )
    )
    db_session.commit()

    response = authenticated_client.delete(
        f"/api/v1/call-import-schemas/{created['id']}"
    )
    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "in use" in detail
    # The error nudges the caller toward the force=true escape hatch
    # so the UI can offer it without guessing at API semantics.
    assert "force=true" in detail

    # Schema still in DB after the failed delete.
    assert (
        db_session.query(CallImportSchema)
        .filter(CallImportSchema.id == UUID(created["id"]))
        .first()
        is not None
    )


def test_force_delete_schema_detaches_in_use_batches(
    authenticated_client, db_session, org_id, seed_org
):
    """``?force=true`` lets the user drop a schema even when batches
    still reference it. The batches stay (they carry their own
    ``parameter_mapping`` snapshot) but their ``schema_id`` is NULLed
    so the FK no longer blocks the delete, and downstream rendering
    falls back to the legacy/free-form mapping path."""
    created = authenticated_client.post(
        "/api/v1/call-import-schemas", json=_minimal_payload()
    ).json()
    schema_id = UUID(created["id"])

    workspace = _default_workspace(db_session, org_id)
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
    batch_id = uuid4()
    db_session.add(
        CallImport(
            id=batch_id,
            organization_id=org_id,
            workspace_id=workspace.id,
            schema_id=schema_id,
            provider="exotel",
            telephony_integration_id=integration.id,
            original_filename="batch.csv",
            parameter_mapping={"conversation_id": "CallID"},
            total_rows=0,
            completed_rows=0,
            failed_rows=0,
            status=CallImportStatus.COMPLETED,
        )
    )
    db_session.commit()

    response = authenticated_client.delete(
        f"/api/v1/call-import-schemas/{created['id']}?force=true"
    )
    assert response.status_code == 204, response.text

    # Schema (and its children) are gone.
    assert (
        db_session.query(CallImportSchema)
        .filter(CallImportSchema.id == schema_id)
        .first()
        is None
    )
    assert (
        db_session.query(CallImportSchemaParameter)
        .filter(CallImportSchemaParameter.schema_id == schema_id)
        .count()
        == 0
    )

    # The batch survived but is now schema-less. Its
    # ``parameter_mapping`` snapshot is preserved so the detail /
    # export endpoints can still render the rows.
    batch = (
        db_session.query(CallImport)
        .filter(CallImport.id == batch_id)
        .one()
    )
    assert batch.schema_id is None
    assert batch.parameter_mapping == {"conversation_id": "CallID"}


def test_delete_schema_404_for_unknown_id(
    authenticated_client, db_session, org_id, seed_org
):
    response = authenticated_client.delete(f"/api/v1/call-import-schemas/{uuid4()}")
    assert response.status_code == 404
