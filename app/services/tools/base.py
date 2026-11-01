"""Provider-agnostic tool types shared by every tool source (knowledge bases, MCP, HTTP, ...)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol

RESULT_PREVIEW_CHARS = 2000

TOOL_STATUS_OK = "ok"
TOOL_STATUS_ERROR = "error"
TOOL_STATUS_MOCKED = "mocked"

SIDE_EFFECT_READ = "read"
SIDE_EFFECT_WRITE = "write"

# How a provider's tools behave inside simulations.
SIM_MODE_LIVE = "live"
SIM_MODE_MOCK_WRITES = "mock_writes"
SIM_MODE_MOCK_ALL = "mock_all"
SIM_MODES = (SIM_MODE_LIVE, SIM_MODE_MOCK_WRITES, SIM_MODE_MOCK_ALL)

_WRITE_VERBS = re.compile(
    r"(^|_)(add|append|archive|assign|create|delete|drop|insert|invite|move|post|publish|"
    r"put|remove|reply|send|set|share|update|upload|upsert|write|patch|react|comment)(_|$)"
)


def classify_side_effect(
    name: str,
    *,
    read_only_hint: Optional[bool] = None,
    destructive_hint: Optional[bool] = None,
) -> str:
    """Read or write: trust explicit MCP annotations, else guess from the tool name's verbs."""
    if read_only_hint is True:
        return SIDE_EFFECT_READ
    if destructive_hint is True or read_only_hint is False:
        return SIDE_EFFECT_WRITE
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|[-.\s]+", "_", name).lower()
    return SIDE_EFFECT_WRITE if _WRITE_VERBS.search(words) else SIDE_EFFECT_READ


@dataclass(frozen=True)
class ToolSpec:
    """One callable tool as exposed to the LLM (OpenAI function-tool shape)."""

    name: str
    description: str
    parameters: dict[str, Any]
    provider: str
    side_effect: str = SIDE_EFFECT_READ

    def openai_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    # Provider-specific facts worth keeping on the call record (e.g. KB hit_count).
    extra: dict[str, Any] = field(default_factory=dict)


class ToolProvider(Protocol):
    """A tool source. Optional attributes: ``simulation_mode`` (default mock_writes)
    and ``close()`` for providers holding sessions or connections."""

    name: str

    def list_tools(self) -> list[ToolSpec]: ...

    def call(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult: ...


@dataclass
class ToolCallRecord:
    """One executed (or mocked) tool call, stored in ``call_data.tool_calls``."""

    call_id: Optional[str]
    tool: str
    provider: str
    arguments: dict[str, Any]
    status: str
    result_preview: str
    latency_ms: int
    side: str = "production"
    turn_index: Optional[int] = None
    error: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra") or {}
        return {**data, **extra}


def preview(text: str, limit: int = RESULT_PREVIEW_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"
