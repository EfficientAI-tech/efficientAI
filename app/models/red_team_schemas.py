"""Pydantic schemas for red team runs (EFF-36)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AttackerKnowledgeItem(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    value: str = Field(..., min_length=1, max_length=500)


class RedTeamConnectionOverrides(BaseModel):
    extension: Optional[str] = Field(None, max_length=32)


class RedTeamRunCreate(BaseModel):
    agent_id: UUID
    intensity: str = "standard"
    name: Optional[str] = Field(None, max_length=200)
    # Custom intensity only: attempts per family (0-20); families at 0 are skipped.
    attack_quotas: Optional[Dict[str, int]] = None
    attacker_knowledge: List[AttackerKnowledgeItem] = Field(default_factory=list, max_length=20)
    connection_overrides: Optional[RedTeamConnectionOverrides] = None
    # Voice agents: persona whose voice the attacker uses (defaults to a matching persona).
    persona_id: Optional[UUID] = None
    attacker_llm_provider: Optional[str] = None
    attacker_llm_model: Optional[str] = None
    judge_llm_provider: Optional[str] = None
    judge_llm_model: Optional[str] = None
    # False (default) returns a preview and starts nothing; True starts the run.
    confirmed: bool = False

    @field_validator("intensity")
    @classmethod
    def _lower(cls, value: str) -> str:
        return (value or "").strip().lower()


class RedTeamRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: str
    agent_id: UUID
    name: Optional[str] = None
    intensity: str
    modality: str
    config: Dict[str, Any] = {}
    attacker_knowledge: Optional[List[Dict[str, Any]]] = None
    connection_overrides: Optional[Dict[str, Any]] = None
    persona_id: Optional[UUID] = None
    resolved_llms: Optional[Dict[str, Any]] = None
    catalog_version: str
    agent_profile: Optional[Dict[str, Any]] = None
    status: str
    verdict: Optional[str] = None
    report: Optional[Dict[str, Any]] = None
    max_attacks: int = 0
    completed_attacks: int = 0
    breached_attacks: int = 0
    error_message: Optional[str] = None
    cancel_requested: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None


class RedTeamAttackResponse(BaseModel):
    """Attack tree node, without the transcript."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_attack_id: Optional[UUID] = None
    kind: str
    level: int
    sequence: int
    family: Optional[str] = None
    technique_id: Optional[str] = None
    technique_name: Optional[str] = None
    owasp_category: Optional[str] = None
    harm_category: Optional[str] = None
    goal: Optional[str] = None
    strategy: Optional[str] = None
    status: str
    outcome: Optional[str] = None
    score: Optional[float] = None
    success_score: Optional[float] = None
    rationale: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class RedTeamAttackDetailResponse(RedTeamAttackResponse):
    judge: Optional[Dict[str, Any]] = None
    # [{"role": "attacker" | "agent", "text": str, "tool_calls"?: [...]}]
    transcript: List[Dict[str, Any]] = []
    # Voice: the evaluator result that holds the recording.
    evaluator_result_id: Optional[UUID] = None
    evaluator_result_ref: Optional[str] = None
    has_recording: bool = False
    redacted: bool = False


class RedTeamRunDetailResponse(RedTeamRunResponse):
    attacks: List[RedTeamAttackResponse] = []


class RedTeamLaunchResponse(BaseModel):
    needs_confirmation: bool
    modality: str
    config: Dict[str, Any]
    preview: Dict[str, Any]
    run: Optional[RedTeamRunResponse] = None


class RedTeamEntitlementsResponse(BaseModel):
    intensities: List[str]
    custom_allowed: bool
    max_family_quota: int
    presets: Dict[str, Dict[str, Any]]
    catalog: Dict[str, Any]
