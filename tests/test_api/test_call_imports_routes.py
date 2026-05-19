"""Unit tests for the CSV parser used by the /call-imports/upload route.

These exercise the helper directly (no FastAPI app required) so we can
validate header normalization, missing-row handling, and edge cases.
"""

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
from app.models.schemas import CallImportColumnMapping
from app.models.enums import CallImportRowStatus


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _mapping(
    *,
    external_call_id: str = "CallID",
    transcript: str | None = "Transcript",
    recording_url: str | None = "Recording URL",
) -> CallImportColumnMapping:
    return CallImportColumnMapping(
        external_call_id=external_call_id,
        transcript=transcript,
        recording_url=recording_url,
    )


def test_parse_csv_accepts_canonical_headers():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://api.exotel.com/recordings/abc-1.mp3,Hello world\n"
        "abc-2,https://api.exotel.com/recordings/abc-2.mp3,Another call\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 2
    assert rows[0]["external_call_id"] == "abc-1"
    assert rows[0]["recording_url"].endswith("abc-1.mp3")
    assert rows[0]["transcript"] == "Hello world"
    assert rows[1]["external_call_id"] == "abc-2"


def test_parse_csv_is_case_insensitive_on_headers():
    csv_text = (
        "callid,recording url,TRANSCRIPT\n"
        "id-1,https://x/recording.mp3,Some transcript\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "id-1"
    assert rows[0]["transcript"] == "Some transcript"


def test_parse_csv_rejects_empty_input():
    with pytest.raises(HTTPException) as exc:
        _parse_csv(b"", _mapping(), [])
    assert exc.value.status_code == 400
    assert "empty" in exc.value.detail.lower()


def test_parse_csv_rejects_missing_required_headers():
    # Recording URL is allowed without Transcript only if Transcript is also
    # missing-as-required; here Transcript is missing so this must fail.
    csv_text = "CallID,Recording URL\nabc-1,https://x/recording.mp3\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert exc.value.status_code == 400
    assert "transcript" in exc.value.detail.lower()


def test_parse_csv_does_not_require_recording_url_header():
    # Recording URL is optional now: a CSV with just CallID, Transcript should
    # parse cleanly, with recording_url left as None for each row so the worker
    # can resolve it from the provider.
    csv_text = (
        "CallID,Transcript\n"
        "abc-1,Hello world\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(recording_url=None), [])
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "abc-1"
    assert rows[0]["recording_url"] is None
    assert rows[0]["transcript"] == "Hello world"


def test_parse_csv_rejects_row_missing_callid():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        ",https://x/recording.mp3,Some transcript\n"
    )
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert exc.value.status_code == 400
    assert "external call id" in exc.value.detail.lower()


def test_parse_csv_allows_blank_recording_url_when_callid_present():
    # With Recording URL header present but the cell empty, the row should be
    # accepted and recording_url normalized to None.
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,,Some transcript\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "abc-1"
    assert rows[0]["recording_url"] is None
    assert rows[0]["transcript"] == "Some transcript"


def test_parse_csv_skips_completely_blank_rows():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,Some transcript\n"
        ",,\n"
        "abc-2,https://x/2.mp3,Other transcript\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 2
    assert [r["external_call_id"] for r in rows] == ["abc-1", "abc-2"]


def test_parse_csv_allows_blank_transcript():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 1
    assert rows[0]["transcript"] is None


def test_parse_csv_strips_utf8_bom():
    csv_text = (
        "\ufeffCallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,T1\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "abc-1"


def test_parse_csv_rejects_header_only_file():
    csv_text = "CallID,Recording URL,Transcript\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text), _mapping(), [])
    assert exc.value.status_code == 400
    assert "data rows" in exc.value.detail.lower()


def test_parse_csv_supports_custom_mapping_and_raw_columns_snapshot():
    csv_text = (
        "ConversationID,Bajaj_url,CallTranscipt,AgentName\n"
        "conv-1,https://x/r1.mp3,hello there,alice\n"
    )
    rows = _parse_csv(
        _csv_bytes(csv_text),
        _mapping(
            external_call_id="ConversationID",
            transcript="CallTranscipt",
            recording_url="Bajaj_url",
        ),
        ["AgentName"],
    )
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "conv-1"
    assert rows[0]["recording_url"] == "https://x/r1.mp3"
    assert rows[0]["transcript"] == "hello there"
    assert rows[0]["raw_columns"] == {
        "ConversationID": "conv-1",
        "CallTranscipt": "hello there",
        "Bajaj_url": "https://x/r1.mp3",
        "AgentName": "alice",
    }


def test_parse_csv_rejects_missing_mapped_column():
    csv_text = "ConversationID,Transcript\nconv-1,hello\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(
            _csv_bytes(csv_text),
            _mapping(
                external_call_id="ConversationID",
                transcript="Transcript",
                recording_url="Bajaj_url",
            ),
            [],
        )
    assert exc.value.status_code == 400
    assert "bajaj_url" in exc.value.detail.lower()


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
        _row(CallImportRowStatus.COMPLETED, "t3"),  # already done -> skip
        _row(CallImportRowStatus.FAILED, "t4"),  # terminal -> skip
        _row(CallImportRowStatus.PENDING, None),  # no task id -> skip
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
        # Must not raise — revoke is best-effort.
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
        SimpleNamespace(recording_s3_key=None),  # not yet uploaded -> ignored
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
    assert deleted == 3  # 2 from keys + 1 from sweep
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
    assert errors == 2  # one per known key


# ---------------------------------------------------------------------------
# End-to-end upload route tests for the configurable mapping + credential pin
# ---------------------------------------------------------------------------

import io

from app.models.database import CallImport, CallImportRow, TelephonyIntegration


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


def _upload_payload(
    integration,
    *,
    provider=None,
    column_mapping=None,
    extra_columns=None,
):
    return {
        "provider": provider or integration.provider,
        "telephony_integration_id": str(integration.id),
        "column_mapping": column_mapping
        or (
            '{"external_call_id":"CallID","transcript":"Transcript",'
            '"recording_url":"Recording URL"}'
        ),
        "extra_columns": extra_columns or "[]",
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
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, provider="plivo"),
    )
    assert response.status_code == 400
    assert "provider" in response.json()["detail"].lower()


