from app.services.testing.evaluator_run_errors import evaluator_error_is_retryable
from app.services.testing.evaluator_simulation_errors import (
    ProductionChatLegError,
    TestAgentLlmLegError,
)


def test_production_chat_leg_not_retryable():
    assert not evaluator_error_is_retryable(
        ProductionChatLegError("smallest_atoms_chat", "timed out")
    )


def test_test_agent_llm_not_retryable():
    assert not evaluator_error_is_retryable(TestAgentLlmLegError("empty response"))
