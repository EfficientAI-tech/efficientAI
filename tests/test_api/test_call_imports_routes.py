"""Tests for the schema-driven CSV/Excel parser + /upload route.

Exercises the schema-driven helpers directly (no FastAPI app required)
for the parser-level cases, plus the full upload route for the
end-to-end credential + persistence behavior. Every test that talks to
the router goes through a freshly-created ``CallImportSchema`` so the
new mapping flow stays exercised in lockstep with the route code.
"""

import io
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.routes.call_imports import (
    _delete_s3_objects,
    _parse_csv,
    _parse_xlsx,
    _revoke_pending_tasks,
)
from app.models.database import (
    CallImport,
    CallImportRow,
    CallImportSchema,
    CallImportSchemaParameter,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportParameterType, CallImportRowStatus


# ---------------------------------------------------------------------------
# Parser-level helpers + fixtures (run against the schema-driven API)
# ---------------------------------------------------------------------------


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _param(
    *,
    name: str,
    type_: CallImportParameterType,
    is_required: bool = False,
    ordering: int = 0,
) -> CallImportSchemaParameter:
    """Build a *transient* parameter object the parser is happy with.

    The parser only reads ``name``, ``type``, ``is_required``; we skip
    the DB roundtrip entirely so the unit tests stay hermetic.
    """
    return CallImportSchemaParameter(
        name=name,
        type=type_.value,
        description=None,
        is_required=is_required,
        ordering=ordering,
    )


def _standard_params() -> list[CallImportSchemaParameter]:
    """The "classic" three-column schema (conv id + recording + transcript)."""
    return [
        _param(
            name="conversation_id",
            type_=CallImportParameterType.CONVERSATION_ID,
            is_required=True,
            ordering=0,
        ),
        _param(
            name="recording_url",
            type_=CallImportParameterType.RECORDING_URL,
            ordering=1,
        ),
        _param(
            name="transcript",
            type_=CallImportParameterType.TRANSCRIPT,
            ordering=2,
        ),
    ]


def _standard_mapping() -> dict[str, str]:
    return {
        "conversation_id": "CallID",
        "recording_url": "Recording URL",
        "transcript": "Transcript",
    }


def _standard_skipped() -> list[str]:
    """All three classic source columns are accounted for in the mapping."""
    return []


def test_parse_csv_accepts_canonical_headers():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://api.exotel.com/recordings/abc-1.mp3,Hello world\n"
        "abc-2,https://api.exotel.com/recordings/abc-2.mp3,Another call\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        _standard_mapping(),
        _standard_skipped(),
    )
    assert len(rows) == 2
    assert rows[0]["conversation_id"] == "abc-1"
    assert rows[0]["recording_url"].endswith("abc-1.mp3")
    assert rows[0]["transcript"] == "Hello world"
    assert rows[1]["conversation_id"] == "abc-2"


def test_parse_csv_is_case_insensitive_on_headers():
    csv_text = (
        "callid,recording url,TRANSCRIPT\n"
        "id-1,https://x/recording.mp3,Some transcript\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        _standard_mapping(),
        _standard_skipped(),
    )
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "id-1"
    assert rows[0]["transcript"] == "Some transcript"


def test_parse_csv_rejects_empty_input():
    with pytest.raises(HTTPException) as exc:
        _parse_csv(b"", _standard_params(), _standard_mapping(), _standard_skipped())
    assert exc.value.status_code == 400
    assert "empty" in exc.value.detail.lower()


def test_parse_csv_rejects_missing_mapped_required_header():
    # The schema requires conversation_id but the CSV has no CallID column.
    csv_text = "Recording URL,Transcript\nhttps://x/r.mp3,Some transcript\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(
            _csv_bytes(csv_text),
            _standard_params(),
            _standard_mapping(),
            _standard_skipped(),
        )
    assert exc.value.status_code == 400
    assert "conversation_id" in exc.value.detail.lower()


