"""Shared pytest fixtures for backend tests."""

import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Some local environments provide ALLOWED_AUDIO_FORMATS as a non-JSON string,
# which breaks pydantic-settings parsing during module import in tests.
os.environ["ALLOWED_AUDIO_FORMATS"] = '["wav","mp3","flac","m4a"]'
# Ensure storage service singletons can initialize in test environments.
os.environ["UPLOAD_DIR"] = "/tmp/efficientai-test-uploads"
# Local dev often sets SERVICE_MODE=media and config.yml media URLs; keep API tests on full app mode.
os.environ["SERVICE_MODE"] = "api"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
for _path in (str(_REPO_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_TASKS_PACKAGE_DIR = str(
    Path(__file__).resolve().parents[1] / "app" / "workers" / "tasks"
)


@pytest.fixture(autouse=True)
def isolate_service_mode_for_app_factory(monkeypatch):
    """Prevent local SERVICE_MODE / media URL config from breaking create_app tests."""
    from app.config import settings

    monkeypatch.setenv("SERVICE_MODE", "api")
    monkeypatch.setattr(settings, "SERVICE_MODE", "api", raising=False)
    monkeypatch.setattr(settings, "MEDIA_WS_BASE_URL", "", raising=False)
    yield


@pytest.fixture(autouse=True)
def disable_db_sharding_for_tests(monkeypatch, request):
    """Tests use one SQLAlchemy session; ignore production shard routing."""
    if request.node.get_closest_marker("integration"):
        yield
        return

    from app.config import settings
    from app.db_sharding.pool_manager import db_pool_manager

    monkeypatch.setattr(settings, "DB_SHARDING_ENABLED", False)
    db_pool_manager.reset()
    yield


@pytest.fixture(autouse=True)
def ensure_workers_tasks_package():
    """Keep ``app.workers.tasks`` importable without eager Celery imports."""
    import importlib

    workers_pkg = importlib.import_module("app.workers")
    tasks_pkg = sys.modules.get("app.workers.tasks")
    if tasks_pkg is None:
        tasks_pkg = types.ModuleType("app.workers.tasks")
        sys.modules["app.workers.tasks"] = tasks_pkg
    tasks_pkg.__path__ = [_TASKS_PACKAGE_DIR]
    workers_pkg.tasks = tasks_pkg

    helpers_pkg = sys.modules.get("app.workers.tasks.helpers")
    if helpers_pkg is None:
        helpers_pkg = types.ModuleType("app.workers.tasks.helpers")
        sys.modules["app.workers.tasks.helpers"] = helpers_pkg
    helpers_pkg.__path__ = [
        str(Path(__file__).resolve().parents[1] / "app" / "workers" / "tasks" / "helpers")
    ]


@pytest.fixture
def org_id():
    """Stable org UUID for auth-related tests."""
    return uuid4()


@pytest.fixture
def seed_org(db_session, org_id):
    from app.models.database import Organization

    org = db_session.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        org = Organization(id=org_id, name="Test Org")
        db_session.add(org)
        db_session.commit()
    return org


@pytest.fixture
def default_workspace(db_session, org_id, seed_org):
    from app.models.database import Workspace

    ws = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org_id,
            Workspace.is_default.is_(True),
        )
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db_session.add(ws)
        db_session.commit()
        db_session.refresh(ws)
    return ws


@pytest.fixture
def api_key():
    """Stable API key for authenticated test clients."""
    return "test_api_key_123"


def _xdist_worker_id(worker_id: str) -> str | None:
    """Return the xdist worker suffix (``gw0``), or None for serial runs."""
    if worker_id in ("master", "main"):
        return None
    return worker_id


def _worker_database_url(base_url: str, worker_id: str) -> str:
    """Give each xdist worker its own Postgres database to avoid DDL races."""
    suffix = _xdist_worker_id(worker_id)
    if suffix is None:
        return base_url
    parsed = make_url(base_url)
    db_name = parsed.database or "efficientai_test"
    return parsed.set(database=f"{db_name}_{suffix}").render_as_string(
        hide_password=False
    )


def _ensure_postgres_database(admin_url: str, database_name: str) -> None:
    """Create ``database_name`` if missing (connects via the admin database)."""
    admin = make_url(admin_url).set(database="postgres")
    bootstrap = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with bootstrap.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        bootstrap.dispose()


def _postgres_engine_kwargs(*, parallel: bool) -> dict:
    if parallel:
        # Many xdist workers × large pools exhaust Postgres connection limits.
        return {"pool_pre_ping": True, "pool_size": 1, "max_overflow": 2}
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


def _bind_runtime_database_url(database_url: str) -> None:
    """Keep SessionLocal/db_pool_manager on the same DB as the test engine."""
    os.environ["TEST_DATABASE_URL"] = database_url
    os.environ["DATABASE_URL"] = database_url
    from app.config import settings

    settings.DATABASE_URL = database_url


@pytest.fixture(scope="session")
def test_engine(worker_id):
    """
    Database engine used for tests.
    Defaults to in-memory SQLite for local speed, but can use a real database
    when TEST_DATABASE_URL is provided (for CI/Postgres validation).
    Schema is created once per test session and torn down at the end.

    With pytest-xdist, each worker gets its own Postgres database
    (``…_gw0``, ``…_gw1``, …) so parallel ``create_all()`` calls do not race
    on shared ENUM types.
    """
    from app.database import Base

    import app.models.database  # noqa: F401

    base_database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    parallel_postgres = bool(base_database_url and _xdist_worker_id(worker_id))

    if base_database_url:
        database_url = _worker_database_url(base_database_url, worker_id)
        parsed = make_url(database_url)
        if parsed.drivername.startswith("postgresql"):
            _ensure_postgres_database(base_database_url, parsed.database)
        _bind_runtime_database_url(database_url)
        engine = create_engine(
            database_url,
            **_postgres_engine_kwargs(parallel=parallel_postgres),
        )
        drop_schema_on_teardown = not parallel_postgres
    else:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        drop_schema_on_teardown = True

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        if drop_schema_on_teardown:
            Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Transaction-scoped SQLAlchemy session; rolls back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = TestingSessionLocal()
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):  # noqa: ARG001
        nonlocal nested
        if trans.nested and not trans._parent.nested:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


