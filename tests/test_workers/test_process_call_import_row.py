"""Tests for the process_call_import_row Celery task and its rollup helper."""

import sys
import types
from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportRow,
    Organization,
    TelephonyIntegration,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
    TelephonyProvider,
)


class RetryCalled(Exception):
    """Raised by task.retry in tests to assert retry paths."""


def _seed(db_session, *, row_count: int = 1):
    org = Organization(id=uuid4(), name="Imports Test Org")
    db_session.add(org)
    db_session.commit()

    integration = TelephonyIntegration(
        organization_id=org.id,
        provider=TelephonyProvider.EXOTEL.value,
        auth_id="enc_auth_id",
        auth_token="enc_auth_token",
        voice_app_id="acct_sid",
        is_active=True,
    )
    db_session.add(integration)
    db_session.commit()

    call_import = CallImport(
        organization_id=org.id,
        provider=TelephonyProvider.EXOTEL.value,
        original_filename="batch.csv",
        total_rows=row_count,
        completed_rows=0,
        failed_rows=0,
        status=CallImportStatus.PROCESSING,
    )
    db_session.add(call_import)
    db_session.flush()

    rows = []
    for idx in range(row_count):
        row = CallImportRow(
            call_import_id=call_import.id,
            organization_id=org.id,
            row_index=idx,
            external_call_id=f"call-{idx}",
            recording_url=f"https://api.exotel.com/recordings/{idx}.mp3",
            transcript=f"transcript {idx}",
            status=CallImportRowStatus.PENDING,
        )
        db_session.add(row)
        rows.append(row)
    db_session.commit()

    return org, call_import, rows


class _FakeExotelClient:
    """Stand-in for ExotelClient that the worker can call."""

    def __init__(
        self,
        audio: bytes = b"FAKE_AUDIO_BYTES",
        content_type: str = "audio/mpeg",
        resolved_url_by_call_sid: dict | None = None,
    ):
        self.audio = audio
        self.content_type = content_type
        self.calls = []
        self.resolved_calls = []
        self._resolved_urls = resolved_url_by_call_sid or {}

    def download_recording(self, recording_url):
        self.calls.append(recording_url)
        return self.audio, self.content_type

    def get_call_recording_url(self, call_sid):
        self.resolved_calls.append(call_sid)
        if call_sid in self._resolved_urls:
            return self._resolved_urls[call_sid]
        return f"https://api.exotel.com/recordings/{call_sid}.mp3"


class _FakeS3:
    """Captures uploaded keys and content."""

    def __init__(self, enabled: bool = True):
        self.prefix = "test-prefix/"
        self._enabled = enabled
        self.uploads = []

    def is_enabled(self):
        return self._enabled

    def get_status_message(self):
        return None if self._enabled else "S3 disabled in tests"

    def upload_file_by_key(self, file_content, key, content_type="audio/mpeg"):
        self.uploads.append({"key": key, "size": len(file_content), "content_type": content_type})
        return key


class _NonClosingSession:
    """Proxy that forwards everything to the underlying session but ignores .close().

    The Celery task closes its DB session in a `finally` block, which expunges
    every instance the test seeded. Tests need to keep using those instances
    afterwards, so we suppress close() while still letting the task's commit /
    rollback / query calls go through unchanged.
    """

    def __init__(self, session):
        self._session = session

    def close(self):  # no-op
        return None

    def __getattr__(self, name):
        return getattr(self._session, name)


def _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3):
    """Wire up SessionLocal + the lazily-imported services the task uses."""
    from app.workers.tasks import process_call_import_row as task_module

    monkeypatch.setattr(
        task_module, "SessionLocal", lambda: _NonClosingSession(db_session)
    )

    # Telephony service: return our fake client regardless of provider.
    fake_telephony_module = sys.modules.get("app.services.telephony.telephony_service")
    if fake_telephony_module is None:
        fake_telephony_module = types.ModuleType("app.services.telephony.telephony_service")
        monkeypatch.setitem(
            sys.modules, "app.services.telephony.telephony_service", fake_telephony_module
        )

    class _FakeTelephonyService:
        def __init__(self, client):
            self._client = client

        def get_provider_client(self, *_args, **_kwargs):
            return self._client

    fake_telephony_module.telephony_service = _FakeTelephonyService(fake_client)

    # Storage service: provide a fake whose state we can inspect.
    fake_s3_module = sys.modules.get("app.services.storage.s3_service")
    if fake_s3_module is None:
        fake_s3_module = types.ModuleType("app.services.storage.s3_service")
        monkeypatch.setitem(sys.modules, "app.services.storage.s3_service", fake_s3_module)
    fake_s3_module.s3_service = fake_s3

    return task_module


def test_process_call_import_row_completes_and_rolls_up_to_completed(db_session, monkeypatch):
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"

    db_session.refresh(row)
    db_session.refresh(call_import)

    assert row.status == CallImportRowStatus.COMPLETED
    assert row.recording_size_bytes == len(b"hello-audio")
    assert row.recording_content_type == "audio/mpeg"
    assert row.recording_s3_key.endswith(".mp3")
    assert f"organizations/{org.id}/call_imports/{call_import.id}/{row.id}.mp3" in row.recording_s3_key

    # Parent counters and status
    assert call_import.completed_rows == 1
    assert call_import.failed_rows == 0
    assert call_import.status == CallImportStatus.COMPLETED

    # Recording was actually fetched once and uploaded once
    assert fake_client.calls == [row.recording_url]
    assert len(fake_s3.uploads) == 1
    assert fake_s3.uploads[0]["size"] == len(b"hello-audio")


