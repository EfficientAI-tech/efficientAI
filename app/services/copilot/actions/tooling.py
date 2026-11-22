"""Turn an action kind into a model-facing "propose_*" tool."""

from __future__ import annotations

from typing import Any, Callable, Optional, Type

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.copilot.actions import service
from app.services.copilot.actions.base import get_kind
from app.services.copilot.registry import (
    SIDE_EFFECT_PROPOSE,
    CopilotTool,
    ToolContext,
    ToolOutput,
    register,
)

# Builds the stored payload from the tool arguments, e.g. resolving an agent's
# name to its id, or loading current values so an edit shows a before/after.
Prepare = Callable[[ToolContext, Session, Any], dict[str, Any]]


def proposal_tool(
    *,
    name: str,
    kind: str,
    description: str,
    args_model: Optional[Type[BaseModel]] = None,
    prepare: Optional[Prepare] = None,
    group: str = "setup",
) -> CopilotTool:
    action_kind = get_kind(kind)
    if action_kind is None:
        raise ValueError(f"unknown action kind {kind}")

    def handler(ctx: ToolContext, db: Session, args: Any) -> ToolOutput:
        payload = prepare(ctx, db, args) if prepare else args.model_dump(mode="json")
        return service.propose(
            db,
            kind=kind,
            payload=payload,
            session_id=ctx.session_id,
            organization_id=ctx.organization_id,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user_id,
            message_id=ctx.message_id,
            capabilities=ctx.capabilities,
        )

    return register(CopilotTool(
        name=name,
        description=(
            f"{description} This only PROPOSES the change: the user reviews it on a card and "
            "must confirm before anything happens."
        ),
        args_model=args_model or action_kind.payload_model,
        handler=handler,
        capability=action_kind.capability,
        side_effect=SIDE_EFFECT_PROPOSE,
        group=group,
    ))