_SESSION_API_APP = None
_SESSION_STUBS_READY = False


def _install_static_stubs():
    if "python_multipart" not in sys.modules:
        fake_python_multipart = types.ModuleType("python_multipart")
        fake_python_multipart.__version__ = "0.0.20"
        sys.modules["python_multipart"] = fake_python_multipart

    if "multipart" not in sys.modules:
        fake_multipart = types.ModuleType("multipart")
        fake_multipart.__version__ = "0.0.20"
        fake_multipart_submodule = types.ModuleType("multipart.multipart")
        fake_multipart_submodule.parse_options_header = lambda *_args, **_kwargs: ("", {})
        sys.modules["multipart"] = fake_multipart
        sys.modules["multipart.multipart"] = fake_multipart_submodule

    if "boto3" not in sys.modules:
        fake_boto3 = types.ModuleType("boto3")
        fake_boto3.client = lambda *_args, **_kwargs: object()
        sys.modules["boto3"] = fake_boto3

    if "botocore.exceptions" not in sys.modules:
        fake_botocore = types.ModuleType("botocore")
        fake_exceptions = types.ModuleType("botocore.exceptions")

        class _ClientError(Exception):
            pass

        class _NoCredentialsError(Exception):
            pass

        fake_exceptions.ClientError = _ClientError
        fake_exceptions.NoCredentialsError = _NoCredentialsError
        fake_botocore.exceptions = fake_exceptions
        sys.modules["botocore"] = fake_botocore
        sys.modules["botocore.exceptions"] = fake_exceptions

    if "croniter" not in sys.modules:
        fake_croniter_module = types.ModuleType("croniter")

        class _FakeCroniter:
            def __init__(self, _expression, start_time=None):
                self._start_time = start_time

            def get_next(self, _type):
                from datetime import timedelta

                if self._start_time is None:
                    raise ValueError("start_time is required")
                return self._start_time + timedelta(minutes=5)

        fake_croniter_module.croniter = _FakeCroniter
        sys.modules["croniter"] = fake_croniter_module

    if "pytz" not in sys.modules:
        from datetime import timezone as _timezone

        fake_pytz_module = types.ModuleType("pytz")

        class _UnknownTimeZoneError(Exception):
            pass

        def _timezone_factory(name):
            if not name:
                raise _UnknownTimeZoneError("Unknown timezone")
            return _timezone.utc

        fake_pytz_module.timezone = _timezone_factory
        fake_pytz_module.UTC = _timezone.utc
        fake_pytz_module.UnknownTimeZoneError = _UnknownTimeZoneError
        sys.modules["pytz"] = fake_pytz_module

    if "app.services.audio" not in sys.modules:
        fake_audio_pkg = types.ModuleType("app.services.audio")
        fake_audio_pkg.__path__ = []
        fake_audio_service_module = types.ModuleType("app.services.audio.audio_service")
        fake_voice_quality_module = types.ModuleType("app.services.audio.voice_quality_service")

        class _FakeAudioService:
            def extract_metadata(self, _file_path):
                return {"duration": None, "sample_rate": None, "channels": None}

        fake_voice_quality_module.AUDIO_METRICS = []
        fake_voice_quality_module.is_audio_metric = lambda *_args, **_kwargs: False
        fake_voice_quality_module.calculate_audio_metrics = lambda *_args, **_kwargs: {}
        fake_audio_service_module.AudioService = _FakeAudioService
        fake_audio_pkg.audio_service = fake_audio_service_module
        fake_audio_pkg.voice_quality_service = fake_voice_quality_module
        sys.modules["app.services.audio"] = fake_audio_pkg
        sys.modules["app.services.audio.audio_service"] = fake_audio_service_module
        sys.modules["app.services.audio.voice_quality_service"] = fake_voice_quality_module

    if "app.services.ai" not in sys.modules:
        fake_ai_pkg = types.ModuleType("app.services.ai")
        # Point the stubbed package at the real on-disk directory so
        # genuinely-needed submodules (like ``llm_resolver``) can still
        # be imported from disk even when the rest of the package is
        # replaced by light stubs above.
        import os as _os

        _real_ai_dir = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
            "app",
            "services",
            "ai",
        )
        fake_ai_pkg.__path__ = [_real_ai_dir]
        fake_model_config_module = types.ModuleType("app.services.ai.model_config_service")
        fake_llm_module = types.ModuleType("app.services.ai.llm_service")
        fake_transcription_module = types.ModuleType("app.services.ai.transcription_service")

        class _FakeModelConfigService:
            def get_all_models(self):
                return {}

            def get_model_config(self, *_args, **_kwargs):
                return None

            def get_models_by_provider(self, *_args, **_kwargs):
                return []

            def get_model_options_by_provider(self, *_args, **_kwargs):
                return {"stt": [], "llm": [], "tts": [], "s2s": []}

            def get_tts_voices_by_provider(self, *_args, **_kwargs):
                return {}

            def get_models_by_type(self, *_args, **_kwargs):
                return []

            def get_voices_for_model(self, *_args, **_kwargs):
                return []

        class _FakeLLMService:
            def generate_response(self, *_args, **_kwargs):
                return {"text": '{"objective_achieved": false, "overall_score": 0.0}', "usage": {}}

        class _FakeTranscriptionService:
            def transcribe(self, *_args, **_kwargs):
                return {"transcript": "test transcript", "processing_time": 0.1}

        fake_model_config_module.model_config_service = _FakeModelConfigService()
        fake_llm_module.llm_service = _FakeLLMService()
        fake_llm_module._resolve_azure_endpoint_from_provider = lambda *_args, **_kwargs: None
        fake_transcription_module.transcription_service = _FakeTranscriptionService()
        fake_ai_pkg.model_config_service = fake_model_config_module
        fake_ai_pkg.llm_service = fake_llm_module
        fake_ai_pkg.transcription_service = fake_transcription_module
        sys.modules["app.services.ai"] = fake_ai_pkg
        sys.modules["app.services.ai.model_config_service"] = fake_model_config_module
        sys.modules["app.services.ai.llm_service"] = fake_llm_module
        sys.modules["app.services.ai.transcription_service"] = fake_transcription_module

    if "app.services.testing.test_agent_service" not in sys.modules:
        fake_testing_pkg = types.ModuleType("app.services.testing")
        fake_testing_pkg.__path__ = []
        fake_test_agent_service_module = types.ModuleType("app.services.testing.test_agent_service")

        class _FakeTestAgentService:
            def create_conversation(self, *args, **kwargs):  # pragma: no cover - overridden in tests
                raise ValueError("Not implemented in base test stub")

            def start_conversation(self, *args, **kwargs):  # pragma: no cover - overridden in tests
                raise ValueError("Not implemented in base test stub")

            def process_audio_chunk(self, *_args, **_kwargs):
                return {"transcription": "ok", "metadata": {}, "error": None}

            def end_conversation(self, *args, **kwargs):  # pragma: no cover - overridden in tests
                raise ValueError("Not implemented in base test stub")

        fake_test_agent_service_module.test_agent_service = _FakeTestAgentService()
        fake_testing_pkg.test_agent_service = fake_test_agent_service_module
        sys.modules["app.services.testing"] = fake_testing_pkg
        sys.modules["app.services.testing.test_agent_service"] = fake_test_agent_service_module

    if "app.services.voice_providers" not in sys.modules:
        fake_voice_providers_module = types.ModuleType("app.services.voice_providers")

        class _FakeVoiceProvider:
            def __init__(self, *args, **kwargs):
                pass

            def create_web_call(self, **_kwargs):
                return {"call_id": "fake-call-id"}

            def update_agent_prompt(self, **_kwargs):
                return {"ok": True}

        fake_voice_providers_module.get_voice_provider = lambda *_args, **_kwargs: _FakeVoiceProvider
        fake_voice_providers_module.sync_provider_prompt = lambda *_args, **_kwargs: {"synced": False}
        sys.modules["app.services.voice_providers"] = fake_voice_providers_module

    if "app.services.voice_agent.bot_fast_api" not in sys.modules:
        voice_agent_dir = str(
            Path(__file__).resolve().parents[1] / "app" / "services" / "voice_agent"
        )
        fake_voice_agent_pkg = types.ModuleType("app.services.voice_agent")
        fake_voice_agent_pkg.__path__ = [voice_agent_dir]
        fake_bot_fast_api_module = types.ModuleType("app.services.voice_agent.bot_fast_api")
        fake_voice_bundle_module = types.ModuleType("app.services.voice_agent.voice_bundle")
        fake_bot_fast_api_module.run_bot = lambda *_args, **_kwargs: None
        fake_voice_bundle_module.run_voice_bundle_fastapi = lambda *_args, **_kwargs: None
        sys.modules["app.services.voice_agent"] = fake_voice_agent_pkg
        sys.modules["app.services.voice_agent.bot_fast_api"] = fake_bot_fast_api_module
        sys.modules["app.services.voice_agent.voice_bundle"] = fake_voice_bundle_module

    if "app.services.reporting.voice_playground_report_service" not in sys.modules:
        fake_reporting_pkg = types.ModuleType("app.services.reporting")
        fake_reporting_pkg.__path__ = [
            str(Path(__file__).resolve().parents[1] / "app" / "services" / "reporting")
        ]
        fake_report_service_module = types.ModuleType("app.services.reporting.voice_playground_report_service")

        class _FakeVoicePlaygroundReportService:
            def get_threshold_defaults(self, *_args, **_kwargs):
                return {}

            def update_threshold_defaults(self, *_args, **_kwargs):
                return {}

        fake_report_service_module.voice_playground_report_service = _FakeVoicePlaygroundReportService()
        sys.modules["app.services.reporting"] = fake_reporting_pkg
        sys.modules["app.services.reporting.voice_playground_report_service"] = fake_report_service_module

    fake_workers_tasks_pkg = sys.modules.get("app.workers.tasks")
    if fake_workers_tasks_pkg is None:
        fake_workers_tasks_pkg = types.ModuleType("app.workers.tasks")
        sys.modules["app.workers.tasks"] = fake_workers_tasks_pkg
    fake_workers_tasks_pkg.__path__ = [_TASKS_PACKAGE_DIR]

    # ``app.workers.tasks`` is stubbed with an empty ``__path__`` so Celery
    # task modules are not eagerly imported, but several API routes and tests
    # still need the real ``helpers`` subpackage (e.g. the diariser default
    # prompt endpoint). Register it explicitly so
    # ``app.workers.tasks.helpers.llm_diarisation`` resolves normally.
    if "app.workers.tasks.helpers" not in sys.modules:
        helpers_pkg = types.ModuleType("app.workers.tasks.helpers")
        helpers_pkg.__path__ = [
            str(
                Path(__file__).resolve().parents[1]
                / "app"
                / "workers"
                / "tasks"
                / "helpers"
            )
        ]
        sys.modules["app.workers.tasks.helpers"] = helpers_pkg

    fake_run_prompt_opt_module = sys.modules.get("app.workers.tasks.run_prompt_optimization")
    if fake_run_prompt_opt_module is None:
        fake_run_prompt_opt_module = types.ModuleType("app.workers.tasks.run_prompt_optimization")
        sys.modules["app.workers.tasks.run_prompt_optimization"] = fake_run_prompt_opt_module

    class _FakePromptOptTask:
        def delay(self, *_args, **_kwargs):
            class _TaskResult:
                id = "fake-prompt-opt-task-id"

            return _TaskResult()

    # Ensure these symbols always exist for API tests, regardless of import order.
    fake_run_prompt_opt_module.run_prompt_optimization_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.process_evaluation_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.process_evaluator_result_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.run_evaluator_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.generate_tts_comparison_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.evaluate_tts_comparison_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.generate_tts_report_pdf_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.run_prompt_optimization_task = _FakePromptOptTask()
    # Required by app.workers.celery_app's eager import block - missing
    # these makes any test that imports a route file fail before the
    # fixture can install dependency overrides.
    fake_workers_tasks_pkg.process_call_import_row_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.evaluate_call_import_row_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.transcribe_call_import_row_task = _FakePromptOptTask()
    fake_workers_tasks_pkg.run_judge_alignment_task = _FakePromptOptTask()

    class _FakeCeleryApp:
        """Minimal Celery stand-in for route / worker imports in API tests."""

        control = types.SimpleNamespace(revoke=lambda *_args, **_kwargs: None)

        def task(self, *_args, **_kwargs):
            def _decorator(fn):
                fn.delay = lambda *_a, **_kw: types.SimpleNamespace(id="fake-task")
                fn.apply_async = lambda *_a, **_kw: types.SimpleNamespace(
                    id="fake-task"
                )
                fn.run = fn
                return fn

            return _decorator

    fake_config_module = types.ModuleType("app.workers.config")
    fake_config_module.celery_app = _FakeCeleryApp()
    sys.modules["app.workers.config"] = fake_config_module

    fake_celery_app_module = types.ModuleType("app.workers.celery_app")
    fake_celery_app_module.celery_app = fake_config_module.celery_app
    fake_celery_app_module.process_evaluation_task = _FakePromptOptTask()
    fake_celery_app_module.process_evaluator_result_task = _FakePromptOptTask()
    fake_celery_app_module.run_evaluator_task = _FakePromptOptTask()
    fake_celery_app_module.generate_tts_comparison_task = _FakePromptOptTask()
    fake_celery_app_module.evaluate_tts_comparison_task = _FakePromptOptTask()
    fake_celery_app_module.generate_tts_report_pdf_task = _FakePromptOptTask()
    fake_celery_app_module.run_prompt_optimization_task = _FakePromptOptTask()
    fake_celery_app_module.process_call_import_row_task = _FakePromptOptTask()
    fake_celery_app_module.run_judge_alignment_task = _FakePromptOptTask()
    sys.modules["app.workers.celery_app"] = fake_celery_app_module
    import importlib

    workers_pkg = importlib.import_module("app.workers")
    workers_pkg.celery_app = fake_celery_app_module

