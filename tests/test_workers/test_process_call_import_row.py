"""Tests for the process_call_import_row Celery task and its rollup helper."""

import importlib.util
import sys
import types
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.database import (
    CallImport,
    CallImportRow,
    Organization,
    TelephonyIntegration,
    Workspace,
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
    workspace = Workspace(
        id=uuid4(),
        organization_id=org.id,
        name="Default",
        slug="default",
        is_default=True,
    )
    db_session.add(workspace)
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
        workspace_id=workspace.id,
        provider=TelephonyProvider.EXOTEL.value,
        telephony_integration_id=integration.id,
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
            workspace_id=workspace.id,
            row_index=idx,
            conversation_id=f"call-{idx}",
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


def _patch_public_download(monkeypatch, *, return_value=None, side_effect=None):
    """Patch the unauthenticated CSV-URL downloader used for direct/Plivo imports."""
    calls = []

    def fake_public(url):
        calls.append(url)
        if side_effect is not None:
            if isinstance(side_effect, type) and issubclass(side_effect, Exception):
                raise side_effect(f"public download failed for {url}")
            if callable(side_effect):
                return side_effect(url)
            raise side_effect
        if callable(return_value):
            return return_value(url)
        return return_value

    monkeypatch.setattr(
        "app.services.telephony.recording_download.download_public_recording",
        fake_public,
    )
    return calls


def _ensure_fake_celery_app():
    """Match API-test Celery stubs so bind=True tasks stay plain functions."""
    existing = sys.modules.get("app.workers.config")
    celery_app = getattr(existing, "celery_app", None) if existing else None
    task_decorator = getattr(celery_app, "task", None)
    if callable(task_decorator):
        def _probe_fn():
            return None

        try:
            probe = task_decorator()(_probe_fn)
        except Exception:
            probe = None
        if (
            isinstance(probe, types.FunctionType)
            and getattr(probe, "run", None) is probe
        ):
            return

    class _FakeCeleryApp:
        def task(self, *_args, **_kwargs):
            def _decorator(fn):
                fn.delay = lambda *_a, **_kw: types.SimpleNamespace(id="fake-task")
                fn.apply_async = lambda *_a, **_kw: types.SimpleNamespace(
                    id="fake-task"
                )
                fn.run = fn
                return fn

            return _decorator

    fake_config = types.ModuleType("app.workers.config")
    fake_config.celery_app = _FakeCeleryApp()
    sys.modules["app.workers.config"] = fake_config


def _wrap_bind_task_for_tests(task):
    """Adapt bind=True tasks for direct ``.run(row_id)`` calls in unit tests."""
    if getattr(task, "_bind_task_wrapped", False):
        return task

    if isinstance(task, types.FunctionType):
        fn = getattr(task, "run", task)

        class _FakeBindTask:
            _bind_task_wrapped = True

            def __init__(self):
                self.request = types.SimpleNamespace(id="test-task-id")

            def run(self, row_id, *args, **kwargs):
                return fn(self, row_id, *args, **kwargs)

            def retry(self, exc=None, countdown=None):
                raise RetryCalled((exc, countdown))

        return _FakeBindTask()

    class _CeleryDelegate:
        _bind_task_wrapped = True

        def __init__(self, celery_task):
            self._celery_task = celery_task

        def run(self, row_id, *args, **kwargs):
            return self._celery_task.run(row_id, *args, **kwargs)

        def retry(self, *args, **kwargs):
            return self._celery_task.retry(*args, **kwargs)

    return _CeleryDelegate(task)


def _load_task_module():
    """Load the real task module even when conftest/API tests stub workers.tasks.

    ``authenticated_client`` installs a lightweight ``app.workers.tasks``
    package with ``__path__ = []``, which blocks normal submodule imports.
    Load the task file directly from disk instead.
    """
    module_name = "app.workers.tasks.process_call_import_row"
    existing = sys.modules.get(module_name)
    if existing is not None and hasattr(existing, "process_call_import_row_task"):
        task = getattr(existing, "process_call_import_row_task", None)
        if isinstance(task, types.FunctionType) or getattr(task, "_bind_task_wrapped", False):
            return existing
        del sys.modules[module_name]

    _ensure_fake_celery_app()

    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "workers"
        / "tasks"
        / "process_call_import_row.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load task module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.process_call_import_row_task = _wrap_bind_task_for_tests(
        module.process_call_import_row_task
    )
    return module


