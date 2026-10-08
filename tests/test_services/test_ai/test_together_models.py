from app.services.ai.together_models import (
    TOGETHER_SERVERLESS_DEFAULT_MODEL,
    normalize_together_model_name,
)


def test_normalize_retired_together_8b_turbo():
    assert (
        normalize_together_model_name("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo")
        == TOGETHER_SERVERLESS_DEFAULT_MODEL
    )


def test_normalize_leaves_other_models():
    assert normalize_together_model_name("meta-llama/Llama-3.3-70B-Instruct-Turbo") == (
        "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    )
