"""Errors surfaced during evaluator text/chat simulation (distinct legs)."""

from __future__ import annotations


class ProductionChatLegError(Exception):
    """Production agent path failed (platform WS, customer API, etc.)."""

    def __init__(self, leg: str, message: str) -> None:
        self.leg = leg
        super().__init__(message)


class TestAgentLlmLegError(Exception):
    """Test-agent LLM path failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
