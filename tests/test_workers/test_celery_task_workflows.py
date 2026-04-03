"""Tests for Celery worker task workflows."""

import importlib
import sys
import types
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.database import (
    Agent,
    EvaluatorResult,
    Metric,
    Organization,
    PromptOptimizationRun,
    TTSComparison,
    TTSSample,
)


class RetryCalled(Exception):
    """Raised by task.retry in tests to assert retry paths."""


def _seed_org(db_session):
    org = Organization(id=uuid4(), name="Worker Test Org")
    db_session.add(org)
    db_session.commit()
    return org


def test_process_evaluation_returns_service_result_on_success(db_session, monkeypatch):
    from app.workers.tasks import process_evaluation as task_module

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    fake_eval_module = types.ModuleType("app.services.evaluation.evaluation_service")

    class _EvalService:
        @staticmethod
        def process_evaluation(eval_id, _db):
            return {"evaluation_id": str(eval_id), "status": "completed"}

    fake_eval_module.evaluation_service = _EvalService()
    monkeypatch.setitem(sys.modules, "app.services.evaluation.evaluation_service", fake_eval_module)

    result = task_module.process_evaluation_task.run(str(uuid4()))

    assert result["status"] == "completed"


def test_process_evaluation_retries_when_service_raises_exception(db_session, monkeypatch):
    from app.workers.tasks import process_evaluation as task_module

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    fake_eval_module = types.ModuleType("app.services.evaluation.evaluation_service")

    class _EvalService:
        @staticmethod
        def process_evaluation(_eval_id, _db):
            raise RuntimeError("processing failed")

    fake_eval_module.evaluation_service = _EvalService()
    monkeypatch.setitem(sys.modules, "app.services.evaluation.evaluation_service", fake_eval_module)

    monkeypatch.setattr(
        task_module.process_evaluation_task,
        "retry",
        lambda exc, countdown: (_ for _ in ()).throw(RetryCalled((exc, countdown))),
    )
    with pytest.raises(RetryCalled):
        task_module.process_evaluation_task.run(str(uuid4()))


def test_process_evaluator_result_returns_error_when_result_missing(db_session, monkeypatch):
    from app.workers.tasks import process_evaluator_result as task_module

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    result = task_module.process_evaluator_result_task.run(str(uuid4()))

    assert result == {"error": "Evaluator result not found"}