def test_upload_rejects_when_credential_unknown(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    payload = _upload_payload(integration)
    # Override with an unknown UUID -> 400, not 500.
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
    integration.is_active = False
    db_session.commit()
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration),
    )
    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


def test_upload_rejects_invalid_column_mapping_json(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration, column_mapping="{not-json}"),
    )
    assert response.status_code == 400
    assert "valid json" in response.json()["detail"].lower()


def test_upload_rejects_when_external_call_id_mapping_missing(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    # Mapping is missing the required external_call_id key.
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(
            integration,
            column_mapping='{"transcript":"Transcript"}',
        ),
    )
    assert response.status_code == 400
    assert "external_call_id" in response.json()["detail"].lower() or "invalid" in response.json()["detail"].lower()


def test_upload_rejects_when_mapped_column_absent_from_csv(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(
            integration,
            column_mapping=(
                '{"external_call_id":"MissingId","transcript":"Transcript",'
                '"recording_url":"Recording URL"}'
            ),
        ),
    )
    assert response.status_code == 400
    assert "missingid" in response.json()["detail"].lower()


def test_upload_persists_raw_columns_and_mapping(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)

    csv_rows = (
        ("call-a", "https://x/a.mp3", "hello a"),
        ("call-b", "https://x/b.mp3", "hello b"),
    )
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv(rows=csv_rows)},
        data=_upload_payload(integration, extra_columns='[]'),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    call_import_id = UUID(body["id"])

    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.telephony_integration_id == integration.id
    assert call_import.column_mapping == {
        "external_call_id": "CallID",
        "transcript": "Transcript",
        "recording_url": "Recording URL",
    }
    assert call_import.extra_columns == []

    rows = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index)
        .all()
    )
    assert [r.external_call_id for r in rows] == ["call-a", "call-b"]
    # raw_columns snapshot preserves the original CSV cells per row.
    assert rows[0].raw_columns == {
        "CallID": "call-a",
        "Transcript": "hello a",
        "Recording URL": "https://x/a.mp3",
    }
    # Production transcripts supplied via CSV must be stamped with
    # ``transcript_source='csv'`` on upload so the UI badge ("From CSV")
    # renders without waiting for any worker to run.
    assert rows[0].transcript == "hello a"
    assert rows[0].transcript_source == "csv"
    # The diarised transcript column starts empty for every fresh upload.
    assert rows[0].diarised_transcript is None