def _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3):
    """Wire up row lookup + the lazily-imported services the task uses."""
    from uuid import UUID

    from app.models.database import CallImportEvaluationRow, CallImportRow

    task_module = _load_task_module()
    session_factory = lambda: _NonClosingSession(db_session)
    monkeypatch.setattr("app.database.SessionLocal", session_factory)

    def fake_locate_call_import_row(row_id):
        rid = row_id if isinstance(row_id, UUID) else UUID(str(row_id))
        row = db_session.query(CallImportRow).filter(CallImportRow.id == rid).first()
        if row is None:
            raise LookupError(f"call_import_row {rid} not found")
        session = _NonClosingSession(db_session)
        return session, session, row, "legacy"

    def fake_locate_call_import_evaluation_row(eval_row_id):
        eid = eval_row_id if isinstance(eval_row_id, UUID) else UUID(str(eval_row_id))
        row = (
            db_session.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.id == eid)
            .first()
        )
        if row is None:
            raise LookupError(f"call_import_evaluation_row {eid} not found")
        eval_row, source_row = row
        session = _NonClosingSession(db_session)
        return session, session, eval_row, source_row, "legacy"

    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_row",
        fake_locate_call_import_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.locate_call_import_evaluation_row",
        fake_locate_call_import_evaluation_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.locate_call_import_evaluation_row",
        fake_locate_call_import_evaluation_row,
    )
    monkeypatch.setattr(
        "app.db_sharding.sessions.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
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
    original_csv_url = row.recording_url

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

    # Exotel credentialed import downloads the CSV-supplied URL directly.
    assert fake_client.resolved_calls == []
    assert fake_client.calls == [original_csv_url]
    assert row.recording_url == original_csv_url

    assert len(fake_s3.uploads) == 1
    assert fake_s3.uploads[0]["size"] == len(b"hello-audio")


def test_process_call_import_row_retries_on_credentialed_throttle(db_session, monkeypatch):
    _, _call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    from app.services.telephony.exotel_client import CredentialedRecordingThrottledError

    class _ThrottledClient:
        _credential_fingerprint = "fp-test"

        def download_recording(self, _url):
            raise CredentialedRecordingThrottledError(
                "rate limited",
                retry_after_seconds=25,
            )

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, _ThrottledClient(), fake_s3)
    from app.workers.concurrency.telephony_credential_rate_limit import CreditStatus

    monkeypatch.setattr(
        "app.workers.concurrency.telephony_credential_rate_limit.consume_telephony_import_credit",
        lambda _fp: CreditStatus(allowed=True, remaining=4),
    )
    from app.workers.concurrency.telephony_credential_rate_limit import CreditStatus

    captured = {}

    def _capture_retry(exc, countdown):
        captured["countdown"] = countdown
        raise RetryCalled((exc, countdown))

    monkeypatch.setattr(task_module.process_call_import_row_task, "retry", _capture_retry)

    with pytest.raises(RetryCalled):
        task_module.process_call_import_row_task.run(str(row.id))

    db_session.refresh(row)
    assert row.status == CallImportRowStatus.PENDING
    assert captured["countdown"] == 25


def test_process_call_import_row_retries_when_credit_denied(db_session, monkeypatch):
    _, _call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    class _FingerprintedClient:
        _credential_fingerprint = "fp-denied"

        def download_recording(self, _url):
            raise AssertionError("download should not run when credit is denied")

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(
        monkeypatch, db_session, _FingerprintedClient(), fake_s3
    )
    from app.workers.concurrency.telephony_credential_rate_limit import CreditStatus

    monkeypatch.setattr(
        "app.workers.concurrency.telephony_credential_rate_limit.consume_telephony_import_credit",
        lambda _fp: CreditStatus(allowed=False, wait_seconds=18, remaining=0),
    )

    captured = {}

    def _capture_retry(exc, countdown):
        captured["countdown"] = countdown
        raise RetryCalled((exc, countdown))

    monkeypatch.setattr(task_module.process_call_import_row_task, "retry", _capture_retry)

    with pytest.raises(RetryCalled):
        task_module.process_call_import_row_task.run(str(row.id))

    db_session.refresh(row)
    assert row.status == CallImportRowStatus.PENDING
    assert captured["countdown"] == 18


