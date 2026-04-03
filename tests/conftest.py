"""Shared pytest fixtures for backend tests."""

import os
import sys
import types
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Some local environments provide ALLOWED_AUDIO_FORMATS as a non-JSON string,
# which breaks pydantic-settings parsing during module import in tests.
os.environ["ALLOWED_AUDIO_FORMATS"] = '["wav","mp3","flac","m4a"]'
# Ensure storage service singletons can initialize in test environments.
os.environ["UPLOAD_DIR"] = "/tmp/efficientai-test-uploads"


@pytest.fixture
def org_id():
    """Stable org UUID for auth-related tests."""
    return uuid4()


@pytest.fixture
def api_key():
    """Stable API key for authenticated test clients."""
    return "test_api_key_123"


@pytest.fixture
def test_engine():
    """
    Database engine used for tests.
    Defaults to in-memory SQLite for local speed, but can use a real database
    when TEST_DATABASE_URL is provided (for CI/Postgres validation).
    """
    test_database_url = os.getenv("TEST_DATABASE_URL", "").strip()

    if test_database_url:
        engine = create_engine(test_database_url, pool_pre_ping=True)
    else:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return engine


@pytest.fixture
def db_session(test_engine):
    """Create a transaction-scoped SQLAlchemy session for a test."""
    from app.database import Base

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session, api_key, org_id):
    """
    FastAPI client with DB/auth dependency overrides and no startup lifespan.
    This avoids running migrations in test bootstrap.
    """
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
        fake_ai_pkg.__path__ = []
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
        fake_voice_agent_pkg = types.ModuleType("app.services.voice_agent")
        fake_voice_agent_pkg.__path__ = []
        fake_bot_fast_api_module = types.ModuleType("app.services.voice_agent.bot_fast_api")
        fake_voice_bundle_module = types.ModuleType("app.services.voice_agent.voice_bundle")
        fake_bot_fast_api_module.run_bot = lambda *_args, **_kwargs: None
        fake_voice_bundle_module.run_voice_bundle_fastapi = lambda *_args, **_kwargs: None
        sys.modules["app.services.voice_agent"] = fake_voice_agent_pkg
        sys.modules["app.services.voice_agent.bot_fast_api"] = fake_bot_fast_api_module
        sys.modules["app.services.voice_agent.voice_bundle"] = fake_voice_bundle_module

    if "app.services.reporting.voice_playground_report_service" not in sys.modules:
        fake_reporting_pkg = types.ModuleType("app.services.reporting")
        fake_reporting_pkg.__path__ = []
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
        fake_workers_tasks_pkg.__path__ = []
        sys.modules["app.workers.tasks"] = fake_workers_tasks_pkg

    fake_run_prompt_opt_module = sys.modules.get("app.workers.tasks.run_prompt_optimization")
    if fake_run_prompt_opt_module is None:
        fake_run_prompt_opt_module = types.ModuleType("app.workers.tasks.run_prompt_optimization")
        sys.modules["app.workers.tasks.run_prompt_optimization"] = fake_run_prompt_opt_module

    class _FakePromptOptTask:
        @staticmethod
        def delay(*_args, **_kwargs):
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

    from app.database import get_db
    from app.dependencies import get_api_key, get_organization_id, require_enterprise_feature
    from app.api.v1.routes import (
        aiproviders,
        agents,
        alerts,
        audio,
        auth,
        chat,
        conversation_evaluations,
        cron_jobs,
        data_sources,
        evaluations,
        evaluator_results,
        evaluators,
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
        test_agents,
        voice_agent,
        voice_playground,
        voicebundles,
    )

    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(evaluations.router, prefix="/api/v1")
    app.include_router(results.router, prefix="/api/v1")
    app.include_router(agents.router, prefix="/api/v1")
    app.include_router(evaluators.router, prefix="/api/v1")
    app.include_router(personas.router, prefix="/api/v1")
    app.include_router(scenarios.router, prefix="/api/v1")
    app.include_router(settings.router, prefix="/api/v1")
    app.include_router(iam.router, prefix="/api/v1")
    app.include_router(audio.router, prefix="/api/v1")
    app.include_router(integrations.router, prefix="/api/v1")
    app.include_router(aiproviders.router, prefix="/api/v1")
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

    def _override_get_db():
        yield db_session

    @asynccontextmanager
    async def _noop_lifespan(_: object):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_api_key] = lambda: api_key
    app.dependency_overrides[get_organization_id] = lambda: org_id
    app.dependency_overrides[require_enterprise_feature] = lambda: None

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def authenticated_client(client, api_key):
    """Client pre-populated with auth header."""
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