def test_upload_preserves_extra_columns_in_raw_snapshot(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    buf = io.StringIO()
    buf.write("CallID,Recording URL,Transcript,AgentName\n")
    buf.write("call-a,https://x/a.mp3,hi,alice\n")
    csv_bytes = buf.getvalue().encode("utf-8")

    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("rows.csv", csv_bytes, "text/csv")},
        data=_upload_payload(integration, extra_columns='["AgentName"]'),
    )
    assert response.status_code == 202, response.text
    call_import_id = UUID(response.json()["id"])

    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.extra_columns == ["AgentName"]

    (row,) = (
        db_session.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
    )
    assert row.raw_columns == {
        "CallID": "call-a",
        "Transcript": "hi",
        "Recording URL": "https://x/a.mp3",
        "AgentName": "alice",
    }


# ---------------------------------------------------------------------------
# Excel (.xlsx) parser unit tests
# ---------------------------------------------------------------------------


def _xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Build an in-memory .xlsx workbook from ``{sheet_name: rows}``.

    The first inner list is treated as the header row; subsequent lists
    are data rows. No disk I/O — uses ``BytesIO`` so each test is hermetic
    and fast. Cells preserve their native Python type (str / int / float /
    datetime / None) so we can also exercise the cell coercion path.

    Skips the calling test when openpyxl isn't installed so the bulk of
    this module's CSV-only tests still run on a minimal install.
    """
    openpyxl = pytest.importorskip(
        "openpyxl", reason="openpyxl required for Excel-flavored tests"
    )
    workbook = openpyxl.Workbook()
    # ``Workbook()`` ships with a default sheet named "Sheet"; rename or
    # remove it so the test specifies all sheets explicitly.
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
    rows = _parse_xlsx(blob, "Calls", _mapping(), [])
    assert len(rows) == 2
    assert rows[0]["external_call_id"] == "abc-1"
    assert rows[0]["recording_url"].endswith("recording.mp3")
    assert rows[0]["transcript"] == "Hello world"


def test_parse_xlsx_coerces_numeric_call_ids_without_decimal_suffix():
    # openpyxl returns int values for whole-number cells; the parser must
    # not stringify them as "123.0" or downstream lookups break.
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                [12345, "https://x/r.mp3", "hi"],
            ]
        }
    )
    rows = _parse_xlsx(blob, "Calls", _mapping(), [])
    assert rows[0]["external_call_id"] == "12345"


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
    rows = _parse_xlsx(blob, "Calls", _mapping(), [])
    assert [r["external_call_id"] for r in rows] == ["abc-1", "abc-2"]


def test_parse_xlsx_rejects_unknown_sheet():
    blob = _xlsx_bytes({"Calls": [["CallID"], ["abc-1"]]})
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(blob, "Nope", _mapping(external_call_id="CallID", transcript=None, recording_url=None), [])
    assert exc.value.status_code == 400
    assert "not found" in exc.value.detail.lower()


def test_parse_xlsx_requires_sheet_name():
    blob = _xlsx_bytes({"Calls": [["CallID"], ["abc-1"]]})
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(blob, None, _mapping(transcript=None, recording_url=None), [])
    assert exc.value.status_code == 400
    assert "sheet_name" in exc.value.detail.lower()


def test_parse_xlsx_rejects_missing_mapped_column():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["ConversationID", "Transcript"],
                ["conv-1", "hi"],
            ]
        }
    )
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(
            blob,
            "Calls",
            _mapping(
                external_call_id="ConversationID",
                transcript="Transcript",
                recording_url="Bajaj_url",
            ),
            [],
        )
    assert exc.value.status_code == 400
    assert "bajaj_url" in exc.value.detail.lower()


def test_parse_xlsx_supports_custom_mapping_and_raw_columns_snapshot():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["ConversationID", "Bajaj_url", "CallTranscipt", "AgentName"],
                ["conv-1", "https://x/r1.mp3", "hello there", "alice"],
            ]
        }
    )
    rows = _parse_xlsx(
        blob,
        "Calls",
        _mapping(
            external_call_id="ConversationID",
            transcript="CallTranscipt",
            recording_url="Bajaj_url",
        ),
        ["AgentName"],
    )
    assert len(rows) == 1
    assert rows[0]["raw_columns"] == {
        "ConversationID": "conv-1",
        "CallTranscipt": "hello there",
        "Bajaj_url": "https://x/r1.mp3",
        "AgentName": "alice",
    }


def test_parse_xlsx_rejects_empty_workbook():
    with pytest.raises(HTTPException) as exc:
        _parse_xlsx(b"", "Calls", _mapping(), [])
    assert exc.value.status_code == 400
    assert "empty" in exc.value.detail.lower()


def test_parse_xlsx_matches_sheet_name_case_insensitively():
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["abc-1", "https://x/r.mp3", "hi"],
            ]
        }
    )
    rows = _parse_xlsx(blob, "calls", _mapping(), [])
    assert len(rows) == 1


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
        files={"file": ("data.xlsx", blob, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "xlsx"
    sheet_names = [s["name"] for s in body["sheets"]]
    assert sheet_names == ["Sheet1", "Sheet2"]
    sheets_by_name = {s["name"]: s for s in body["sheets"]}
    assert sheets_by_name["Sheet1"]["headers"] == [
        "CallID",
        "Recording URL",
        "Transcript",
    ]
    assert sheets_by_name["Sheet1"]["row_count"] == 1
    assert sheets_by_name["Sheet2"]["headers"] == ["ConversationID", "AudioLink"]
    assert sheets_by_name["Sheet2"]["row_count"] == 2


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
    payload = _upload_payload(integration)
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
    assert [r.external_call_id for r in rows] == ["xls-1", "xls-2"]
    assert rows[0].transcript == "from xlsx"
    assert rows[0].transcript_source == "csv"


def test_upload_xlsx_rejects_when_sheet_name_missing(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["xls-1", "https://x/a.mp3", "hi"],
            ]
        }
    )
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={
            "file": (
                "data.xlsx",
                blob,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data=_upload_payload(integration),
    )
    assert response.status_code == 400
    assert "sheet_name" in response.json()["detail"].lower()


def test_upload_xlsx_rejects_unknown_sheet_name(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    blob = _xlsx_bytes(
        {
            "Calls": [
                ["CallID", "Recording URL", "Transcript"],
                ["xls-1", "https://x/a.mp3", "hi"],
            ]
        }
    )
    payload = _upload_payload(integration)
    payload["sheet_name"] = "DoesNotExist"

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
    assert response.status_code == 400
    assert "doesnotexist" in response.json()["detail"].lower()


def test_upload_csv_rejects_sheet_name_form_field(
    authenticated_client, db_session, org_id, seed_org
):
    integration = _seed_integration(db_session, org_id)
    payload = _upload_payload(integration)
    # CSVs have no sheet concept; a non-empty value is a typo / wrong file.
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
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": ("legacy.xls", b"\xd0\xcf\x11\xe0fake", "application/vnd.ms-excel")},
        data=_upload_payload(integration),
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_upload_csv_still_persists_with_null_sheet_name(
    authenticated_client, db_session, org_id, seed_org
):
    """Backwards-compat: existing CSV upload flow must continue to work
    end-to-end and leave ``sheet_name`` NULL on the resulting batch."""
    integration = _seed_integration(db_session, org_id)
    response = authenticated_client.post(
        "/api/v1/call-imports/upload",
        files={"file": _csv()},
        data=_upload_payload(integration),
    )
    assert response.status_code == 202, response.text
    call_import_id = UUID(response.json()["id"])
    call_import = (
        db_session.query(CallImport).filter(CallImport.id == call_import_id).one()
    )
    assert call_import.sheet_name is None
