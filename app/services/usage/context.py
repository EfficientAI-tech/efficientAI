"""Usage attribution context (org, workspace, product section, resource)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional, Any
from uuid import UUID


class LLMUsageProductSection(str, Enum):
    CALL_IMPORT_EVALUATIONS = "call_import_evaluations"
    CALL_IMPORTS = "call_imports"
    PLAYGROUND = "playground"
    VOICE_PLAYGROUND = "voice_playground"
    EVALUATORS = "evaluators"
    METRICS = "metrics"
    CHAT = "chat"
    JUDGE_ALIGNMENT = "judge_alignment"
    PROMPT_OPTIMIZATION = "prompt_optimization"
    PERSONAS = "personas"
    AGENTS = "agents"
    PROMPT_PARTIALS = "prompt_partials"
    CONVERSATION_EVALUATIONS = "conversation_evaluations"
    TELEPHONY = "telephony"
    TEST_AGENT = "test_agent"
    OTHER = "other"


@dataclass(frozen=True)
class LLMUsageContext:
    organization_id: UUID
    workspace_id: Optional[UUID] = None
    product_section: LLMUsageProductSection = LLMUsageProductSection.OTHER
    resource_id: Optional[UUID] = None
    resource_type: Optional[str] = None
    extra: Optional[dict[str, str]] = None


_usage_context_var: ContextVar[Optional[LLMUsageContext]] = ContextVar(
    "llm_usage_context", default=None
)
_usage_workspace_hint_var: ContextVar[Optional[UUID]] = ContextVar(
    "llm_usage_workspace_hint", default=None
)
_usage_section_hint_var: ContextVar[LLMUsageProductSection] = ContextVar(
    "llm_usage_section_hint", default=LLMUsageProductSection.OTHER
)

# Path fragments under /api/v1 → product section (longest match wins).
_PATH_SECTION_RULES: tuple[tuple[str, LLMUsageProductSection], ...] = (
    ("call-import-evaluations", LLMUsageProductSection.CALL_IMPORT_EVALUATIONS),
    ("call-imports", LLMUsageProductSection.CALL_IMPORTS),
    ("voice-playground", LLMUsageProductSection.VOICE_PLAYGROUND),
    ("playground", LLMUsageProductSection.PLAYGROUND),
    ("evaluators", LLMUsageProductSection.EVALUATORS),
    ("metrics", LLMUsageProductSection.METRICS),
    ("chat", LLMUsageProductSection.CHAT),
    ("judge-alignment", LLMUsageProductSection.JUDGE_ALIGNMENT),
    ("prompt-optimization", LLMUsageProductSection.PROMPT_OPTIMIZATION),
    ("personas", LLMUsageProductSection.PERSONAS),
    ("agents", LLMUsageProductSection.AGENTS),
    ("prompt-partials", LLMUsageProductSection.PROMPT_PARTIALS),
    ("conversation-evaluations", LLMUsageProductSection.CONVERSATION_EVALUATIONS),
    ("telephony", LLMUsageProductSection.TELEPHONY),
    ("test-agent", LLMUsageProductSection.TEST_AGENT),
)


def get_usage_context() -> Optional[LLMUsageContext]:
    return _usage_context_var.get()


def set_usage_context(ctx: Optional[LLMUsageContext]) -> Token:
    return _usage_context_var.set(ctx)


def reset_usage_context(token: Token) -> None:
    _usage_context_var.reset(token)


def set_usage_hints(
    *,
    workspace_id: Optional[UUID] = None,
    product_section: Optional[LLMUsageProductSection] = None,
) -> tuple[Token, Token]:
    ws_token = _usage_workspace_hint_var.set(workspace_id)
    section = product_section or LLMUsageProductSection.OTHER
    section_token = _usage_section_hint_var.set(section)
    return ws_token, section_token


def reset_usage_hints(tokens: tuple[Token, Token]) -> None:
    _usage_workspace_hint_var.reset(tokens[0])
    _usage_section_hint_var.reset(tokens[1])


def get_usage_workspace_hint() -> Optional[UUID]:
    return _usage_workspace_hint_var.get()


def get_usage_section_hint() -> LLMUsageProductSection:
    return _usage_section_hint_var.get()


@contextmanager
def llm_usage_context(ctx: LLMUsageContext) -> Iterator[None]:
    token = set_usage_context(ctx)
    try:
        yield
    finally:
        reset_usage_context(token)


def infer_product_section_from_path(path: str) -> LLMUsageProductSection:
    normalized = (path or "").lower()
    for fragment, section in _PATH_SECTION_RULES:
        if f"/{fragment}" in normalized or normalized.endswith(fragment):
            return section
    return LLMUsageProductSection.OTHER


def ensure_usage_context(
    organization_id: UUID,
    *,
    workspace_id: Optional[UUID] = None,
    product_section: LLMUsageProductSection = LLMUsageProductSection.OTHER,
    resource_id: Optional[UUID] = None,
    resource_type: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> Token | None:
    """Set or enrich usage context. Returns token to reset, or None if unchanged."""
    resolved_workspace = workspace_id or get_usage_workspace_hint()
    resolved_section = product_section
    if resolved_section == LLMUsageProductSection.OTHER:
        hint = get_usage_section_hint()
        if hint != LLMUsageProductSection.OTHER:
            resolved_section = hint

    current = get_usage_context()
    if current is None:
        return set_usage_context(
            LLMUsageContext(
                organization_id=organization_id,
                workspace_id=resolved_workspace,
                product_section=resolved_section,
                resource_id=resource_id,
                resource_type=resource_type,
                extra=extra,
            )
        )

    upgraded_workspace = current.workspace_id or resolved_workspace
    upgraded_section = (
        resolved_section
        if current.product_section == LLMUsageProductSection.OTHER
        and resolved_section != LLMUsageProductSection.OTHER
        else current.product_section
    )
    upgraded_resource_id = current.resource_id or resource_id
    upgraded_resource_type = current.resource_type or resource_type
    upgraded_extra = {**(current.extra or {}), **(extra or {})} or None
    if (
        upgraded_workspace == current.workspace_id
        and upgraded_section == current.product_section
        and upgraded_resource_id == current.resource_id
        and upgraded_resource_type == current.resource_type
        and upgraded_extra == current.extra
    ):
        return None

    return set_usage_context(
        LLMUsageContext(
            organization_id=current.organization_id,
            workspace_id=upgraded_workspace,
            product_section=upgraded_section,
            resource_id=upgraded_resource_id,
            resource_type=upgraded_resource_type,
            extra=upgraded_extra,
        )
    )


def usage_context_for_agent(
    agent: Any,
    *,
    workspace_id: Optional[UUID] = None,
    extra: Optional[dict[str, str]] = None,
) -> LLMUsageContext:
    """Usage context for agent-scoped LLM work (simulations, setup, summaries)."""
    merged: dict[str, str] = dict(extra or {})
    merged.setdefault("agent_id", str(agent.id))
    short = getattr(agent, "agent_id", None)
    if short:
        merged.setdefault("agent_short_id", str(short))
    return LLMUsageContext(
        organization_id=agent.organization_id,
        workspace_id=workspace_id or agent.workspace_id,
        product_section=LLMUsageProductSection.AGENTS,
        resource_id=agent.id,
        resource_type="agent",
        extra=merged,
    )


def usage_context_for_evaluator_result(result: Any) -> LLMUsageContext:
    """Usage context for post-run processing of synthetic evaluator results."""
    extra: dict[str, str] = {
        "evaluator_result_id": str(result.id),
        "synthetic_testing": "pre_prod",
    }
    if getattr(result, "result_id", None):
        extra["result_short_id"] = str(result.result_id)
    if result.agent_id:
        extra["agent_id"] = str(result.agent_id)
    if result.evaluator_id:
        extra["evaluator_id"] = str(result.evaluator_id)
    if getattr(result, "persona_id", None):
        extra["persona_id"] = str(result.persona_id)
    if getattr(result, "scenario_id", None):
        extra["scenario_id"] = str(result.scenario_id)
    platform = getattr(result, "provider_platform", None)
    if platform:
        extra["provider_platform"] = str(platform).lower()

    resource_id = result.evaluator_id or result.id
    resource_type = "evaluator" if result.evaluator_id else "evaluator_result"
    section = (
        LLMUsageProductSection.EVALUATORS
        if result.evaluator_id
        else LLMUsageProductSection.PLAYGROUND
    )
    return LLMUsageContext(
        organization_id=result.organization_id,
        workspace_id=result.workspace_id,
        product_section=section,
        resource_id=resource_id,
        resource_type=resource_type,
        extra=extra,
    )


def usage_context_for_metric_studio_run(
    run: Any,
    *,
    source_kind: Optional[str] = None,
    source_ref: Optional[str] = None,
    result_row_id: Optional[UUID] = None,
) -> LLMUsageContext:
    """Usage context for Metrics Studio batch scoring."""
    extra: dict[str, str] = {"metric_studio_run_id": str(run.id)}
    if source_kind:
        extra["source_kind"] = source_kind
    if source_ref:
        extra["source_ref"] = source_ref
    if result_row_id:
        extra["metric_studio_result_id"] = str(result_row_id)
    if source_kind == "evaluator_result":
        extra["synthetic_testing"] = "pre_prod"
    return LLMUsageContext(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        product_section=LLMUsageProductSection.METRICS,
        resource_id=run.id,
        resource_type="metric_studio_run",
        extra=extra,
    )


def usage_context_for_persona_generation(
    agent: Any,
    *,
    workspace_id: Optional[UUID] = None,
) -> LLMUsageContext:
    """Usage context for LLM-generated persona caller prompts."""
    return LLMUsageContext(
        organization_id=agent.organization_id,
        workspace_id=workspace_id or agent.workspace_id,
        product_section=LLMUsageProductSection.PERSONAS,
        resource_id=agent.id,
        resource_type="agent",
        extra={
            "agent_id": str(agent.id),
            "synthetic_testing": "pre_prod",
        },
    )


def usage_context_for_prompt_optimization_run(run: Any) -> LLMUsageContext:
    """Usage context for a GEPA prompt optimization run."""
    cfg = run.config if isinstance(run.config, dict) else {}
    is_judge = cfg.get("source") == "judge_alignment"
    extra: dict[str, str] = {
        "optimization_run_id": str(run.id),
        "agent_id": str(run.agent_id),
    }
    if run.evaluator_id:
        extra["evaluator_id"] = str(run.evaluator_id)
    if is_judge:
        extra["source"] = "judge_alignment"
        if cfg.get("judge_dataset_id"):
            extra["judge_dataset_id"] = str(cfg["judge_dataset_id"])
    return LLMUsageContext(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        product_section=(
            LLMUsageProductSection.JUDGE_ALIGNMENT
            if is_judge
            else LLMUsageProductSection.PROMPT_OPTIMIZATION
        ),
        resource_id=run.agent_id,
        resource_type="agent",
        extra=extra,
    )


def usage_context_for_judge_run(run: Any) -> LLMUsageContext:
    """Usage context for a judge alignment scoring run."""
    return LLMUsageContext(
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        product_section=LLMUsageProductSection.JUDGE_ALIGNMENT,
        resource_id=run.evaluator_id,
        resource_type="evaluator",
        extra={
            "judge_run_id": str(run.id),
            "judge_dataset_id": str(run.dataset_id),
        },
    )


def usage_context_for_prompt_partial(partial: Any) -> LLMUsageContext:
    """Usage context for prompt partial / agent flowchart LLM work."""
    return LLMUsageContext(
        organization_id=partial.organization_id,
        workspace_id=partial.workspace_id,
        product_section=LLMUsageProductSection.PROMPT_PARTIALS,
        resource_id=partial.id,
        resource_type="prompt_partial",
        extra={"prompt_partial_id": str(partial.id)},
    )


def usage_context_for_playground_voice_call(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID],
    agent_id: Optional[UUID],
    provider_platform: Optional[str],
    call_short_id: Optional[str] = None,
) -> LLMUsageContext:
    """Usage context for live playground Voice AI Agent provider sessions."""
    extra: dict[str, str] = {"synthetic_testing": "pre_prod"}
    if agent_id:
        extra["agent_id"] = str(agent_id)
    if provider_platform:
        extra["provider_platform"] = str(provider_platform).lower()
    if call_short_id:
        extra["call_short_id"] = call_short_id
    return LLMUsageContext(
        organization_id=organization_id,
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.PLAYGROUND,
        resource_id=agent_id,
        resource_type="agent" if agent_id else None,
        extra=extra,
    )


def usage_context_for_test_agent_simulation(
    *,
    organization_id: UUID,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    evaluator_id: Optional[UUID] = None,
    persona_id: Optional[UUID] = None,
    scenario_id: Optional[UUID] = None,
    evaluator_result_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
    provider_platform: Optional[str] = None,
) -> LLMUsageContext:
    """Usage context for synthetic LLM-to-LLM simulation (caller / test-agent leg)."""
    extra: dict[str, str] = {"simulation": "llm_to_llm"}
    if agent_id:
        extra["agent_id"] = str(agent_id)
    if evaluator_id:
        extra["evaluator_id"] = str(evaluator_id)
    if persona_id:
        extra["persona_id"] = str(persona_id)
    if scenario_id:
        extra["scenario_id"] = str(scenario_id)
    if evaluator_result_id:
        extra["evaluator_result_id"] = str(evaluator_result_id)
    if conversation_id:
        extra["conversation_id"] = str(conversation_id)
    if provider_platform:
        extra["provider_platform"] = str(provider_platform)
    return LLMUsageContext(
        organization_id=organization_id,
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.TEST_AGENT,
        resource_id=agent_id,
        resource_type="agent" if agent_id else None,
        extra=extra,
    )
