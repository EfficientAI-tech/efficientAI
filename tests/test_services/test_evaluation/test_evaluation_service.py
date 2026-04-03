"""Service-layer tests for evaluation processing."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.exceptions import AudioFileNotFoundError, EvaluationNotFoundError
from app.models.enums import EvaluationStatus
from app.services.evaluation.evaluation_service import EvaluationService

evaluation_module = importlib.import_module("app.services.evaluation.evaluation_service")


class _FakeQuery:
    def __init__(self, model, lookup):
        self.model = model
        self.lookup = lookup

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.lookup.get(self.model)


class _FakeDB:
    def __init__(self, lookup):
        self.lookup = lookup
        self.added = []
        self.commits = 0

    def query(self, model):
        return _FakeQuery(model, self.lookup)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


class _FakeEvaluationResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_process_evaluation_success(monkeypatch):
    evaluation_id = uuid4()
    audio_id = uuid4()
    evaluation = SimpleNamespace(
        id=evaluation_id,
        audio_id=audio_id,
        model_name="base",
        metrics_requested=["wer", "latency"],
        reference_text="hello world",
        status=EvaluationStatus.PENDING,
        started_at=None,
        completed_at=None,
        error_message=None,
    )
    audio_file = SimpleNamespace(id=audio_id, file_path="/tmp/a.wav", duration=2.0)
    db = _FakeDB({evaluation_module.Evaluation: evaluation, evaluation_module.AudioFile: audio_file})

    fake_model = SimpleNamespace(transcribe=lambda _path: {"text": "hello world"})
    monkeypatch.setattr(EvaluationService, "_load_model", lambda self, _name: fake_model)
    monkeypatch.setattr(
        evaluation_module.metrics_service,
        "calculate_metrics",
        lambda **_kwargs: {"wer": 0.0, "latency_s": 0.5, "latency_ms": 500.0},
    )
    monkeypatch.setattr(evaluation_module, "EvaluationResult", _FakeEvaluationResult)

    service = EvaluationService()
    result = service.process_evaluation(evaluation_id, db)

    assert result["status"] == "completed"
    assert result["transcript"] == "hello world"
    assert result["metrics"]["wer"] == 0.0
    assert evaluation.status == EvaluationStatus.COMPLETED
    assert len(db.added) == 1
    assert db.commits >= 2


def test_process_evaluation_raises_when_evaluation_missing():
    db = _FakeDB({evaluation_module.Evaluation: None})
    service = EvaluationService()

    with pytest.raises(EvaluationNotFoundError):
        service.process_evaluation(uuid4(), db)


def test_process_evaluation_raises_when_audio_missing():
    evaluation = SimpleNamespace(id=uuid4(), audio_id=uuid4())
    db = _FakeDB({evaluation_module.Evaluation: evaluation, evaluation_module.AudioFile: None})
    service = EvaluationService()

    with pytest.raises(AudioFileNotFoundError):
        service.process_evaluation(evaluation.id, db)


def test_process_evaluation_marks_failed_on_transcription_error(monkeypatch):
    evaluation_id = uuid4()
    audio_id = uuid4()
    evaluation = SimpleNamespace(
        id=evaluation_id,
        audio_id=audio_id,
        model_name="base",
        metrics_requested=["wer"],
        reference_text="hello",
        status=EvaluationStatus.PENDING,
        completed_at=None,
        error_message=None,
    )
    audio_file = SimpleNamespace(id=audio_id, file_path="/tmp/a.wav", duration=1.0)
    db = _FakeDB({evaluation_module.Evaluation: evaluation, evaluation_module.AudioFile: audio_file})

    fake_model = SimpleNamespace(transcribe=lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(EvaluationService, "_load_model", lambda self, _name: fake_model)

    service = EvaluationService()
    with pytest.raises(RuntimeError, match="boom"):
        service.process_evaluation(evaluation_id, db)

    assert evaluation.status == EvaluationStatus.FAILED
    assert evaluation.error_message == "boom"


def test_cancel_evaluation_only_cancels_pending():
    pending_eval = SimpleNamespace(id=uuid4(), status=EvaluationStatus.PENDING)
    db_pending = _FakeDB({evaluation_module.Evaluation: pending_eval})
    service = EvaluationService()
    assert service.cancel_evaluation(pending_eval.id, db_pending) is True
    assert pending_eval.status == EvaluationStatus.CANCELLED

    completed_eval = SimpleNamespace(id=uuid4(), status=EvaluationStatus.COMPLETED)
    db_completed = _FakeDB({evaluation_module.Evaluation: completed_eval})
    assert service.cancel_evaluation(completed_eval.id, db_completed) is False
