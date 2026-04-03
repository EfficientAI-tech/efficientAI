"""Unit tests for audio metric evaluation helper."""

import sys
import types
from types import SimpleNamespace
from uuid import uuid4

from app.models.enums import MetricType
from app.workers.tasks.helpers.audio_evaluation import (
    evaluate_audio_metrics,
    handle_audio_evaluation_error,
)


def _install_fake_audio_dependencies(monkeypatch, audio_bytes: bytes | None):
    """Inject fake S3/audio service modules for isolated unit tests."""
    storage_module = types.ModuleType("app.services.storage.s3_service")
    storage_module.s3_service = SimpleNamespace(
        download_file_by_key=lambda _key: audio_bytes,
    )

    voice_quality_module = types.ModuleType("app.services.audio.voice_quality_service")
    voice_quality_module.calculate_audio_metrics = lambda *_args, **_kwargs: {
        "pitch variance": 0.55,
    }

    qualitative_service = SimpleNamespace(
        calculate_metrics=lambda *_args, **_kwargs: {"mos score": 4.4},
    )
    qualitative_module = types.ModuleType("app.services.audio.qualitative_voice_service")
    qualitative_module.qualitative_voice_service = qualitative_service

    monkeypatch.setitem(sys.modules, "app.services.storage.s3_service", storage_module)
    monkeypatch.setitem(sys.modules, "app.services.audio.voice_quality_service", voice_quality_module)
    monkeypatch.setitem(sys.modules, "app.services.audio.qualitative_voice_service", qualitative_module)


def test_evaluate_audio_metrics_returns_download_error(monkeypatch):
    _install_fake_audio_dependencies(monkeypatch, audio_bytes=None)
    metric = SimpleNamespace(id=uuid4(), name="pitch variance", metric_type=MetricType.NUMBER)

    result = evaluate_audio_metrics("missing-key", [metric], "result-1")

    metric_result = result[str(metric.id)]
    assert metric_result["value"] is None
    assert metric_result["error"] == "audio_download_failed"
    assert metric_result["type"] == "number"


def test_evaluate_audio_metrics_merges_parselmouth_and_qualitative(monkeypatch):
    _install_fake_audio_dependencies(monkeypatch, audio_bytes=b"fake-mp3-bytes")
    metrics = [
        SimpleNamespace(id=uuid4(), name="pitch variance", metric_type=MetricType.NUMBER),
        SimpleNamespace(id=uuid4(), name="mos score", metric_type=MetricType.RATING),
    ]

    result = evaluate_audio_metrics("audio-key", metrics, "result-2")

    assert result[str(metrics[0].id)]["value"] == 0.55
    assert result[str(metrics[0].id)]["type"] == "number"
    assert result[str(metrics[1].id)]["value"] == 4.4
    assert result[str(metrics[1].id)]["type"] == "rating"


def test_handle_audio_evaluation_error_applies_error_to_all_metrics():
    metrics = [
        SimpleNamespace(id=uuid4(), name="pitch variance", metric_type=MetricType.NUMBER),
        SimpleNamespace(id=uuid4(), name="mos score", metric_type=MetricType.RATING),
    ]

    result = handle_audio_evaluation_error(metrics, RuntimeError("boom"))

    assert result[str(metrics[0].id)]["error"] == "boom"
    assert result[str(metrics[1].id)]["error"] == "boom"
