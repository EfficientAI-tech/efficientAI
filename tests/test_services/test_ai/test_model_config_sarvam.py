"""Ensure Sarvam LLM models are present in the model catalog."""

from app.models.database import ModelProvider
from app.services.ai.model_config_service import model_config_service


def test_sarvam_llm_models_in_catalog():
    llm_models = model_config_service.get_models_by_type(ModelProvider.SARVAM, "llm")
    assert "sarvam-30b" in llm_models
    assert "sarvam-105b" in llm_models
