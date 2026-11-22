"""Action kinds: the changes the copilot can make, each only after user confirmation.

A write tool never changes anything. It validates its arguments and records a
``CopilotAction`` in ``proposed`` state; the chat shows it as a card the user
can edit, confirm or reject. Confirming runs ``apply`` with the confirming
user's own workspace and capabilities (checked again at that moment).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Type, Union
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ActionContext:
    db: Session
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID
    capabilities: frozenset[str]


@dataclass
class EntityRef:
    type: str
    id: str
    name: Optional[str] = None
    link: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ActionResult:
    summary: str
    created: list[EntityRef] = field(default_factory=list)
    updated: list[EntityRef] = field(default_factory=list)
    undo_state: Optional[dict[str, Any]] = None  # None: this result can't be undone
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "created": [e.as_dict() for e in self.created],
            "updated": [e.as_dict() for e in self.updated],
            **({"data": self.data} if self.data else {}),
        }


Apply = Callable[[ActionContext, Any], Union[ActionResult, Awaitable[ActionResult]]]
Undo = Callable[[ActionContext, dict[str, Any]], Union[None, Awaitable[None]]]


@dataclass(frozen=True)
class ActionKind:
    kind: str
    title: str
    payload_model: Type[BaseModel]
    apply: Apply
    describe: Callable[[Any], str]
    capability: Optional[str] = None
    undo: Optional[Undo] = None
    # Costs money or starts heavy work (calls, LLM evaluation of many rows):
    # the card shows the estimate and the confirm button says so.
    costly: bool = False
    estimate: Optional[Callable[[Session, UUID, UUID, Any], dict[str, Any]]] = None
    editable: bool = True


_KINDS: dict[str, ActionKind] = {}
_loaded = False


def register_kind(kind: ActionKind) -> ActionKind:
    if kind.kind in _KINDS:
        raise ValueError(f"duplicate action kind {kind.kind}")
    _KINDS[kind.kind] = kind
    return kind


def _load() -> None:
    global _loaded
    if _loaded:
        return
    from app.services.copilot.actions import kinds  # noqa: F401  (registers)

    _loaded = True


def get_kind(kind: str) -> Optional[ActionKind]:
    _load()
    return _KINDS.get(kind)


def all_kinds() -> list[ActionKind]:
    _load()
    return list(_KINDS.values())


async def call_maybe_async(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Await async callables, call sync ones directly.

    Actions run on a worker thread with a private event loop (see the confirm
    route), so blocking here never stalls the server's loop.
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