def _wire_bulk_ops_stubs(db_session):
    # Bulk call-import tasks: materialize runs synchronously in API tests;
    # diarize/delete are no-ops (return immediately).
    fake_bulk_ops_module = sys.modules.get("app.workers.tasks.call_import_bulk_ops")
    if fake_bulk_ops_module is None:
        fake_bulk_ops_module = types.ModuleType("app.workers.tasks.call_import_bulk_ops")
        sys.modules["app.workers.tasks.call_import_bulk_ops"] = fake_bulk_ops_module

    def _sync_materialize_delay(evaluation_id, *, transcribe_overwrite=False):
        from uuid import UUID

        from app.services.call_imports.bulk_ops import materialize_and_enqueue_evaluation

        materialize_and_enqueue_evaluation(
            db_session,
            UUID(evaluation_id),
            transcribe_overwrite=transcribe_overwrite,
        )
        return types.SimpleNamespace(id="fake-sync-bulk-task")

    class _NoopBulkTask:
        @staticmethod
        def delay(*_args, **_kwargs):
            return types.SimpleNamespace(id="fake-sync-bulk-task")

    fake_bulk_ops_module.materialize_call_import_evaluation_task = types.SimpleNamespace(
        delay=_sync_materialize_delay
    )

    def _sync_mapped_materialize_delay(
        call_import_id,
        organization_id,
        workspace_id,
        evaluation_id,
        *,
        transcribe_overwrite=False,
    ):
        from uuid import UUID

        from app.services.call_imports.bulk_ops import (
            execute_call_import_materialization,
            materialize_and_enqueue_evaluation,
        )

        mat_result = execute_call_import_materialization(
            db_session,
            UUID(call_import_id),
            UUID(organization_id),
            UUID(workspace_id),
            schedule_import_dispatch=False,
        )
        if mat_result.get("status") != "failed":
            materialize_and_enqueue_evaluation(
                db_session,
                UUID(evaluation_id),
                transcribe_overwrite=transcribe_overwrite,
            )
        return types.SimpleNamespace(id="fake-sync-mapped-bulk-task")

    fake_bulk_ops_module.materialize_mapped_call_import_evaluation_task = (
        types.SimpleNamespace(delay=_sync_mapped_materialize_delay)
    )

    def _sync_import_materialize_delay(call_import_id, organization_id, workspace_id):
        from uuid import UUID

        from app.services.call_imports.bulk_ops import execute_call_import_materialization

        execute_call_import_materialization(
            db_session,
            UUID(call_import_id),
            UUID(organization_id),
            UUID(workspace_id),
        )
        return types.SimpleNamespace(id="fake-sync-bulk-task")

    fake_bulk_ops_module.materialize_call_import_rows_task = types.SimpleNamespace(
        delay=_sync_import_materialize_delay
    )
    fake_bulk_ops_module.bulk_diarize_call_import_task = _NoopBulkTask()
    fake_bulk_ops_module.bulk_delete_call_import_rows_task = _NoopBulkTask()
    fake_bulk_ops_module.delete_call_import_task = _NoopBulkTask()

    def _sync_retry_delay(evaluation_id, payload_dict):
        from uuid import UUID

        eval_row_ids_raw = payload_dict.get("eval_row_ids")
        metric_ids_raw = payload_dict.get("metric_ids")
        from app.services.call_imports.bulk_ops import execute_evaluation_retry

        execute_evaluation_retry(
            db_session,
            UUID(evaluation_id),
            eval_row_ids=(
                [UUID(rid) for rid in eval_row_ids_raw]
                if eval_row_ids_raw
                else None
            ),
            metric_ids=(
                [UUID(mid) for mid in metric_ids_raw] if metric_ids_raw else None
            ),
            include_completed=bool(payload_dict.get("include_completed", False)),
            transcribe_overwrite=bool(payload_dict.get("transcribe_overwrite", False)),
        )
        return types.SimpleNamespace(id="fake-sync-retry-task")

    fake_bulk_ops_module.retry_call_import_evaluation_task = types.SimpleNamespace(
        delay=_sync_retry_delay
    )

    def _sync_cancel_delay(evaluation_id, *, mode):
        from uuid import UUID

        from app.services.call_imports.bulk_ops import execute_evaluation_cancel

        execute_evaluation_cancel(db_session, UUID(evaluation_id), mode=mode)
        return types.SimpleNamespace(id="fake-sync-cancel-task")

    fake_bulk_ops_module.cancel_call_import_evaluation_task = types.SimpleNamespace(
        delay=_sync_cancel_delay
    )