def test_parse_csv_allows_optional_param_without_mapping():
    csv_text = (
        "CallID,Transcript\n"
        "abc-1,Hello world\n"
    )
    # Drop the recording_url mapping entry so it is treated as "not used".
    mapping = {"conversation_id": "CallID", "transcript": "Transcript"}
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        mapping,
        _standard_skipped(),
    )
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "abc-1"
    assert rows[0]["recording_url"] is None
    assert rows[0]["transcript"] == "Hello world"


def test_parse_csv_rejects_row_missing_conversation_id():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        ",https://x/recording.mp3,Some transcript\n"
    )
    with pytest.raises(HTTPException) as exc:
        _parse_csv(
            _csv_bytes(csv_text),
            _standard_params(),
            _standard_mapping(),
            _standard_skipped(),
        )
    assert exc.value.status_code == 400
    assert "conversation_id" in exc.value.detail.lower()


def test_parse_csv_skips_completely_blank_rows():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,Some transcript\n"
        ",,\n"
        "abc-2,https://x/2.mp3,Other transcript\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        _standard_mapping(),
        _standard_skipped(),
    )
    assert len(rows) == 2
    assert [r["conversation_id"] for r in rows] == ["abc-1", "abc-2"]


def test_parse_csv_strips_utf8_bom():
    csv_text = (
        "\ufeffCallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,T1\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        _standard_mapping(),
        _standard_skipped(),
    )
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "abc-1"


def test_parse_csv_rejects_unhandled_columns():
    # CSV has an extra "AgentName" column that's neither mapped nor
    # marked skipped → 400 so nothing silently drops.
    csv_text = (
        "CallID,Recording URL,Transcript,AgentName\n"
        "abc-1,https://x/r.mp3,hi,alice\n"
    )
    with pytest.raises(HTTPException) as exc:
        _parse_csv(
            _csv_bytes(csv_text),
            _standard_params(),
            _standard_mapping(),
            skipped_columns=[],
        )
    assert exc.value.status_code == 400
    assert "agentname" in exc.value.detail.lower()


def test_parse_csv_accepts_explicitly_skipped_columns():
    csv_text = (
        "CallID,Recording URL,Transcript,AgentName\n"
        "abc-1,https://x/r.mp3,hi,alice\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _standard_params(),
        _standard_mapping(),
        skipped_columns=["AgentName"],
    )
    assert len(rows) == 1
    # Skipped columns do NOT appear in parameter_values.
    assert "AgentName" not in rows[0]["parameter_values"]


def test_parse_csv_with_custom_text_parameter_is_preserved_per_row():
    params = _standard_params() + [
        _param(name="agent_name", type_=CallImportParameterType.TEXT, ordering=3)
    ]
    mapping = {
        **_standard_mapping(),
        "agent_name": "AgentName",
    }
    csv_text = (
        "CallID,Recording URL,Transcript,AgentName\n"
        "conv-1,https://x/r1.mp3,hello there,alice\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), params, mapping, skipped_columns=[])
    assert rows[0]["parameter_values"]["agent_name"] == "alice"
    assert rows[0]["parameter_values"]["conversation_id"] == "conv-1"


def test_parse_csv_coerces_typed_parameter_values():
    params = _standard_params() + [
        _param(name="latency_ms", type_=CallImportParameterType.NUMBER, ordering=3),
        _param(name="answered", type_=CallImportParameterType.BOOLEAN, ordering=4),
    ]
    mapping = {
        **_standard_mapping(),
        "latency_ms": "Latency",
        "answered": "Answered",
    }
    csv_text = (
        "CallID,Recording URL,Transcript,Latency,Answered\n"
        "conv-1,https://x/r.mp3,hi,123.5,true\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), params, mapping, skipped_columns=[])
    assert rows[0]["parameter_values"]["latency_ms"] == 123.5
    assert rows[0]["parameter_values"]["answered"] is True


def test_parse_csv_rejects_invalid_number_cell():
    params = _standard_params() + [
        _param(name="latency_ms", type_=CallImportParameterType.NUMBER, ordering=3),
    ]
    mapping = {**_standard_mapping(), "latency_ms": "Latency"}
    csv_text = (
        "CallID,Recording URL,Transcript,Latency\n"
        "conv-1,https://x/r.mp3,hi,not-a-number\n"
    )
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text), params, mapping, skipped_columns=[])
    assert exc.value.status_code == 400
    assert "not a valid number" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# _revoke_pending_tasks