def test_process_evaluator_result_uses_existing_transcript_and_adds_call_analysis(
    db_session, test_engine, monkeypatch
):
    from app.workers.tasks import process_evaluator_result as task_module

    org = _seed_org(db_session)
    eval_result = EvaluatorResult(
        id=uuid4(),
        result_id="710001",
        organization_id=org.id,
        status="queued",
        transcription="existing transcript",
    )
    db_session.add(eval_result)
    db_session.commit()

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(task_module, "_recover_missing_audio_for_result", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        task_module,
        "_load_related_entities",
        lambda *_args, **_kwargs: (types.SimpleNamespace(custom_prompt="custom"), None, None, None),
    )
    monkeypatch.setattr(task_module, "_transcribe_audio", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(task_module, "_categorize_metrics", lambda *_args, **_kwargs: ([], [], {}))
    monkeypatch.setattr(
        task_module,
        "_generate_call_analysis",
        lambda *_args, **_kwargs: {
            "call_summary": "summary",
            "user_sentiment": "Neutral",
            "call_successful": True,
        },
    )

    result = task_module.process_evaluator_result_task.run(str(eval_result.id))

    verify_session = sessionmaker(bind=test_engine)()
    persisted = verify_session.query(EvaluatorResult).filter(EvaluatorResult.id == eval_result.id).one()
    assert result["status"] == "completed"
    assert result["transcription"] == "existing transcript"
    assert persisted.status == "completed"
    assert persisted.call_data["call_analysis"]["call_successful"] is True
    assert persisted.call_data["generated"]["call_analysis"]["user_sentiment"] == "Neutral"
    verify_session.close()


def test_process_evaluator_result_handles_audio_and_llm_failures_with_fallback_scores(
    db_session, test_engine, monkeypatch
):
    from app.workers.tasks import process_evaluator_result as task_module

    org = _seed_org(db_session)
    eval_result = EvaluatorResult(
        id=uuid4(),
        result_id="710002",
        organization_id=org.id,
        status="queued",
        audio_s3_key="audio/key.wav",
    )
    db_session.add(eval_result)
    db_session.add(
        Metric(
            id=uuid4(),
            organization_id=org.id,
            name="MOS Score",
            metric_type="rating",
            trigger="always",
            enabled=True,
            is_default=False,
        )
    )
    db_session.add(
        Metric(
            id=uuid4(),
            organization_id=org.id,
            name="Professionalism",
            metric_type="rating",
            trigger="always",
            enabled=True,
            is_default=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(task_module, "_recover_missing_audio_for_result", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        task_module,
        "_load_related_entities",
        lambda *_args, **_kwargs: (types.SimpleNamespace(custom_prompt="custom"), None, None, None),
    )
    monkeypatch.setattr(
        task_module,
        "_transcribe_audio",
        lambda *_args, **_kwargs: ("fresh transcript", [{"speaker": "S1", "text": "hi"}], 0.2),
    )
    monkeypatch.setattr(task_module, "evaluate_audio_metrics", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audio fail")))
    monkeypatch.setattr(
        task_module,
        "handle_audio_evaluation_error",
        lambda metrics, _err: {str(m.id): {"value": None, "metric_name": m.name, "error": "audio_failed"} for m in metrics},
    )
    monkeypatch.setattr(task_module, "evaluate_with_llm", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("llm fail")))
    monkeypatch.setattr(
        task_module,
        "handle_llm_evaluation_error",
        lambda metrics, _err: {str(m.id): {"value": None, "metric_name": m.name, "error": "llm_failed"} for m in metrics},
    )
    monkeypatch.setattr(task_module, "_generate_call_analysis", lambda *_args, **_kwargs: None)

    result = task_module.process_evaluator_result_task.run(str(eval_result.id))

    verify_session = sessionmaker(bind=test_engine)()
    persisted = verify_session.query(EvaluatorResult).filter(EvaluatorResult.id == eval_result.id).one()
    assert result["status"] == "completed"
    assert persisted.status == "completed"
    assert isinstance(persisted.metric_scores, dict)
    assert len(persisted.metric_scores) == 2
    errors = {v.get("error") for v in persisted.metric_scores.values()}
    assert errors == {"audio_failed", "llm_failed"}
    verify_session.close()


def test_process_evaluator_result_categorizes_audio_metrics_as_skipped_without_audio(db_session):
    from app.workers.tasks import process_evaluator_result as task_module

    audio_metric = types.SimpleNamespace(id=uuid4(), name="MOS Score", metric_type="rating")
    llm_metric = types.SimpleNamespace(id=uuid4(), name="Professionalism", metric_type="rating")

    llm_metrics, audio_metrics, skipped_scores = task_module._categorize_metrics(
        [audio_metric, llm_metric], has_audio=False
    )

    assert len(llm_metrics) == 1 and llm_metrics[0].name == "Professionalism"
    assert audio_metrics == []
    assert skipped_scores[str(audio_metric.id)]["skipped"] == "audio_required"


def test_run_evaluator_returns_error_when_evaluator_missing(db_session, monkeypatch):
    from app.workers.tasks import run_evaluator as task_module

    org = _seed_org(db_session)
    eval_result = EvaluatorResult(
        id=uuid4(),
        result_id="901234",
        organization_id=org.id,
        status="queued",
    )
    db_session.add(eval_result)
    db_session.commit()

    fake_bridge_module = types.ModuleType("app.services.testing.test_agent_bridge_service")
    fake_bridge_module.test_agent_bridge_service = object()
    monkeypatch.setitem(sys.modules, "app.services.testing.test_agent_bridge_service", fake_bridge_module)
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    result = task_module.run_evaluator_task.run(str(uuid4()), str(eval_result.id))

    assert result == {"error": "Evaluator not found"}


def test_run_prompt_optimization_marks_failed_without_training_data(db_session, test_engine, monkeypatch):
    from app.workers.tasks import run_prompt_optimization as task_module

    # API test stubs can overwrite this symbol in-memory; reload to restore real task.
    task_module = importlib.reload(task_module)

    org = _seed_org(db_session)
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        name="Optimizer Agent",
        language="en",
        description="Optimize my prompt",
        call_type="outbound",
        call_medium="phone_call",
    )
    db_session.add(agent)
    db_session.flush()

    run = PromptOptimizationRun(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        seed_prompt="seed prompt",
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(task_module.logger, "error", lambda *_args, **_kwargs: None)
    task_module.run_prompt_optimization_task.run(run.id)
    verify_session = sessionmaker(bind=test_engine)()
    persisted_run = verify_session.query(PromptOptimizationRun).filter(PromptOptimizationRun.id == run.id).first()

    assert persisted_run.status == "failed"
    assert "No completed evaluator results" in persisted_run.error_message
    verify_session.close()


def test_run_prompt_optimization_persists_best_prompt_and_candidates_on_success(db_session, test_engine, monkeypatch):
    from app.workers.tasks import run_prompt_optimization as task_module

    # API test stubs can overwrite this symbol in-memory; reload to restore real task.
    task_module = importlib.reload(task_module)

    org = _seed_org(db_session)
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        name="Optimizer Agent",
        language="en",
        description="Optimize my prompt",
        call_type="outbound",
        call_medium="phone_call",
    )
    db_session.add(agent)
    db_session.flush()

    db_session.add(
        EvaluatorResult(
            id=uuid4(),
            result_id="345678",
            organization_id=org.id,
            agent_id=agent.id,
            transcription="sample transcript",
            status="completed",
        )
    )
    db_session.add(
        Metric(
            id=uuid4(),
            organization_id=org.id,
            name="Professionalism",
            metric_type="rating",
            trigger="always",
            enabled=True,
            is_default=False,
        )
    )
    run = PromptOptimizationRun(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        seed_prompt="seed prompt",
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    fake_opt_module = types.ModuleType("app.services.optimization")
    fake_opt_module.run_optimization = lambda **_kwargs: {
        "best_candidate": "improved prompt",
        "best_score": 0.92,
        "metric_history": [{"iter": 1, "score": 0.92}],
        "total_metric_calls": 3,
        "candidates": [{"prompt_text": "candidate prompt", "score": 0.92}],
    }
    monkeypatch.setitem(sys.modules, "app.services.optimization", fake_opt_module)
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    monkeypatch.setattr(task_module.logger, "error", lambda *_args, **_kwargs: None)
    task_module.run_prompt_optimization_task.run(run.id)
    verify_session = sessionmaker(bind=test_engine)()
    persisted_run = verify_session.query(PromptOptimizationRun).filter(PromptOptimizationRun.id == run.id).first()

    assert persisted_run.status == "completed"
    assert persisted_run.best_prompt == "improved prompt"
    assert persisted_run.best_score == 0.92
    verify_session.close()


def test_generate_tts_comparison_dispatches_evaluation_after_sample_generation(db_session, monkeypatch):
    from app.workers.tasks import tts_comparison as task_module

    org = _seed_org(db_session)
    comp = TTSComparison(
        id=uuid4(),
        organization_id=org.id,
        simulation_id="123456",
        status="pending",
        provider_a="openai",
        model_a="gpt-4o-mini-tts",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        sample_texts=["hello world"],
        num_runs=1,
    )
    db_session.add(comp)
    db_session.flush()
    sample = TTSSample(
        id=uuid4(),
        comparison_id=comp.id,
        organization_id=org.id,
        provider="openai",
        model="gpt-4o-mini-tts",
        voice_id="alloy",
        voice_name="Alloy",
        side="A",
        sample_index=0,
        run_index=0,
        text="hello world",
        status="pending",
    )
    db_session.add(sample)
    db_session.commit()

    fake_tts_module = types.ModuleType("app.services.ai.tts_service")

    class _TTSService:
        @staticmethod
        def synthesize_timed(**_kwargs):
            return (b"fake-audio-bytes", 120.0, 35.0)

    fake_tts_module.tts_service = _TTSService()
    fake_tts_module.get_audio_file_extension = lambda *_args, **_kwargs: "mp3"
    monkeypatch.setitem(sys.modules, "app.services.ai.tts_service", fake_tts_module)

    fake_s3_module = types.ModuleType("app.services.storage.s3_service")

    class _S3Service:
        prefix = ""

        @staticmethod
        def upload_file_by_key(file_content, key):
            assert file_content == b"fake-audio-bytes"
            return key

    fake_s3_module.s3_service = _S3Service()
    monkeypatch.setitem(sys.modules, "app.services.storage.s3_service", fake_s3_module)

    called = {"value": False}
    monkeypatch.setattr(
        task_module.evaluate_tts_comparison_task,
        "delay",
        lambda _comparison_id: called.__setitem__("value", True),
    )
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    result = task_module.generate_tts_comparison_task.run(str(comp.id))

    assert result == {"generated": 1, "failed": 0}
    assert called["value"] is True


def test_evaluate_tts_comparison_returns_zero_when_no_completed_samples(db_session, monkeypatch):
    from app.workers.tasks import tts_comparison as task_module

    org = _seed_org(db_session)
    comp = TTSComparison(
        id=uuid4(),
        organization_id=org.id,
        simulation_id="654321",
        status="evaluating",
        provider_a="openai",
        model_a="gpt-4o-mini-tts",
        voices_a=[{"id": "alloy", "name": "Alloy"}],
        sample_texts=["hello world"],
        num_runs=1,
    )
    db_session.add(comp)
    db_session.commit()

    fake_s3_module = types.ModuleType("app.services.storage.s3_service")
    fake_s3_module.s3_service = object()
    monkeypatch.setitem(sys.modules, "app.services.storage.s3_service", fake_s3_module)

    fake_qvs_module = types.ModuleType("app.services.audio.qualitative_voice_service")
    fake_qvs_module.qualitative_voice_service = object()
    monkeypatch.setitem(sys.modules, "app.services.audio.qualitative_voice_service", fake_qvs_module)

    fake_tx_module = types.ModuleType("app.services.ai.transcription_service")
    fake_tx_module.transcription_service = object()
    monkeypatch.setitem(sys.modules, "app.services.ai.transcription_service", fake_tx_module)

    fake_vp_module = types.ModuleType("app.api.v1.routes.voice_playground")
    fake_vp_module._recompute_summary = lambda _comp, _db: None
    monkeypatch.setitem(sys.modules, "app.api.v1.routes.voice_playground", fake_vp_module)
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db_session)

    result = task_module.evaluate_tts_comparison_task.run(str(comp.id))

    assert result == {"evaluated": 0}