def _install_concurrency_stubs():
    fake_fair_dispatch_module = sys.modules.get("app.workers.concurrency.fair_dispatch")
    if fake_fair_dispatch_module is None:
        fake_fair_dispatch_module = types.ModuleType(
            "app.workers.concurrency.fair_dispatch"
        )
        sys.modules["app.workers.concurrency.fair_dispatch"] = (
            fake_fair_dispatch_module
        )
    if not hasattr(fake_fair_dispatch_module, "schedule_fair_dispatch"):
        fake_fair_dispatch_module.schedule_fair_dispatch = lambda *_a, **_kw: None
    if not hasattr(fake_fair_dispatch_module, "store_row_restricted_metrics"):
        fake_fair_dispatch_module.store_row_restricted_metrics = lambda *_a, **_kw: None
    if not hasattr(fake_fair_dispatch_module, "store_evaluation_transcribe_overwrite"):
        fake_fair_dispatch_module.store_evaluation_transcribe_overwrite = (
            lambda *_a, **_kw: None
        )
    if not hasattr(fake_fair_dispatch_module, "read_fair_dispatch_state"):
        fake_fair_dispatch_module.read_fair_dispatch_state = lambda: {
            "global_rr_cursor": 0,
            "dispatch_dedupe_active": False,
            "dispatch_queue": "celery",
            "at_capacity_backoff_seconds": 15,
        }
    if not hasattr(fake_fair_dispatch_module, "read_workspace_eval_rr_cursor"):
        fake_fair_dispatch_module.read_workspace_eval_rr_cursor = lambda _ws_id: 0
    if not hasattr(fake_fair_dispatch_module, "finish_eval_work_and_redispatch"):
        fake_fair_dispatch_module.finish_eval_work_and_redispatch = (
            lambda *_a, **_kw: None
        )

    def _ensure_concurrency_submodule(name: str) -> types.ModuleType:
        full_name = f"app.workers.concurrency.{name}"
        module = sys.modules.get(full_name)
        if module is None:
            module = types.ModuleType(full_name)
            sys.modules[full_name] = module
        return module

    for submodule, attrs in {
        "fair_diarization_dispatch": (
            "finish_diarization_work_and_redispatch",
            "schedule_fair_diarization_dispatch",
        ),
        "fair_import_dispatch": (
            "finish_import_work_and_redispatch",
            "schedule_fair_import_dispatch",
        ),
        "diarization_dispatch": (
            "build_diarization_params_from_request",
            "store_row_diarization_params",
        ),
        "limits": (
            "acquire_eval_slot",
            "release_eval_slot_for_celery_task",
            "slot_registered_for_task",
        ),
    }.items():
        mod = _ensure_concurrency_submodule(submodule)
        for attr in attrs:
            if not hasattr(mod, attr):
                setattr(mod, attr, lambda *_a, **_kw: None)

    limits_mod = _ensure_concurrency_submodule("limits")
    for attr in (
        "read_global_inflight",
        "read_org_inflight",
        "read_workspace_inflight",
        "read_job_inflight",
    ):
        if not hasattr(limits_mod, attr):
            setattr(limits_mod, attr, lambda *_a, **_kw: 0)

    fake_eval_dispatch_module = sys.modules.get("app.workers.concurrency.eval_dispatch")
    if fake_eval_dispatch_module is None:
        fake_eval_dispatch_module = types.ModuleType(
            "app.workers.concurrency.eval_dispatch"
        )
        sys.modules["app.workers.concurrency.eval_dispatch"] = fake_eval_dispatch_module
    for queue_name in ("DIARIZATION_QUEUE", "EVALUATIONS_QUEUE", "IMPORTS_QUEUE"):
        if not hasattr(fake_eval_dispatch_module, queue_name):
            setattr(
                fake_eval_dispatch_module,
                queue_name,
                queue_name.replace("_QUEUE", "").lower(),
            )
    if not hasattr(fake_eval_dispatch_module, "schedule_evaluation_dispatch"):
        fake_eval_dispatch_module.schedule_evaluation_dispatch = lambda *_a, **_kw: None


