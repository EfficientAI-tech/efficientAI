"""Ensure TypeSafe LLM models are present in the model catalog."""

from app.models.database import ModelProvider
from app.services.ai.model_config_service import model_config_service


def test_typesafe_llm_models_in_catalog():
    llm_models = model_config_service.get_models_by_type(ModelProvider.TYPESAFE, "llm")
    assert "jev-1.13.0" in llm_models
