"""Studio run LLM settings must reach build_llm_config_buckets."""

from types import SimpleNamespace
from uuid import uuid4

from app.workers.tasks.evaluate_studio_run_item import (
    studio_evaluator_from_llm_config,
    studio_run_llm_bucket_kwargs,
)


def test_studio_run_llm_bucket_kwargs_uses_run_fields():
    cred_id = uuid4()
    run = SimpleNamespace(
        metric_llm_overrides={"m1": {"llm_model": "gpt-4o-mini"}},
        llm_provider=" openai ",
        llm_model=" gpt-4o ",
        llm_config={"temperature": 0.1},
        llm_credential_id=cred_id,
    )
    kwargs = studio_run_llm_bucket_kwargs(run)  # type: ignore[arg-type]
    assert kwargs["run_provider"] == "openai"
    assert kwargs["run_model"] == "gpt-4o"
    assert kwargs["run_llm_config"] == {"temperature": 0.1}
    assert kwargs["run_credential_id"] == str(cred_id)
    assert kwargs["overrides"] == {"m1": {"llm_model": "gpt-4o-mini"}}


def test_studio_evaluator_from_llm_config_uses_bucket_provider_and_model():
    cred_id = uuid4()
    config = ("google", "gemini-2.5-flash", '{"temperature": 0.2}', str(cred_id))
    evaluator = studio_evaluator_from_llm_config(config)
    assert evaluator is not None
    assert evaluator.llm_provider == "google"
    assert evaluator.llm_model == "gemini-2.5-flash"
    assert evaluator.llm_config == {"temperature": 0.2}
    assert evaluator.llm_credential_id == str(cred_id)


def test_studio_evaluator_from_llm_config_returns_none_without_provider():
    assert studio_evaluator_from_llm_config((None, "gpt-4o", None, None)) is None


def test_studio_run_llm_bucket_kwargs_empty_when_unset():
    run = SimpleNamespace(
        metric_llm_overrides=None,
        llm_provider=None,
        llm_model=None,
        llm_config=None,
        llm_credential_id=None,
    )
    kwargs = studio_run_llm_bucket_kwargs(run)  # type: ignore[arg-type]
    assert kwargs["run_provider"] is None
    assert kwargs["run_model"] is None
    assert kwargs["run_llm_config"] is None
    assert kwargs["run_credential_id"] is None
    assert kwargs["overrides"] == {}
