"""Ensure VoiceMaker TTS models are present in the model catalog."""

from app.models.database import ModelProvider
from app.services.ai.model_config_service import model_config_service


def test_voicemaker_tts_models_in_catalog():
    tts_models = model_config_service.get_models_by_type(ModelProvider.VOICEMAKER, "tts")
    assert "voicemaker-ai3" in tts_models
    assert "voicemaker-proplus" in tts_models
    assert "voicemaker-pro1" in tts_models
    assert "voicemaker-pro2" in tts_models