def _build_session_api_app():
    import app.dependencies as app_dependencies
    from app.api.v1.routes import (
        aiproviders,
        agents,
        alerts,
        audio,
        auth,
        llm_gateway,
        call_import_evaluations,
        call_import_schemas,
        call_import_tags,
        call_imports,
        chat,
        conversation_evaluations,
        cron_jobs,
        data_sources,
        evaluations,
        evaluator_results,
        evaluators,
        evaluator_suites,
        iam,
        integrations,
        manual_evaluations,
        metrics,
        model_config,
        observability,
        personas,
        playground,
        profile,
        prompt_optimization,
        prompt_partials,
        results,
        scenarios,
        settings,
        telephony,
        test_agents,
        voice_agent,
        voice_playground,
        voicebundles,
        vobiz_telephony,
        workspaces,
        workspace_iam,
        platform_admin,
        metric_studio,
    )

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(evaluations.router, prefix="/api/v1")
    app.include_router(results.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(evaluators.router, prefix="/api/v1")
    app.include_router(evaluator_suites.router, prefix="/api/v1")
    app.include_router(personas.router, prefix="/api/v1")
    app.include_router(scenarios.router, prefix="/api/v1")
    app.include_router(settings.router, prefix="/api/v1")
    app.include_router(iam.router, prefix="/api/v1")
    app.include_router(audio.router, prefix="/api/v1")
    app.include_router(integrations.router, prefix="/api/v1")
    app.include_router(aiproviders.router, prefix="/api/v1")
    app.include_router(llm_gateway.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(evaluator_results.router, prefix="/api/v1")
    app.include_router(voicebundles.router, prefix="/api/v1")
    app.include_router(test_agents.router, prefix="/api/v1")
    app.include_router(manual_evaluations.router, prefix="/api/v1")
    app.include_router(conversation_evaluations.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(model_config.router, prefix="/api/v1")
    app.include_router(data_sources.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(prompt_partials.router, prefix="/api/v1")
    app.include_router(cron_jobs.router, prefix="/api/v1")
    app.include_router(profile.router, prefix="/api/v1")
    app.include_router(observability.router, prefix="/api/v1")
    app.include_router(playground.router, prefix="/api/v1")
    app.include_router(prompt_optimization.router, prefix="/api/v1")
    app.include_router(voice_agent.router, prefix="/api/v1")
    app.include_router(voice_playground.router, prefix="/api/v1")
    app.include_router(telephony.router, prefix="/api/v1")
    app.include_router(vobiz_telephony.router, prefix="/api/v1")
    app.include_router(call_imports.router, prefix="/api/v1")
    app.include_router(call_import_schemas.router, prefix="/api/v1")
    app.include_router(call_import_tags.router, prefix="/api/v1")
    app.include_router(call_import_evaluations.router, prefix="/api/v1")
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(workspace_iam.router, prefix="/api/v1")
    app.include_router(platform_admin.router, prefix="/api/v1")
    app.include_router(metric_studio.router, prefix="/api/v1")
    # Enterprise route dependencies call app.dependencies.is_feature_enabled at runtime.
    # Force-enable it for API tests so tests remain focused on route behavior.
    app_dependencies.is_feature_enabled = lambda *_args, **_kwargs: True

    @asynccontextmanager
    async def _noop_lifespan(_: object):
        yield

    app.router.lifespan_context = _noop_lifespan
    return app

@pytest.fixture
def client(db_session, api_key, org_id):
    """
    FastAPI client with DB/auth dependency overrides and no startup lifespan.
    This avoids running migrations in test bootstrap.
    """
    global _SESSION_API_APP, _SESSION_STUBS_READY

    if not _SESSION_STUBS_READY:
        _install_static_stubs()
        _install_concurrency_stubs()
        _SESSION_API_APP = _build_session_api_app()
        _SESSION_STUBS_READY = True

    _wire_bulk_ops_stubs(db_session)

    from app.database import get_db
    from app.dependencies import (
        get_api_key,
        get_organization_id,
        get_workspace_context,
        get_workspace_id,
        require_enterprise_feature,
        WorkspaceContext,
    )
    from app.core.auth.capabilities import ALL_CAPABILITIES
    from app.models.database import Organization, Workspace
    from app.services.workspace_rbac import backfill_org_workspace_memberships, seed_system_workspace_roles

    app = _SESSION_API_APP

    def _override_workspace_context() -> WorkspaceContext:
        return WorkspaceContext(
            workspace_id=default_workspace.id,
            organization_id=org_id,
            capabilities=frozenset(ALL_CAPABILITIES),
            is_org_admin=True,
        )
    # The TestClient flow doesn't run migration 033, so we manually
    # ensure the test org has a Default workspace before any route
    # that depends on ``get_workspace_id`` runs. This mirrors what the
    # real migration would have produced.
    def _ensure_default_workspace() -> Workspace:
        org = (
            db_session.query(Organization)
            .filter(Organization.id == org_id)
            .first()
        )
        if org is None:
            org = Organization(id=org_id, name="Test Organization")
            db_session.add(org)
            db_session.flush()
        ws = (
            db_session.query(Workspace)
            .filter(
                Workspace.organization_id == org_id,
                Workspace.is_default.is_(True),
            )
            .first()
        )
        if ws is None:
            ws = Workspace(
                organization_id=org_id,
                name="Default",
                slug="default",
                is_default=True,
            )
            db_session.add(ws)
            db_session.commit()
        seed_system_workspace_roles(db_session, organization_id=org_id)
        return ws

    default_workspace = _ensure_default_workspace()
    backfill_org_workspace_memberships(db_session, organization_id=org_id)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_api_key] = lambda: api_key
    app.dependency_overrides[get_organization_id] = lambda: org_id
    app.dependency_overrides[get_workspace_id] = lambda: default_workspace.id
    app.dependency_overrides[get_workspace_context] = _override_workspace_context
    app.dependency_overrides[require_enterprise_feature] = lambda: None

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def telephony_client(db_session):
    """Telephony edge TestClient (Vobiz carrier webhooks + media WebSocket routes only)."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.routes import vobiz_telephony
    from app.database import get_db

    app = FastAPI()

    @asynccontextmanager
    async def _noop_lifespan(_: object):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.include_router(vobiz_telephony.webhook_router, prefix="/api/v1")
    app.include_router(vobiz_telephony.ws_router, prefix="/api/v1")

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def authenticated_client(client, api_key, db_session, org_id):
    """Client pre-populated with auth header and a real API key in the DB."""
    from app.models.database import APIKey, Organization, OrganizationMember, RoleEnum, User

    existing_org = db_session.query(Organization).filter(Organization.id == org_id).first()
    if existing_org is None:
        db_session.add(Organization(id=org_id, name="Test Organization"))
        db_session.flush()

    existing_key = (
        db_session.query(APIKey)
        .filter(APIKey.key == api_key, APIKey.organization_id == org_id)
        .first()
    )
    if existing_key is None:
        user = User(
            id=uuid4(),
            email="owner@example.com",
            name="Org Owner",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=user.id,
                role=RoleEnum.ADMIN.value,
            )
        )
        db_session.add(
            APIKey(
                id=uuid4(),
                key=api_key,
                name="Test API Key",
                organization_id=org_id,
                user_id=user.id,
                is_active=True,
            )
        )
        db_session.commit()

    client.headers.update({"X-API-Key": api_key})
    return client


@pytest.fixture
def payload_factory():
    """Factory helpers for common API payload shapes."""

    def _agent_payload(**overrides):
        payload = {
            "name": "Test Agent",
            "phone_number": "+1234567890",
            "language": "en",
            "description": "This is a test agent description with enough words to pass validation.",
            "call_type": "outbound",
            "call_medium": "phone_call",
            "voice_ai_integration_id": str(uuid4()),
            "voice_ai_agent_id": "agent_123",
        }
        payload.update(overrides)
        return payload

    def _persona_payload(**overrides):
        payload = {
            "name": "Test Persona",
            "gender": "neutral",
            "is_custom": False,
        }
        payload.update(overrides)
        return payload

    def _scenario_payload(**overrides):
        payload = {
            "name": "Test Scenario",
            "description": "Simple test scenario for backend API tests.",
        }
        payload.update(overrides)
        return payload

    def _evaluation_payload(**overrides):
        payload = {
            "audio_id": str(uuid4()),
            "evaluation_type": "asr",
            "metrics": ["wer", "latency"],
        }
        payload.update(overrides)
        return payload

    return {
        "agent": _agent_payload,
        "persona": _persona_payload,
        "scenario": _scenario_payload,
        "evaluation": _evaluation_payload,
    }