def test_eval_chain_import_throttle_does_not_fail_eval_row(
    db_session, monkeypatch
):
    from app.models.database import CallImportEvaluation, CallImportEvaluationRow

    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    evaluation = CallImportEvaluation(
        call_import_id=call_import.id,
        organization_id=org.id,
        workspace_id=call_import.workspace_id,
        name="Eval",
        selected_metric_ids=[],
        status="running",
        total_rows=1,
        completed_rows=0,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()
    eval_row = CallImportEvaluationRow(
        evaluation_id=evaluation.id,
        call_import_row_id=row.id,
        status="pending",
    )
    db_session.add(eval_row)
    db_session.commit()

    class _FingerprintedClient:
        _credential_fingerprint = "fp-denied"

        def download_recording(self, _url):
            raise AssertionError("download should not run when credit is denied")

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(
        monkeypatch, db_session, _FingerprintedClient(), fake_s3
    )
    from app.workers.concurrency.telephony_credential_rate_limit import CreditStatus

    monkeypatch.setattr(
        "app.workers.concurrency.telephony_credential_rate_limit.consume_telephony_import_credit",
        lambda _fp: CreditStatus(allowed=False, wait_seconds=15, remaining=0),
    )
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: True,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_dispatch.finish_eval_work_and_redispatch",
        lambda _task_id: None,
    )

    def _capture_retry(exc, countdown):
        raise RetryCalled((exc, countdown))

    monkeypatch.setattr(task_module.process_call_import_row_task, "retry", _capture_retry)

    with pytest.raises(RetryCalled):
        task_module.process_call_import_row_task.run(
            str(row.id),
            _eval_slot_task_id="slot-eval-chain",
            run_eval_row_id=str(eval_row.id),
        )

    db_session.refresh(eval_row)
    assert eval_row.status == "pending"
    assert eval_row.error_message is None


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