# ---------------------------------------------------------------------------


def _row(status, task_id="task-x"):
    """Build a row-shaped object with the fields _revoke_pending_tasks reads."""
    return SimpleNamespace(status=status, celery_task_id=task_id)


def test_revoke_pending_tasks_only_targets_in_flight_rows():
    rows = [
        _row(CallImportRowStatus.PENDING, "t1"),
        _row(CallImportRowStatus.PROCESSING, "t2"),
        _row(CallImportRowStatus.COMPLETED, "t3"),
        _row(CallImportRowStatus.FAILED, "t4"),
        _row(CallImportRowStatus.PENDING, None),
    ]

    fake_celery = types.ModuleType("app.workers.celery_app")
    fake_celery.celery_app = SimpleNamespace(control=MagicMock())

    with patch.dict(sys.modules, {"app.workers.celery_app": fake_celery}):
        _revoke_pending_tasks(rows)

    fake_celery.celery_app.control.revoke.assert_called_once_with(
        ["t1", "t2"], terminate=False
    )


def test_revoke_pending_tasks_swallows_celery_failures():
    rows = [_row(CallImportRowStatus.PENDING, "t1")]

    fake_celery = types.ModuleType("app.workers.celery_app")
    fake_celery.celery_app = SimpleNamespace(
        control=SimpleNamespace(
            revoke=MagicMock(side_effect=RuntimeError("broker down"))
        )
    )

    with patch.dict(sys.modules, {"app.workers.celery_app": fake_celery}):
        _revoke_pending_tasks(rows)


def test_revoke_pending_tasks_noop_for_no_in_flight_rows():
    rows = [_row(CallImportRowStatus.COMPLETED, "t1")]

    fake_celery = types.ModuleType("app.workers.celery_app")
    fake_celery.celery_app = SimpleNamespace(control=MagicMock())

    with patch.dict(sys.modules, {"app.workers.celery_app": fake_celery}):
        _revoke_pending_tasks(rows)

    fake_celery.celery_app.control.revoke.assert_not_called()


# ---------------------------------------------------------------------------
# _delete_s3_objects
# ---------------------------------------------------------------------------


def test_delete_s3_objects_skips_when_s3_disabled():
    fake_s3 = SimpleNamespace(
        is_enabled=lambda: False,
        prefix="",
        delete_keys=MagicMock(),
        delete_keys_by_prefix=MagicMock(),
    )

    with patch(
        "app.services.storage.s3_service.s3_service", fake_s3
    ):
        deleted, errors = _delete_s3_objects(
            organization_id=uuid4(),
            call_import_id=uuid4(),
            rows=[SimpleNamespace(recording_s3_key="k1")],
        )

    assert (deleted, errors) == (0, 0)
    fake_s3.delete_keys.assert_not_called()
    fake_s3.delete_keys_by_prefix.assert_not_called()


def test_delete_s3_objects_deletes_known_keys_and_sweeps_prefix():
    org_id = uuid4()
    import_id = uuid4()

    fake_s3 = SimpleNamespace(
        is_enabled=lambda: True,
        prefix="myprefix/",
        delete_keys=MagicMock(return_value=(2, [])),
        delete_keys_by_prefix=MagicMock(return_value=(1, [])),
    )

    rows = [
        SimpleNamespace(recording_s3_key="myprefix/k1"),
        SimpleNamespace(recording_s3_key="myprefix/k2"),
        SimpleNamespace(recording_s3_key=None),
    ]

    with patch(
        "app.services.storage.s3_service.s3_service", fake_s3
    ):
        deleted, errors = _delete_s3_objects(
            organization_id=org_id,
            call_import_id=import_id,
            rows=rows,
        )

    fake_s3.delete_keys.assert_called_once_with(["myprefix/k1", "myprefix/k2"])
    fake_s3.delete_keys_by_prefix.assert_called_once_with(
        f"myprefix/organizations/{org_id}/call_imports/{import_id}/"
    )
    assert deleted == 3
    assert errors == 0


