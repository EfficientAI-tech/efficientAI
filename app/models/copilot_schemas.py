"""Request/response schemas for the copilot API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CopilotReason(BaseModel):
    code: str
    message: str


class CopilotStatusResponse(BaseModel):
    ready: bool
    reasons: List[CopilotReason] = []
    warnings: List[CopilotReason] = []
    provider: Optional[str] = None
    model: Optional[str] = None
    credential_id: Optional[UUID] = None
    credential_name: Optional[str] = None
    tool_calling: Optional[str] = None
    tools: List[str] = []


class PageContext(BaseModel):
    """Where the user is in the app. Client-supplied: used as a hint, never trusted for access."""

    route: Optional[str] = Field(None, max_length=300)
    entity_type: Optional[str] = Field(None, max_length=64)
    entity_id: Optional[str] = Field(None, max_length=64)
    title: Optional[str] = Field(None, max_length=200)


class CopilotSessionCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)


class CopilotSessionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    status: Optional[Literal["active", "archived"]] = None


class CopilotSessionResponse(BaseModel):
    id: UUID
    title: Optional[str]
    status: str
    message_count: int
    last_message_at: Optional[datetime]
    created_at: datetime
    draft: Optional[dict[str, Any]] = None


class CopilotSessionListResponse(BaseModel):
    items: List[CopilotSessionResponse]
    next_cursor: Optional[str] = None


class CopilotToolCallView(BaseModel):
    id: str
    name: str
    status: str
    latency_ms: Optional[int] = None
    ui: Optional[dict[str, Any]] = None


class CopilotMessageResponse(BaseModel):
    id: UUID
    seq: int
    role: str
    content: str
    status: str
    error: Optional[str] = None
    tool_calls: List[CopilotToolCallView] = []
    created_at: datetime
    completed_at: Optional[datetime] = None


class CopilotMessageListResponse(BaseModel):
    items: List[CopilotMessageResponse]
    has_more: bool


class CopilotMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    client_message_id: Optional[UUID] = Field(
        None, description="Client-generated id; resending the same id never runs the turn twice."
    )
    page_context: Optional[PageContext] = None
    timezone: Optional[str] = Field(None, max_length=64, description="IANA zone, e.g. Asia/Kolkata.")

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is empty")
        return value


class CopilotActionConfirm(BaseModel):
    payload: Optional[dict[str, Any]] = Field(
        None, description="The proposal as edited by the user; omit to apply it unchanged."
    )
