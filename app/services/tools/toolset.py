"""Collect an agent's tools from every provider and execute calls by name."""

from __future__ import annotations

import json
import time
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.services.tools.base import (
    SIDE_EFFECT_WRITE,
    SIM_MODE_LIVE,
    SIM_MODE_MOCK_ALL,
    SIM_MODE_MOCK_WRITES,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_MOCKED,
    TOOL_STATUS_OK,
    ToolCallRecord,
    ToolProvider,
    ToolResult,
    ToolSpec,
    preview,
)

DEFAULT_WRITE_MOCK = {"ok": True, "simulated": True}


class Toolset:
    """Name → provider map that executes calls and records them.

    In a simulation each provider's ``simulation_mode`` decides what runs for real:
    ``live`` runs everything, ``mock_writes`` (default) fakes write tools and
    ``mock_all`` fakes every tool. ``mock_responses`` (tool name → response) comes
    from a scenario's ``expected_tool_calls[].mock_response`` and always wins.
    """

    def __init__(
        self,
        providers: list[ToolProvider],
        *,
        simulation: bool = True,
        mock_responses: Optional[dict[str, Any]] = None,
    ):
        self.providers = providers
        self.simulation = simulation
        self.mock_responses = dict(mock_responses or {})
        self._specs: dict[str, tuple[ToolSpec, ToolProvider]] = {}
        for provider in providers:
            try:
                specs = provider.list_tools()
            except Exception as exc:
                logger.warning("[Tools] {} has no usable tools: {}", provider.name, exc)
                continue
            for spec in specs:
                if spec.name in self._specs:
                    logger.warning("[Tools] Duplicate tool name {} ignored", spec.name)
                    continue
                self._specs[spec.name] = (spec, provider)

    def __bool__(self) -> bool:
        return bool(self._specs)

    @property
    def tool_names(self) -> list[str]:
        return list(self._specs)

    def definitions(self) -> list[dict[str, Any]]:
        return [spec.openai_definition() for spec, _ in self._specs.values()]

    def provider(self, name: str) -> Optional[ToolProvider]:
        return next((p for p in self.providers if p.name == name), None)

    def spec(self, name: str) -> Optional[ToolSpec]:
        entry = self._specs.get(name)
        return entry[0] if entry else None

    def _should_mock(self, spec: ToolSpec, provider: ToolProvider) -> bool:
        if spec.name in self.mock_responses:
            return True
        if not self.simulation:
            return False
        mode = getattr(provider, "simulation_mode", SIM_MODE_MOCK_WRITES)
        if mode == SIM_MODE_LIVE:
            return False
        return mode == SIM_MODE_MOCK_ALL or spec.side_effect == SIDE_EFFECT_WRITE

    def should_mock(self, name: str) -> bool:
        entry = self._specs.get(name)
        return entry is not None and self._should_mock(*entry)

    def close(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception as exc:
                logger.warning("[Tools] Closing {} failed: {}", provider.name, exc)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        call_id: Optional[str] = None,
        side: str = "production",
    ) -> tuple[ToolResult, ToolCallRecord]:
        started = time.monotonic()
        entry = self._specs.get(name)
        provider_name = entry[0].provider if entry else "unknown"
        status = TOOL_STATUS_OK
        if entry is None:
            result = ToolResult(f"Unknown tool: {name}", is_error=True)
        elif self._should_mock(*entry):
            mock = self.mock_responses.get(name, DEFAULT_WRITE_MOCK)
            content = mock if isinstance(mock, str) else json.dumps(mock)
            result = ToolResult(content)
            status = TOOL_STATUS_MOCKED
        else:
            try:
                result = entry[1].call(name, arguments)
            except Exception as exc:
                logger.warning("[Tools] {} failed: {}", name, exc)
                result = ToolResult(f"Tool error: {exc}", is_error=True)
        if result.is_error:
            status = TOOL_STATUS_ERROR
        record = ToolCallRecord(
            call_id=call_id,
            tool=name,
            provider=provider_name,
            arguments=arguments,
            status=status,
            result_preview=preview(result.content),
            latency_ms=round((time.monotonic() - started) * 1000),
            side=side,
            error=result.content if result.is_error else None,
            extra=result.extra,
        )
        return result, record


def build_agent_toolset(
    db: Session,
    *,
    agent: Any,
    organization_id: UUID,
    llm_model: Optional[str] = None,
    channel: str = "chat_tools",
    mock_responses: Optional[dict[str, Any]] = None,
) -> Toolset:
    """Every tool the production agent can call: its knowledge bases plus attached connections."""
    from app.services.knowledge_bases.retrieval import agent_has_ready_knowledge
    from app.services.tools.connections import agent_connection_providers
    from app.services.tools.providers.knowledge_base import KnowledgeBaseToolProvider

    providers: list[ToolProvider] = []
    workspace_id = getattr(agent, "workspace_id", None)
    if workspace_id and agent_has_ready_knowledge(db, agent_id=agent.id):
        providers.append(
            KnowledgeBaseToolProvider(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_id=agent.id,
                channel=channel,
                llm_model=llm_model,
            )
        )
    if workspace_id:
        providers.extend(agent_connection_providers(db, agent=agent))
    return Toolset(providers, mock_responses=mock_responses)


def scenario_mock_responses(scenario: Any) -> dict[str, Any]:
    """``tool → mock_response`` from a scenario's ``expected_tool_calls``."""
    mocks: dict[str, Any] = {}
    for expectation in getattr(scenario, "expected_tool_calls", None) or []:
        if (
            isinstance(expectation, dict)
            and expectation.get("tool")
            and ("mock_response" in expectation)
        ):
            mocks[str(expectation["tool"])] = expectation["mock_response"]
    return mocks