def test_process_call_import_row_fails_when_csv_omits_recording_url(
    db_session, monkeypatch
):
    """When recording_url is absent, Exotel credentialed import fails immediately."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    row.recording_url = None
    db_session.commit()

    fake_client = _FakeExotelClient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "no_recording_source"

    db_session.refresh(row)
    db_session.refresh(call_import)

    assert fake_client.resolved_calls == []
    assert fake_client.calls == []
    assert row.status == CallImportRowStatus.FAILED
    assert "Exotel import requires a recording URL" in (row.error_message or "")
    assert call_import.status == CallImportStatus.FAILED


def test_process_call_import_row_exotel_csv_url_uses_credentialed_download(
    db_session, monkeypatch
):
    """Exotel credentialed import downloads the CSV URL with provider auth."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    csv_url = row.recording_url
    assert csv_url

    class _CredentialedDownloader:
        def __init__(self):
            self.calls = []

        def download_recording(self, recording_url):
            self.calls.append(recording_url)
            return b"csv-url-audio", "audio/mpeg"

    fake_client = _CredentialedDownloader()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)
    public_calls = _patch_public_download(
        monkeypatch,
        return_value=(b"should-not-be-used", "audio/mpeg"),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"
    db_session.refresh(row)
    assert fake_client.calls == [csv_url]
    assert public_calls == []
    assert row.status == CallImportRowStatus.COMPLETED


def test_process_call_import_row_fails_when_lookup_fails_without_csv_url(
    db_session, monkeypatch
):
    """When recording_url is absent, the row fails without attempting download."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.recording_url = None
    db_session.commit()

    class _ShouldNotDownload:
        def __init__(self):
            self.calls = []

        def download_recording(self, recording_url):
            self.calls.append(recording_url)
            return b"fallback-audio", "audio/mpeg"

    fake_client = _ShouldNotDownload()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    db_session.refresh(row)
    assert fake_client.calls == []
    assert row.status == CallImportRowStatus.FAILED


def test_process_call_import_row_fails_when_csv_url_download_fails(
    db_session, monkeypatch
):
    """When credentialed CSV-URL download fails, the row is marked failed."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    assert row.recording_url

    from app.services.telephony.exotel_client import ExotelAuthError

    class _CsvUrlAuthFails:
        def __init__(self):
            self.calls = []

        def download_recording(self, recording_url):
            self.calls.append(recording_url)
            raise ExotelAuthError(f"auth rejected for {recording_url}")

    fake_client = _CsvUrlAuthFails()
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
    assert fake_client.calls == [row.recording_url]
    assert "recording URL" in (row.error_message or "")
    assert "auth rejected" in (row.error_message or "")
    assert call_import.status == CallImportStatus.FAILED
    assert fake_s3.uploads == []


def test_process_call_import_row_uses_csv_url_when_provider_lacks_lookup(
    db_session, monkeypatch
):
    """Plivo credentialed imports download the CSV URL without provider auth."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    csv_url = row.recording_url
    assert csv_url

    call_import.provider = TelephonyProvider.PLIVO.value
    db_session.commit()

    class _NoLookupClient:
        def __init__(self):
            self.calls = []

        def download_recording(self, recording_url):
            self.calls.append(recording_url)
            return b"plivo-audio", "audio/mpeg"

    fake_client = _NoLookupClient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)
    public_calls = _patch_public_download(
        monkeypatch, return_value=(b"plivo-audio", "audio/mpeg")
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"
    db_session.refresh(row)
    db_session.refresh(call_import)

    assert fake_client.calls == []
    assert public_calls == [csv_url]
    assert row.status == CallImportRowStatus.COMPLETED
    assert call_import.status == CallImportStatus.COMPLETED


def test_process_call_import_row_fails_when_csv_url_missing_for_exotel(
    db_session, monkeypatch
):
    """When recording_url is absent, Exotel import fails without retry."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.recording_url = None
    db_session.commit()

    class _ShouldNotBeCalled:
        def download_recording(self, recording_url):
            raise AssertionError("download_recording should not be called")

    fake_client = _ShouldNotBeCalled()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "no_recording_source"
    db_session.refresh(row)
    assert row.status == CallImportRowStatus.FAILED


def test_process_call_import_row_retries_when_exotel_csv_url_transient(
    db_session, monkeypatch
):
    """When credentialed CSV-URL download is transient, schedule a retry."""

    _, _call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    from app.services.telephony.exotel_client import ExotelTransientError

    class _CsvTransient:
        def __init__(self):
            self.calls = []

        def download_recording(self, recording_url):
            self.calls.append(recording_url)
            raise ExotelTransientError("503 fetching recording")

    fake_client = _CsvTransient()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    with pytest.raises(RetryCalled):
        task_module.process_call_import_row_task.run(str(row.id))

    db_session.refresh(row)
    assert row.status == CallImportRowStatus.PENDING
    assert "Transient" in (row.error_message or "")
    assert fake_client.calls == [row.recording_url]


def test_process_call_import_row_uses_csv_url_when_provider_set_without_pin(
    db_session, monkeypatch
):
    """Legacy credentialed batches without a pinned credential still download
    the CSV recording URL with provider auth."""
    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    call_import.telephony_integration_id = None
    call_import.provider = TelephonyProvider.EXOTEL.value
    db_session.commit()

    fake_client = _FakeExotelClient(audio=b"legacy-auth-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)
    public_calls = _patch_public_download(
        monkeypatch,
        return_value=(b"should-not-be-used", "audio/mpeg"),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"
    db_session.refresh(row)
    assert row.status == CallImportRowStatus.COMPLETED
    assert fake_client.resolved_calls == []
    assert fake_client.calls == [row.recording_url]
    assert public_calls == []


def test_process_call_import_row_direct_url_mode_completes(db_session, monkeypatch):
    org, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    call_import.telephony_integration_id = None
    call_import.provider = None
    db_session.commit()

    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(
        monkeypatch, db_session, _FakeExotelClient(), fake_s3
    )
    public_calls = _patch_public_download(
        monkeypatch, return_value=(b"direct-url-audio", "audio/mpeg")
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "completed"
    db_session.refresh(row)
    assert row.status == CallImportRowStatus.COMPLETED
    assert public_calls == [row.recording_url]
    assert row.recording_size_bytes == len(b"direct-url-audio")


def test_process_call_import_row_marks_failed_when_recording_url_missing(
    db_session, monkeypatch
):
    """Missing recording_url on an Exotel row is non-retryable."""

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]
    row.recording_url = None
    db_session.commit()

    class _ShouldNotDownload:
        def download_recording(self, _url):
            raise AssertionError("download_recording should not be called")

    fake_client = _ShouldNotDownload()
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    monkeypatch.setattr(
        task_module.process_call_import_row_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result["status"] == "failed"
    assert result["reason"] == "no_recording_source"

    db_session.refresh(row)
    db_session.refresh(call_import)
    assert row.status == CallImportRowStatus.FAILED
    assert "Exotel import requires a recording URL" in (row.error_message or "")
    assert call_import.status == CallImportStatus.FAILED


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


def test_process_call_import_row_releases_slot_and_redispatches(db_session, monkeypatch):
    from unittest.mock import MagicMock

    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    finish_mock = MagicMock()
    monkeypatch.setattr(
        "app.workers.concurrency.limits.slot_registered_for_task",
        lambda _task_id: True,
    )
    monkeypatch.setattr(
        "app.workers.concurrency.fair_import_dispatch.finish_import_work_and_redispatch",
        finish_mock,
    )

    result = task_module.process_call_import_row_task.run(
        str(row.id),
        _eval_slot_task_id="slot-task-abc",
    )

    assert result["status"] == "completed"
    finish_mock.assert_called_once_with("slot-task-abc")


def test_rollup_parent_status_preserves_deleting(db_session, monkeypatch):
    from app.workers.tasks.process_call_import_row import _rollup_parent_status

    monkeypatch.setattr(
        "app.services.call_imports.bulk_ops.is_sharding_enabled",
        lambda: False,
    )

    _, call_import, rows = _seed(db_session, row_count=2)
    call_import.status = CallImportStatus.DELETING
    rows[0].status = CallImportRowStatus.COMPLETED
    rows[1].status = CallImportRowStatus.PENDING
    db_session.commit()

    _rollup_parent_status(db_session, call_import)

    assert call_import.status == CallImportStatus.DELETING
    assert call_import.completed_rows == 1
    assert call_import.failed_rows == 0


def test_process_row_skips_when_parent_deleting(db_session, monkeypatch):
    _, call_import, rows = _seed(db_session, row_count=1)
    call_import.status = CallImportStatus.DELETING
    db_session.commit()
    row = rows[0]

    fake_client = _FakeExotelClient()
    fake_s3 = _FakeS3()
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result == {"status": "skipped", "reason": "import_deleting"}
    db_session.refresh(row)
    assert row.status == CallImportRowStatus.PENDING
    assert fake_client.calls == []
    assert fake_s3.uploads == []


def test_row_or_import_gone_after_row_deleted(db_session):
    from app.workers.tasks.process_call_import_row import _row_or_import_gone

    _, _call_import, rows = _seed(db_session, row_count=1)
    row_id = rows[0].id
    db_session.delete(rows[0])
    db_session.commit()

    assert _row_or_import_gone(db_session, row_id) == "row_deleted"


def test_process_row_skips_when_row_deleted_during_upload(db_session, monkeypatch):
    _, call_import, rows = _seed(db_session, row_count=1)
    row = rows[0]

    fake_client = _FakeExotelClient(audio=b"hello-audio", content_type="audio/mpeg")
    fake_s3 = _FakeS3(enabled=True)

    def _upload_then_delete(file_content, key, content_type="audio/mpeg"):
        fake_s3.uploads.append(
            {"key": key, "size": len(file_content), "content_type": content_type}
        )
        db_session.delete(row)
        db_session.commit()
        return key

    fake_s3.upload_file_by_key = _upload_then_delete
    task_module = _patch_dependencies(monkeypatch, db_session, fake_client, fake_s3)

    result = task_module.process_call_import_row_task.run(str(row.id))

    assert result == {"status": "skipped", "reason": "row_deleted"}
