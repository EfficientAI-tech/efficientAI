"""Unit tests for the CSV parser used by the /call-imports/upload route.

These exercise the helper directly (no FastAPI app required) so we can
validate header normalization, missing-row handling, and edge cases.
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.routes.call_imports import (
    _delete_s3_objects,
    _parse_csv,
    _revoke_pending_tasks,
)
from app.models.enums import CallImportRowStatus


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def test_parse_csv_accepts_canonical_headers():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://api.exotel.com/recordings/abc-1.mp3,Hello world\n"
        "abc-2,https://api.exotel.com/recordings/abc-2.mp3,Another call\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text))
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
    rows = _parse_csv(_csv_bytes(csv_text))
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "id-1"
    assert rows[0]["transcript"] == "Some transcript"


def test_parse_csv_rejects_empty_input():
    with pytest.raises(HTTPException) as exc:
        _parse_csv(b"")
    assert exc.value.status_code == 400
    assert "empty" in exc.value.detail.lower()


def test_parse_csv_rejects_missing_required_headers():
    # Recording URL is allowed without Transcript only if Transcript is also
    # missing-as-required; here Transcript is missing so this must fail.
    csv_text = "CallID,Recording URL\nabc-1,https://x/recording.mp3\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text))
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
    rows = _parse_csv(_csv_bytes(csv_text))
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
        _parse_csv(_csv_bytes(csv_text))
    assert exc.value.status_code == 400
    assert "callid" in exc.value.detail.lower()


def test_parse_csv_allows_blank_recording_url_when_callid_present():
    # With Recording URL header present but the cell empty, the row should be
    # accepted and recording_url normalized to None.
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,,Some transcript\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text))
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
    rows = _parse_csv(_csv_bytes(csv_text))
    assert len(rows) == 2
    assert [r["external_call_id"] for r in rows] == ["abc-1", "abc-2"]


def test_parse_csv_allows_blank_transcript():
    csv_text = (
        "CallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text))
    assert len(rows) == 1
    assert rows[0]["transcript"] is None


def test_parse_csv_strips_utf8_bom():
    csv_text = (
        "\ufeffCallID,Recording URL,Transcript\n"
        "abc-1,https://x/recording.mp3,T1\n"
    )
    rows = _parse_csv(_csv_bytes(csv_text))
    assert len(rows) == 1
    assert rows[0]["external_call_id"] == "abc-1"


def test_parse_csv_rejects_header_only_file():
    csv_text = "CallID,Recording URL,Transcript\n"
    with pytest.raises(HTTPException) as exc:
        _parse_csv(_csv_bytes(csv_text))
    assert exc.value.status_code == 400
    assert "data rows" in exc.value.detail.lower()


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