def test_delete_s3_objects_aggregates_errors_without_raising():
    fake_s3 = SimpleNamespace(
        is_enabled=lambda: True,
        prefix="",
        delete_keys=MagicMock(return_value=(0, [{"Key": "k1", "Code": "AccessDenied"}])),
        delete_keys_by_prefix=MagicMock(return_value=(0, [])),
    )

    with patch(
        "app.services.storage.s3_service.s3_service", fake_s3
    ):
        deleted, errors = _delete_s3_objects(
            organization_id=uuid4(),
            call_import_id=uuid4(),
            rows=[SimpleNamespace(recording_s3_key="k1")],
        )

    assert deleted == 0
    assert errors == 1


def test_delete_s3_objects_treats_bulk_exception_as_full_failure():
    fake_s3 = SimpleNamespace(
        is_enabled=lambda: True,
        prefix="",
        delete_keys=MagicMock(side_effect=RuntimeError("network down")),
        delete_keys_by_prefix=MagicMock(return_value=(0, [])),
    )

    with patch(
        "app.services.storage.s3_service.s3_service", fake_s3
    ):
        deleted, errors = _delete_s3_objects(
            organization_id=uuid4(),
            call_import_id=uuid4(),
            rows=[
                SimpleNamespace(recording_s3_key="k1"),
                SimpleNamespace(recording_s3_key="k2"),
            ],
        )

    assert deleted == 0
    assert errors == 2


# ---------------------------------------------------------------------------
# End-to-end upload route tests (schema-driven path)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_import_worker():
    """Replace the Celery enqueue so route tests don't talk to Redis."""
    fake_module = types.ModuleType("app.workers.tasks.process_call_import_row")

    class _Task:
        @staticmethod
        def delay(*_args, **_kwargs):
            return types.SimpleNamespace(id="fake-task-id")

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


def _seed_integration(db_session, org_id, *, provider="exotel"):
    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider=provider,
        auth_id="enc",
        auth_token="enc",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    db_session.commit()
    return integration


def _default_workspace_id(db_session, org_id) -> UUID:
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    assert ws is not None, "default workspace must be seeded by conftest"
    return ws.id


def _seed_schema(
    db_session,
    org_id,
    workspace_id,
    *,
    name="Standard QA",
    extras: list[dict] | None = None,
) -> CallImportSchema:
    """Persist a schema with the classic three parameters plus optional extras."""
    schema = CallImportSchema(
        organization_id=org_id,
        workspace_id=workspace_id,
        name=name,
        description=None,
    )
    db_session.add(schema)
    db_session.flush()
    params = [
        CallImportSchemaParameter(
            schema_id=schema.id,
            name="conversation_id",
            type=CallImportParameterType.CONVERSATION_ID.value,
            is_required=True,
            ordering=0,
        ),
        CallImportSchemaParameter(
            schema_id=schema.id,
            name="recording_url",
            type=CallImportParameterType.RECORDING_URL.value,
            is_required=False,
            ordering=1,
        ),
        CallImportSchemaParameter(
            schema_id=schema.id,
            name="transcript",
            type=CallImportParameterType.TRANSCRIPT.value,
            is_required=False,
            ordering=2,
        ),
    ]
    for idx, extra in enumerate(extras or []):
        params.append(
            CallImportSchemaParameter(
                schema_id=schema.id,
                name=extra["name"],
                type=extra["type"].value,
                is_required=bool(extra.get("is_required", False)),
                ordering=3 + idx,
            )
        )
    for p in params:
        db_session.add(p)
    db_session.commit()
    db_session.refresh(schema)
    return schema


def _upload_payload(
    integration,
    schema_id,
    *,
    provider=None,
    parameter_mapping: dict | None = None,
    skipped_columns: list[str] | None = None,
):
    import json

    return {
        "provider": provider or integration.provider,
        "telephony_integration_id": str(integration.id),
        "schema_id": str(schema_id),
        "parameter_mapping": json.dumps(
            parameter_mapping
            if parameter_mapping is not None
            else {
                "conversation_id": "CallID",
                "recording_url": "Recording URL",
                "transcript": "Transcript",
            }
        ),
        "skipped_columns": json.dumps(skipped_columns or []),
    }


