"""Unit tests for enum contract stability."""

import enum

from app.models import enums


def _all_enum_types():
    for _, obj in vars(enums).items():
        if isinstance(obj, type) and issubclass(obj, enum.Enum):
            yield obj


def test_enum_values_are_unique_within_each_enum():
    for enum_type in _all_enum_types():
        values = [member.value for member in enum_type]
        assert len(values) == len(set(values)), f"Duplicate enum values found in {enum_type.__name__}"


def test_critical_enum_values_are_stable():
    assert enums.EvaluationType.ASR.value == "asr"
    assert enums.EvaluationStatus.COMPLETED.value == "completed"
    assert enums.ModelProvider.OPENAI.value == "openai"
    assert enums.VoiceBundleType.STT_LLM_TTS.value == "stt_llm_tts"
    assert enums.PromptOptimizationStatus.RUNNING.value == "running"
