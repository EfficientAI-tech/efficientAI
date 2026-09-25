"""Ensure Together LLM models are present in the model catalog."""

from app.models.database import ModelProvider
from app.services.ai.model_config_service import model_config_service


def test_together_llm_models_in_catalog():
    llm_models = model_config_service.get_models_by_type(ModelProvider.TOGETHER, "llm")
    assert "together/Tev1-4B-experimental" in llm_models
    assert "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo" in llm_models