def _csv(rows=(("call-1", "https://x/recording.mp3", "hi there"),)):
    buf = io.StringIO()
    buf.write("CallID,Recording URL,Transcript\n")
    for call_id, url, transcript in rows:
        buf.write(f"{call_id},{url},{transcript}\n")
    return ("rows.csv", buf.getvalue().encode("utf-8"), "text/csv")


def test_upload_rejects_when_provider_does_not_match_integration(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id, provider="exotel")
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, schema.id, provider="plivo"),
    )
    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()


def test_upload_rejects_when_credential_unknown(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    payload = _upload_payload(integration, schema.id)
    payload["telephony_integration_id"] = str(uuid4())
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=payload,
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_upload_rejects_inactive_credential(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    integration.is_active = False
    db_session.commit()
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, schema.id),
    )
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


def test_upload_rejects_invalid_parameter_mapping_json(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    payload = _upload_payload(integration, schema.id)
    payload["parameter_mapping"] = "{not-json}"
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=payload,
    )
    assert response.status_code == 400
    assert "valid json" in response.json()["detail"].lower()


def test_upload_rejects_unknown_schema(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, uuid4()),
    )
    assert response.status_code == 400
    assert "schema not found" in response.json()["detail"].lower()


def test_upload_rejects_when_required_parameter_unmapped(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    # Map only the optional fields; conversation_id is left out so the
    # required-parameter check trips before we even read the file.
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(
            integration,
            schema.id,
            parameter_mapping={
                "transcript": "Transcript",
                "recording_url": "Recording URL",
            },
            skipped_columns=["CallID"],
        ),
    )
    assert response.status_code == 400
    assert "conversation_id" in response.json()["detail"].lower()


def test_upload_rejects_when_mapped_column_absent_from_csv(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(
            integration,
            schema.id,
            parameter_mapping={
                "conversation_id": "MissingId",
                "recording_url": "Recording URL",
                "transcript": "Transcript",
            },
        ),
    )
    assert response.status_code == 400
    assert "missingid" in response.json()["detail"].lower()


def test_upload_persists_parameter_mapping_and_rows(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))

    csv_rows = (
        ("call-a", "https://x/a.mp3", "hello a"),
        ("call-b", "https://x/b.mp3", "hello b"),
    )
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv(rows=csv_rows)},
        data=_upload_payload(integration, schema.id),
    )
    assert response.status_code == 202, response.text
    call_import_id = UUID(response.json()["id"])

    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.telephony_integration_id == integration.id
    assert call_import.schema_id == schema.id
    assert call_import.parameter_mapping == {
        "conversation_id": "CallID",
        "recording_url": "Recording URL",
        "transcript": "Transcript",
    }
    # Legacy mapping columns must be empty for new schema-driven uploads.
    assert call_import.column_mapping == {}
    assert call_import.extra_columns == []
    assert call_import.custom_column_mapping == {}

    rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index)
        .all()
    )
    assert [r.conversation_id for r in rows] == ["call-a", "call-b"]
    # raw_columns is now keyed by PARAMETER NAME (not CSV header).
    assert rows[0].raw_columns == {
        "conversation_id": "call-a",
        "transcript": "hello a",
        "recording_url": "https://x/a.mp3",
    }
    assert rows[0].transcript == "hello a"
    assert rows[0].transcript_source == "csv"
    assert rows[0].diarised_transcript is None


def test_upload_requires_skip_for_unmapped_csv_columns(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))

    buf = io.StringIO()
    buf.write("CallID,Recording URL,Transcript,AgentName\n")
    buf.write("call-a,https://x/a.mp3,hi,alice\n")
    csv_bytes = buf.getvalue().encode("utf-8")

    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("rows.csv", csv_bytes, "text/csv")},
        data=_upload_payload(integration, schema.id),
    )
    assert response.status_code == 400
    assert "agentname" in response.json()["detail"].lower()

    # Same payload but with AgentName listed as skipped -> succeeds and
    # the column never lands in raw_columns.
    response_ok = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("rows.csv", csv_bytes, "text/csv")},
        data=_upload_payload(
            integration,
            schema.id,
            skipped_columns=["AgentName"],
        ),
    )
    assert response_ok.status_code == 202, response_ok.text
    call_import_id = UUID(response_ok.json()["id"])
    (row,) = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
    )
    assert "AgentName" not in (row.raw_columns or {})