def test_process_call_import_row_marks_failed_on_auth_error_without_retry(db_session, monkeypatch):
    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    from app.services.telephony.exotel_client import ExotelAuthError

    class _AuthFailingClient:
        def download_recording(self, _url):
            raise ExotelAuthError("bad creds")

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, _AuthFailingClient(), fake_s3)

    # If retry is invoked, the test would surface it; we don't expect it.
    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "non_retryable_provider_error"

    db_session.refresh(row)
    db_session.refresh(call_import)

    assert row.status == CallImportRowStatus.FAILED
    assert "bad creds" in (row.error_message or "")
    assert row.recording_s3_key is None
    assert call_import.failed_rows == 1
    assert call_import.completed_rows == 0
    assert call_import.status == CallImportStatus.FAILED
    assert fake_s3.uploads == []


def test_process_call_import_row_retries_on_transient_error(db_session, monkeypatch):
    _, _call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    from app.services.telephony.exotel_client import ExotelTransientError

    class _TransientFailingClient:
        def download_recording(self, _url):
            raise ExotelTransientError("flaky network")

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, _TransientFailingClient(), fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    with pytest.raises(RetryCalled):
        task_module.process_call_import_row_task.run(str(row.id))

    db_session.refresh(row)
    # After scheduling a retry, the row stays in PENDING (not COMPLETED, not FAILED)
    assert row.status == CallImportRowStatus.PENDING
    assert "Transient" in (row.error_message or "")
    assert row.attempts == 1


def test_process_call_import_row_partial_status_when_some_rows_fail(db_session, monkeypatch):
    _, call_import, rows = _seed(db_session, row_count=2)

    # Pre-mark the second row as FAILED (e.g. from an earlier attempt).
    rows[1].status = CallImportRowStatus.FAILED
    rows[1].error_message = "previous failure"
    db_session.commit()

    fake_client = _FakeExotelClient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(rows[0].id))
    assert result["status"] == "completed"

    db_session.refresh(call_import)
    db_session.refresh(rows[0])

    assert rows[0].status == CallImportRowStatus.COMPLETED
    assert call_import.completed_rows == 1
    assert call_import.failed_rows == 1
    # Mixed terminal outcomes -> PARTIAL
    assert call_import.status == CallImportStatus.PARTIAL


def test_process_call_import_row_resolves_url_when_csv_omits_it(db_session, monkeypatch):
    """When recording_url is absent, the worker resolves it via the provider's
    Calls API, persists the resolved URL on the row, then downloads."""

    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    # Mimic a CSV that only had CallID + Transcript (no Recording URL).
    row.recording_url = None
    db_session.commit()

    resolved_url = "https://api.exotel.com/v1/Recordings/resolved-from-api.mp3"
    fake_client = _FakeExotelClient(
        audio=b"resolved-audio",
        content_type="audio/mpeg",
        resolved_url_by_call_sid={row.external_call_id: resolved_url},
    )
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"

    db_session.refresh(row)
    db_session.refresh(call_import)

    # Worker should have resolved exactly once for this CallID and downloaded
    # using the resolved URL, then persisted that URL on the row.
    assert fake_client.resolved_calls == [row.external_call_id]
    assert fake_client.calls == [resolved_url]
    assert row.recording_url == resolved_url
    assert row.status == CallImportRowStatus.COMPLETED
    assert row.recording_size_bytes == len(b"resolved-audio")
    assert call_import.status == CallImportStatus.COMPLETED


def test_process_call_import_row_does_not_resolve_when_url_present(db_session, monkeypatch):
    """If the row already has a recording_url (from the CSV), the worker
    should NOT call the resolver path."""

    _, _call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    assert row.recording_url  # sanity: seeded with a URL

    fake_client = _FakeExotelClient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"
    assert fake_client.resolved_calls == []
    assert fake_client.calls == [row.recording_url]


def test_process_call_import_row_marks_failed_on_resolve_not_found(db_session, monkeypatch):
    """A 404 / no-recording outcome from the resolver is non-retryable."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.recording_url = None
    db_session.commit()

    from app.services.telephony.exotel_client import ExotelNotFoundError

    class _ResolverFailingClient:
        def __init__(self):
            self.resolved_calls = []
            self.calls = []

        def get_call_recording_url(self, call_sid):
            self.resolved_calls.append(call_sid)
            raise ExotelNotFoundError(f"call {call_sid} has no recording")

        def download_recording(self, _url):
            self.calls.append(_url)
            raise AssertionError("download_recording should not be called")

    fake_client = _ResolverFailingClient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "non_retryable_provider_error"

    db_session.refresh(row)
    db_session.refresh(call_import)
    assert row.status == CallImportRowStatus.FAILED
    assert "no recording" in (row.error_message or "")
    assert call_import.status == CallImportStatus.FAILED
    assert fake_client.calls == []  # never reached download


def test_process_call_import_row_marks_failed_when_s3_disabled(db_session, monkeypatch):
    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    fake_client = _FakeExotelClient()
    fake_s3 = _FakeS3(enabled=False)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "s3_unavailable"

    db_session.refresh(row)
    db_session.refresh(call_import)
    assert row.status == CallImportRowStatus.FAILED
    assert call_import.status == CallImportStatus.FAILED
