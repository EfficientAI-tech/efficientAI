"""Resolve heterogeneous call sources into a common evaluation sample."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes.playground import extract_transcript_from_call_data
from app.models.database import (
    Agent,
    CallImport,
    CallImportRow,
    CallRecording,
    Evaluator,
    EvaluatorResult,
    Persona,
    Scenario,
)


def _basename_from_s3_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    parts = key.strip().split("/")
    name = parts[-1].strip() if parts else ""
    return name or None


@dataclass
class ResolvedCallSample:
    source_kind: str
    source_ref: str
    label: str
    transcript: Optional[str]
    diarised_transcript: Optional[str]
    audio_s3_key: Optional[str]
    call_data: Optional[dict]
    agent_id: Optional[UUID]
    metadata: Dict[str, Any] = field(default_factory=dict)


def _resolve_call_import_row(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    source_ref: str,
    display_label: Optional[str],
) -> ResolvedCallSample:
    try:
        row_id = UUID(source_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid call_import_row id.") from exc

    from app.db_sharding.sessions import is_sharding_enabled
    from app.db_sharding.row_ops import close_row_sessions, locate_call_import_row

    row_db = None
    extra_catalog = None
    close_located_sessions = False
    try:
        if is_sharding_enabled():
            try:
                row_db, located_catalog, row, _shard_id = locate_call_import_row(row_id)
                extra_catalog = located_catalog if located_catalog is not row_db else None
                close_located_sessions = True
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="Call import row not found.") from exc
        else:
            row = db.query(CallImportRow).filter(CallImportRow.id == row_id).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Call import row not found.")
            row_db = db

        if row.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Call import row not found.")

        call_import = (
            db.query(CallImport)
            .filter(
                CallImport.id == row.call_import_id,
                CallImport.organization_id == organization_id,
                CallImport.workspace_id == workspace_id,
            )
            .first()
        )
        if not call_import:
            raise HTTPException(status_code=404, detail="Call import row not found.")

        recording_filename = _basename_from_s3_key(row.recording_s3_key)
        label = (
            display_label
            or recording_filename
            or row.conversation_id
            or f"Import row {row.row_index}"
        )
        return ResolvedCallSample(
            source_kind="call_import_row",
            source_ref=str(row.id),
            label=label,
            transcript=(row.transcript or "").strip() or None,
            diarised_transcript=(row.diarised_transcript or "").strip() or None,
            audio_s3_key=(row.recording_s3_key or "").strip() or None,
            call_data=None,
            agent_id=None,
            metadata={
                "call_import_id": str(row.call_import_id),
                "call_import_name": getattr(call_import, "name", None),
                "original_filename": getattr(call_import, "original_filename", None),
                "recording_filename": recording_filename,
                "row_index": row.row_index,
                "conversation_id": row.conversation_id,
            },
        )
    finally:
        if close_located_sessions and row_db is not None:
            close_row_sessions(row_db, extra_catalog)


def _resolve_call_recording(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    source_ref: str,
    display_label: Optional[str],
) -> ResolvedCallSample:
    recording = (
        db.query(CallRecording)
        .filter(
            CallRecording.call_short_id == source_ref,
            CallRecording.organization_id == organization_id,
            CallRecording.workspace_id == workspace_id,
        )
        .first()
    )
    if not recording:
        raise HTTPException(status_code=404, detail="Call recording not found.")

    call_data = recording.call_data if isinstance(recording.call_data, dict) else {}
    platform = (recording.provider_platform or "").lower()
    transcript_text, _ = extract_transcript_from_call_data(call_data, platform)
    audio_s3_key = None
    evaluator_result_name = None
    if recording.evaluator_result_id:
        result = (
            db.query(EvaluatorResult)
            .filter(EvaluatorResult.id == recording.evaluator_result_id)
            .first()
        )
        if result:
            if result.audio_s3_key:
                audio_s3_key = result.audio_s3_key
            evaluator_result_name = result.name or result.result_id

    agent_name = None
    if recording.agent_id:
        agent = db.query(Agent).filter(Agent.id == recording.agent_id).first()
        agent_name = agent.name if agent else None

    label = (
        display_label
        or evaluator_result_name
        or agent_name
        or recording.call_short_id
    )
    return ResolvedCallSample(
        source_kind="call_recording",
        source_ref=recording.call_short_id,
        label=label,
        transcript=transcript_text or None,
        diarised_transcript=transcript_text or None,
        audio_s3_key=audio_s3_key,
        call_data=call_data or None,
        agent_id=recording.agent_id,
        metadata={
            "call_short_id": recording.call_short_id,
            "provider_platform": recording.provider_platform,
            "source": getattr(recording.source, "value", recording.source),
            "agent_name": agent_name,
            "evaluator_result_name": evaluator_result_name,
        },
    )


def _resolve_evaluator_result(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    source_ref: str,
    display_label: Optional[str],
) -> ResolvedCallSample:
    result = None
    try:
        result_uuid = UUID(source_ref)
        result = (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.id == result_uuid,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
            .first()
        )
    except ValueError:
        result = (
            db.query(EvaluatorResult)
            .filter(
                EvaluatorResult.result_id == source_ref,
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.workspace_id == workspace_id,
            )
            .first()
        )

    if not result:
        raise HTTPException(status_code=404, detail="Evaluator result not found.")

    persona_name = None
    scenario_name = None
    evaluator_name = None
    if result.persona_id:
        persona = db.query(Persona).filter(Persona.id == result.persona_id).first()
        persona_name = persona.name if persona else None
    if result.scenario_id:
        scenario = db.query(Scenario).filter(Scenario.id == result.scenario_id).first()
        scenario_name = scenario.name if scenario else None
    if result.evaluator_id:
        evaluator = db.query(Evaluator).filter(Evaluator.id == result.evaluator_id).first()
        evaluator_name = evaluator.name if evaluator else None

    label = display_label or result.name or result.result_id
    return ResolvedCallSample(
        source_kind="evaluator_result",
        source_ref=str(result.id),
        label=label,
        transcript=(result.transcription or "").strip() or None,
        diarised_transcript=(result.transcription or "").strip() or None,
        audio_s3_key=(result.audio_s3_key or "").strip() or None,
        call_data=result.call_data if isinstance(result.call_data, dict) else None,
        agent_id=result.agent_id,
        metadata={
            "result_id": result.result_id,
            "evaluator_id": str(result.evaluator_id) if result.evaluator_id else None,
            "evaluator_name": evaluator_name,
            "persona_id": str(result.persona_id) if result.persona_id else None,
            "persona_name": persona_name,
            "scenario_id": str(result.scenario_id) if result.scenario_id else None,
            "scenario_name": scenario_name,
            "agent_id": str(result.agent_id) if result.agent_id else None,
        },
    )


def resolve_source(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    source_kind: str,
    source_ref: str,
    display_label: Optional[str] = None,
) -> ResolvedCallSample:
    if source_kind == "call_import_row":
        return _resolve_call_import_row(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            display_label=display_label,
        )
    if source_kind == "call_recording":
        return _resolve_call_recording(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            display_label=display_label,
        )
    if source_kind == "evaluator_result":
        return _resolve_evaluator_result(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_ref=source_ref,
            display_label=display_label,
        )
    raise HTTPException(status_code=400, detail=f"Unknown source_kind: {source_kind}")


def preview_source_label(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    source_kind: str,
    source_ref: str,
    display_label: Optional[str] = None,
) -> str:
    sample = resolve_source(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        source_kind=source_kind,
        source_ref=source_ref,
        display_label=display_label,
    )
    return sample.label