def test_upload_custom_typed_parameter_is_coerced_and_preserved(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(
        db_session,
        org_id,
        _default_workspace_id(db_session, org_id),
        extras=[
            {"name": "agent_name", "type": CallImportParameterType.TEXT},
            {"name": "latency_ms", "type": CallImportParameterType.NUMBER},
        ],
    )
    buf = io.StringIO()
    buf.write("CallID,Recording URL,Transcript,AgentName,Latency\n")
    buf.write("conv-1,https://x/r.mp3,hi,alice,1234\n")
    csv_bytes = buf.getvalue().encode("utf-8")
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("rows.csv", csv_bytes, "text/csv")},
        data=_upload_payload(
            integration,
            schema.id,
            parameter_mapping={
                "conversation_id": "CallID",
                "recording_url": "Recording URL",
                "transcript": "Transcript",
                "agent_name": "AgentName",
                "latency_ms": "Latency",
            },
        ),
    )
    assert response.status_code == 202, response.text
    (row,) = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == UUID(response.json()["id"]))
        .all()
    )
    assert row.raw_columns["agent_name"] == "alice"
    assert row.raw_columns["latency_ms"] == 1234


# ---------------------------------------------------------------------------
# Excel (.xlsx) parser unit tests
# ---------------------------------------------------------------------------


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    openpyxl = pytest.importorskip(
        "openpyxl", reason="openpyxl required for Excel-flavored tests"
    )
    workbook = openpyxl.Workbook()
    default = workbook.active
    workbook.remove(default)
    for sheet_name, rows in sheets.items():
        ws = workbook.create_sheet(title=sheet_name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def test_parse_xlsx_accepts_canonical_headers():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["abc-1", "https://x/recording.mp3", "Hello world"],
                ["abc-2", "https://x/2.mp3", "Another call"],
            ]
        }
    )
    rows = _parse_xlsx(
        blob, "Calls", _standard_params(), _standard_mapping(), _standard_skipped()
    )
    assert len(rows) == 2
    assert rows[0]["conversation_id"] == "abc-1"
    assert rows[0]["recording_url"].endswith("recording.mp3")
    assert rows[0]["transcript"] == "Hello world"


def test_parse_xlsx_coerces_numeric_call_ids_without_decimal_suffix():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                [12345, "https://x/r.mp3", "hi"],
            ]
        }
    )
    rows = _parse_xlsx(
        blob, "Calls", _standard_params(), _standard_mapping(), _standard_skipped()
    )
    assert rows[0]["conversation_id"] == "12345"


def test_parse_xlsx_skips_fully_blank_rows():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["abc-1", "https://x/r.mp3", "hi"],
                [None, None, None],
                ["abc-2", "https://x/r2.mp3", "hi 2"],
            ]
        }
    )
    rows = _parse_xlsx(
        blob, "Calls", _standard_params(), _standard_mapping(), _standard_skipped()
    )
    assert [r["conversation_id"] for r in rows] == ["abc-1", "abc-2"]


def test_parse_xlsx_rejects_unknown_sheet():
    blob = _xlsx_bytes({"Calls": [["CallID"], ["abc-1"]]})
    minimal_params = [
        _param(
            name="conversation_id",
            type_=CallImportParameterType.CONVERSATION_ID,
            is_required=True,
        )
    ]
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(
            blob,
            "Nope",
            minimal_params,
            {"conversation_id": "CallID"},
            skipped_columns=[],
        )
    assert exc.value.status_code == 400
    assert "not found" in exc.value.detail.lower()


