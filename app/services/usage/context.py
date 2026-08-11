"""Usage attribution context (org, workspace, product section, resource)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional
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
    if (
        upgraded_workspace == current.workspace_id
        and upgraded_section == current.product_section
        and upgraded_resource_id == current.resource_id
        and upgraded_resource_type == current.resource_type
    ):
        return None

    return set_usage_context(
        LLMUsageContext(
            organization_id=current.organization_id,
            workspace_id=upgraded_workspace,
            product_section=upgraded_section,
            resource_id=upgraded_resource_id,
            resource_type=upgraded_resource_type,
        )
    )