def test_parse_xlsx_requires_sheet_name():
    blob = _xlsx_bytes({"Calls": [["CallID"], ["abc-1"]]})
    minimal_params = [
        _param(
            name="conversation_id",
            type_=CallImportParameterType.CONVERSATION_ID,
            is_required=True,
        )
    ]
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(
            blob,
            None,
            minimal_params,
            {"conversation_id": "CallID"},
            skipped_columns=[],
        )
    assert exc.value.status_code == 400
    assert "sheet_name" in exc.value.detail.lower()


def test_parse_xlsx_rejects_empty_workbook():
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(b"", "Calls", _standard_params(), _standard_mapping(), [])
    assert exc.value.status_code == 400
    assert "empty" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# /preview endpoint
# ---------------------------------------------------------------------------


def test_preview_returns_single_synthetic_sheet_for_csv(
    authenticated_client, db_session, org_id, seed_org
):
    csv_bytes = (
        b"CallID,Recording URL,Transcript\n"
        b"abc-1,https://x/r.mp3,hi\n"
        b"abc-2,https://x/r2.mp3,hi 2\n"
    )
    response = authenticated_client.post(
        "/api/v1/call-imports/preview",
        files={"file": ("rows.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "csv"
    assert len(body["sheets"]) == 1
    sheet = body["sheets"][0]
    assert sheet["name"] == "rows.csv"
    assert sheet["headers"] == ["CallID", "Recording URL", "Transcript"]
    assert sheet["row_count"] == 2


def test_preview_returns_all_worksheets_for_xlsx(
    authenticated_client, db_session, org_id, seed_org
):
    blob = _xlsx_bytes(
        {
            "Sheet1": [
                ["CallID", "Recording URL", "Transcript"],
                ["abc-1", "https://x/r.mp3", "hi"],
            ],
            "Sheet2": [
                ["ConversationID", "AudioLink"],
                ["conv-1", "https://x/r2.mp3"],
                ["conv-2", "https://x/r3.mp3"],
            ],
        }
    )
    response = authenticated_client.post(
        "/api/v1/call-imports/preview",
        files={
            "file": (
                "data.xlsx",
                blob,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "xlsx"
    sheet_names = [s["name"] for s in body["sheets"]]
    assert sheet_names == ["Sheet1", "Sheet2"]


def test_preview_rejects_unsupported_extension(
    authenticated_client, db_session, org_id, seed_org
):
    response = authenticated_client.post(
        "/api/v1/call-imports/preview",
        files={"file": ("data.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /upload route — Excel variants
# ---------------------------------------------------------------------------


def test_upload_xlsx_with_sheet_name_persists_rows(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    blob = _xlsx_bytes(
        {
            "Sheet1": [["CallID"], ["wrong"]],
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["xls-1", "https://x/a.mp3", "from xlsx"],
                ["xls-2", "https://x/b.mp3", "second xlsx row"],
            ],
        }
    )
    payload = _upload_payload(integration, schema.id)
    payload["sheet_name"] = "Calls"

    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={
            "file": (
                "data.xlsx",
                blob,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data=payload,
    )
    assert response.status_code == 202, response.text
    call_import_id = UUID(response.json()["id"])
    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.sheet_name == "Calls"
    assert call_import.original_filename == "data.xlsx"
    rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index)
        .all()
    )
    assert [r.conversation_id for r in rows] == ["xls-1", "xls-2"]
    assert rows[0].transcript == "from xlsx"
    assert rows[0].transcript_source == "csv"


def test_upload_csv_rejects_sheet_name_form_field(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    payload = _upload_payload(integration, schema.id)
    payload["sheet_name"] = "Sheet1"

    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=payload,
    )
    assert response.status_code == 400
    assert "sheet_name" in response.json()["detail"].lower()


def test_upload_rejects_xls_legacy_format(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("legacy.xls", b"\xd0\xcf\x11\xe0fake", "application/vnd.ms-excel")},
        data=_upload_payload(integration, schema.id),
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_upload_csv_still_persists_with_null_sheet_name(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    schema = _seed_schema(db_session, org_id, _default_workspace_id(db_session, org_id))
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, schema.id),
    )
    assert response.status_code == 202, response.text
    call_import_id = UUID(response.json()["id"])
    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.sheet_name is None
