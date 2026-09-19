"""Human-readable labels for usage attribution context (no raw UUIDs in UI)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import (
    Agent,
    CallImport,
    CallImportEvaluation,
    CallImportRow,
    CallImportTag,
    CallImportTagAssignment,
    CallRecording,
    Evaluator,
    EvaluatorResult,
    EvaluatorSuite,
    Persona,
    Scenario,
    TTSComparison,
)

RESOURCE_TYPE_LABELS = {
    "call_import_evaluation": "Evaluation",
    "call_import": "Import",
    "tts_comparison": "Simulation",
    "evaluator_result": "Evaluator result",
    "evaluator": "Evaluator",
    "agent": "Agent",
    "metric": "Metric",
}

_USAGE_KIND_LABELS = {
    "llm": "LLM",
    "stt": "STT",
    "tts": "TTS",
}

_PROVIDER_PLATFORM_LABELS = {
    "retell": "Retell",
    "vapi": "Vapi",
    "voice_bundle": "Voice bundle",
    "custom_websocket": "WebSocket",
}


@dataclass(frozen=True)
class _CallRecordingMeta:
    call_short_id: Optional[str]
    source: Any
    provider_platform: Optional[str]


def usage_kind_label(kind: Optional[str]) -> str:
    if not kind:
        return "—"
    return _USAGE_KIND_LABELS.get(kind, kind)


def short_entity_id(uid: UUID) -> str:
    return str(uid)[:8]


def format_entity_label(
    custom_name: Optional[str],
    uid: UUID,
    default_prefix: str,
) -> str:
    """Human label: name-shortId (e.g. unauthenticated sheet.xlsx-3111d376)."""
    short = short_entity_id(uid)
    text = (custom_name or "").strip()
    if text:
        return f"{text}-{short}"
    return f"{default_prefix}-{short}"


class UsageNameResolver:
    """Batch-resolve entity names for usage context JSONB keys."""

    def __init__(self, db: Session, organization_id: UUID) -> None:
        self._db = db
        self._organization_id = organization_id
        self._evaluations: Dict[UUID, str] = {}
        self._call_imports: Dict[UUID, str] = {}
        self._call_import_rows: Dict[UUID, str] = {}
        self._tts_comparisons: Dict[UUID, str] = {}
        self._agents: Dict[UUID, str] = {}
        self._evaluators: Dict[UUID, str] = {}
        self._evaluator_results: Dict[UUID, str] = {}

    def preload(self, contexts: list[Dict[str, Any]]) -> None:
        eval_ids: Set[UUID] = set()
        import_ids: Set[UUID] = set()
        row_ids: Set[UUID] = set()
        comparison_ids: Set[UUID] = set()
        agent_ids: Set[UUID] = set()
        evaluator_ids: Set[UUID] = set()
        evaluator_result_ids: Set[UUID] = set()

        for ctx in contexts:
            if not ctx:
                continue
            norm = _normalize_context(ctx)
            rtype = norm.get("resource_type")
            resource_id = norm.get("resource_id")
            if resource_id:
                uid = parse_uuid(resource_id)
                if uid:
                    if rtype == "call_import":
                        import_ids.add(uid)
                    elif rtype == "call_import_evaluation":
                        eval_ids.add(uid)
                    elif rtype == "tts_comparison":
                        comparison_ids.add(uid)
                    elif rtype == "agent":
                        agent_ids.add(uid)
                    elif rtype == "evaluator_result":
                        evaluator_result_ids.add(uid)
                    elif rtype == "evaluator":
                        evaluator_ids.add(uid)
                    else:
                        eval_ids.add(uid)
                        import_ids.add(uid)
            for key, bucket in (
                ("evaluation_id", eval_ids),
                ("call_import_id", import_ids),
                ("call_import_row_id", row_ids),
                ("agent_id", agent_ids),
                ("evaluator_result_id", evaluator_result_ids),
            ):
                raw = norm.get(key)
                if not raw:
                    continue
                uid = parse_uuid(raw)
                if uid:
                    bucket.add(uid)

        if eval_ids:
            for row in (
                self._db.query(CallImportEvaluation)
                .filter(
                    CallImportEvaluation.organization_id == self._organization_id,
                    CallImportEvaluation.id.in_(eval_ids),
                )
                .all()
            ):
                self._evaluations[row.id] = format_entity_label(
                    row.name, row.id, "Evaluation"
                )

        tag_names_by_import: Dict[UUID, list[str]] = {}
        if import_ids:
            for cid, tag_name in (
                self._db.query(
                    CallImportTagAssignment.call_import_id,
                    CallImportTag.name,
                )
                .join(
                    CallImportTag,
                    CallImportTag.id == CallImportTagAssignment.tag_id,
                )
                .filter(CallImportTagAssignment.call_import_id.in_(import_ids))
                .all()
            ):
                tag_names_by_import.setdefault(cid, []).append(tag_name)

        if import_ids:
            for row in (
                self._db.query(CallImport)
                .filter(
                    CallImport.organization_id == self._organization_id,
                    CallImport.id.in_(import_ids),
                )
                .all()
            ):
                display_name, prefix = _call_import_label_parts(
                    row,
                    sorted(tag_names_by_import.get(row.id, [])),
                )
                self._call_imports[row.id] = format_entity_label(
                    display_name, row.id, prefix
                )

        if comparison_ids:
            for row in (
                self._db.query(TTSComparison)
                .filter(
                    TTSComparison.organization_id == self._organization_id,
                    TTSComparison.id.in_(comparison_ids),
                )
                .all()
            ):
                self._tts_comparisons[row.id] = _tts_comparison_display_name(row)

        call_meta_by_result: Dict[UUID, _CallRecordingMeta] = {}
        pending_results: list[EvaluatorResult] = []
        pending_evaluators: list[Evaluator] = []

        if evaluator_result_ids:
            for rec in (
                self._db.query(CallRecording)
                .filter(CallRecording.evaluator_result_id.in_(evaluator_result_ids))
                .all()
            ):
                if rec.evaluator_result_id:
                    call_meta_by_result[rec.evaluator_result_id] = _CallRecordingMeta(
                        call_short_id=str(rec.call_short_id) if rec.call_short_id else None,
                        source=rec.source,
                        provider_platform=rec.provider_platform,
                    )

            pending_results = (
                self._db.query(EvaluatorResult)
                .filter(
                    EvaluatorResult.organization_id == self._organization_id,
                    EvaluatorResult.id.in_(evaluator_result_ids),
                )
                .all()
            )
            for row in pending_results:
                if row.agent_id:
                    agent_ids.add(row.agent_id)

        if evaluator_ids:
            pending_evaluators = (
                self._db.query(Evaluator)
                .filter(
                    Evaluator.organization_id == self._organization_id,
                    Evaluator.id.in_(evaluator_ids),
                )
                .all()
            )
            for row in pending_evaluators:
                if row.agent_id:
                    agent_ids.add(row.agent_id)

        persona_ids: Set[UUID] = set()
        scenario_ids: Set[UUID] = set()
        suite_ids: Set[UUID] = set()
        for row in pending_results:
            if row.persona_id:
                persona_ids.add(row.persona_id)
            if row.scenario_id:
                scenario_ids.add(row.scenario_id)
        for row in pending_evaluators:
            if row.persona_id:
                persona_ids.add(row.persona_id)
            if row.scenario_id:
                scenario_ids.add(row.scenario_id)
            if row.suite_id:
                suite_ids.add(row.suite_id)

        missing_agent_ids = [uid for uid in agent_ids if uid not in self._agents]
        if missing_agent_ids:
            for row in (
                self._db.query(Agent)
                .filter(
                    Agent.organization_id == self._organization_id,
                    Agent.id.in_(missing_agent_ids),
                )
                .all()
            ):
                self._agents[row.id] = _agent_display_name(row)

        persona_names: Dict[UUID, str] = {}
        if persona_ids:
            for row in (
                self._db.query(Persona)
                .filter(
                    Persona.organization_id == self._organization_id,
                    Persona.id.in_(persona_ids),
                )
                .all()
            ):
                persona_names[row.id] = _clean_name(row.name, "Persona")

        scenario_names: Dict[UUID, str] = {}
        if scenario_ids:
            for row in (
                self._db.query(Scenario)
                .filter(
                    Scenario.organization_id == self._organization_id,
                    Scenario.id.in_(scenario_ids),
                )
                .all()
            ):
                scenario_names[row.id] = _clean_name(row.name, "Scenario")

        suite_names: Dict[UUID, str] = {}
        if suite_ids:
            for row in (
                self._db.query(EvaluatorSuite)
                .filter(
                    EvaluatorSuite.organization_id == self._organization_id,
                    EvaluatorSuite.id.in_(suite_ids),
                )
                .all()
            ):
                suite_names[row.id] = _clean_name(row.name, "Suite")

        for row in pending_results:
            agent_label = self._agents.get(row.agent_id) if row.agent_id else None
            self._evaluator_results[row.id] = _evaluator_result_display_name(
                row,
                agent_label,
                call_meta_by_result.get(row.id),
                persona_names.get(row.persona_id) if row.persona_id else None,
                scenario_names.get(row.scenario_id) if row.scenario_id else None,
            )

        for row in pending_evaluators:
            agent_label = self._agents.get(row.agent_id) if row.agent_id else None
            self._evaluators[row.id] = _evaluator_display_name(
                row,
                agent_label,
                persona_names.get(row.persona_id) if row.persona_id else None,
                scenario_names.get(row.scenario_id) if row.scenario_id else None,
                suite_names.get(row.suite_id) if row.suite_id else None,
            )

        if row_ids:
            for row in (
                self._db.query(CallImportRow)
                .filter(
                    CallImportRow.organization_id == self._organization_id,
                    CallImportRow.id.in_(row_ids),
                )
                .all()
            ):
                self._call_import_rows[row.id] = _clean_name(
                    row.conversation_id, "Conversation"
                )

    def evaluation_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._evaluations:
            return self._evaluations[uid]
        if uid:
            return format_entity_label(None, uid, "Evaluation")
        return "Evaluation"

    def call_import_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._call_imports:
            return self._call_imports[uid]
        if uid:
            return format_entity_label(None, uid, "Import")
        return "Import"

    def tts_comparison_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._tts_comparisons:
            return self._tts_comparisons[uid]
        if uid:
            return format_entity_label(None, uid, "Simulation")
        return "Simulation"

    def agent_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._agents:
            return self._agents[uid]
        if uid:
            return format_entity_label(None, uid, "Agent")
        return "Agent"

    def evaluator_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._evaluators:
            return self._evaluators[uid]
        if uid:
            return format_entity_label(None, uid, "Evaluator")
        return "Evaluator"

    def evaluator_result_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._evaluator_results:
            return self._evaluator_results[uid]
        if uid:
            return format_entity_label(None, uid, "Run")
        return "Run"

    def resource_name(self, raw_id: str, resource_type: Optional[str]) -> str:
        if resource_type == "call_import_evaluation":
            return self.evaluation_name(raw_id)
        if resource_type == "call_import":
            return self.call_import_name(raw_id)
        if resource_type == "tts_comparison":
            return self.tts_comparison_name(raw_id)
        if resource_type == "evaluator":
            return self.evaluator_name(raw_id)
        if resource_type == "evaluator_result":
            return self.evaluator_result_name(raw_id)
        if resource_type == "agent":
            return self.agent_name(raw_id)
        uid = parse_uuid(raw_id)
        if uid:
            prefix = RESOURCE_TYPE_LABELS.get(resource_type or "", "Resource")
            return format_entity_label(None, uid, prefix)
        return RESOURCE_TYPE_LABELS.get(resource_type or "", "Unscoped")

    def call_import_row_name(self, raw_id: str) -> str:
        uid = parse_uuid(raw_id)
        if uid and uid in self._call_import_rows:
            return self._call_import_rows[uid]
        return "Conversation"


def parse_uuid(raw: Any) -> Optional[UUID]:
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _clean_name(value: Optional[str], fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def _call_import_title(row: CallImport) -> Optional[str]:
    filename = (row.original_filename or "").strip()
    if filename:
        return filename
    dataset = (row.dataset or "").strip()
    if dataset:
        return dataset
    return None


def _call_import_meta_suffix(row: CallImport, tag_names: list[str]) -> str:
    parts: list[str] = []
    dataset = (row.dataset or "").strip()
    filename = (row.original_filename or "").strip()
    if dataset and dataset != filename:
        parts.append(dataset)
    for name in tag_names:
        if name and name not in parts:
            parts.append(name)
    if not parts:
        return ""
    return f" ({' · '.join(parts)})"


def _call_import_label_parts(
    row: CallImport,
    tag_names: list[str],
) -> tuple[Optional[str], str]:
    base = _call_import_title(row)
    suffix = _call_import_meta_suffix(row, tag_names)
    if base:
        return f"{base}{suffix}", "Import"
    if suffix:
        return suffix.strip(" ()"), "Import"
    return None, "Import"


def _tts_comparison_display_name(row: TTSComparison) -> str:
    name = (row.name or "").strip()
    if name:
        return name
    sim = (row.simulation_id or "").strip()
    if sim:
        return f"Simulation #{sim}"
    return format_entity_label(None, row.id, "Simulation")


def _agent_display_name(row: Agent) -> str:
    name = (row.name or "").strip()
    if name:
        return name
    short = (row.agent_id or "").strip()
    if short:
        return f"Agent #{short}"
    return format_entity_label(None, row.id, "Agent")


def _platform_label(platform: Optional[str]) -> Optional[str]:
    if not platform:
        return None
    key = platform.strip().lower()
    return _PROVIDER_PLATFORM_LABELS.get(key, key.replace("_", " ").title())


def _call_source_label(source: Any) -> Optional[str]:
    raw = getattr(source, "value", source)
    if not raw:
        return None
    key = str(raw).strip().lower()
    if key == "playground":
        return "Playground"
    if key == "webhook":
        return "Live call"
    return str(raw).replace("_", " ").title()


def _format_usage_timestamp(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return None


def _dedupe_result_name(name: str, agent_name: str) -> str:
    text = name.strip()
    if not text or not agent_name:
        return text
    for sep in (" - ", " · "):
        suffix = f"{sep}{agent_name}"
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    if text == agent_name:
        return ""
    return text


def _friendly_run_suffix(
    row: EvaluatorResult,
    agent_name: str,
    persona_name: Optional[str],
    scenario_name: Optional[str],
    call_meta: Optional[_CallRecordingMeta],
) -> str:
    name = _dedupe_result_name((row.name or ""), agent_name)
    if name:
        return name

    if persona_name and scenario_name:
        return f"{persona_name} · {scenario_name}"
    if scenario_name:
        return scenario_name
    if persona_name:
        return persona_name

    if call_meta:
        source_label = _call_source_label(call_meta.source)
        platform = _platform_label(call_meta.provider_platform)
        if source_label == "Playground":
            return f"Playground · {platform}" if platform else "Playground call"
        if source_label:
            return f"{source_label} · {platform}" if platform else source_label

    platform = _platform_label(getattr(row, "provider_platform", None))
    if platform:
        return platform

    ts = _format_usage_timestamp(
        getattr(row, "timestamp", None) or getattr(row, "created_at", None)
    )
    if ts:
        return ts

    run_short = (row.result_id or "").strip()
    if run_short:
        return f"Run #{run_short}"
    return format_entity_label(None, row.id, "Run")


def _evaluator_display_name(
    row: Evaluator,
    agent_label: Optional[str],
    persona_name: Optional[str],
    scenario_name: Optional[str],
    suite_name: Optional[str],
) -> str:
    name = (row.name or "").strip() or (suite_name or "").strip() or "Evaluator"
    ctx_parts: list[str] = []
    if scenario_name:
        ctx_parts.append(scenario_name)
    if persona_name and persona_name not in ctx_parts:
        ctx_parts.append(persona_name)

    if ctx_parts and name in ("Evaluator", (suite_name or "").strip()):
        evaluator_label = " · ".join(ctx_parts)
    elif ctx_parts and name not in ctx_parts:
        evaluator_label = f"{name} · {' · '.join(ctx_parts)}"
    else:
        evaluator_label = name

    if agent_label:
        return f"{agent_label} · {evaluator_label}"
    return evaluator_label


def _evaluator_result_display_name(
    row: EvaluatorResult,
    agent_label: Optional[str],
    call_meta: Optional[_CallRecordingMeta],
    persona_name: Optional[str],
    scenario_name: Optional[str],
) -> str:
    agent_name = (agent_label or "").strip()
    suffix = _friendly_run_suffix(row, agent_name, persona_name, scenario_name, call_meta)
    if agent_label:
        return f"{agent_label} · {suffix}"
    name = (row.name or "").strip()
    if name:
        return f"{name} · {suffix}"
    return suffix


def _normalize_context(raw: Any) -> Dict[str, str]:
    if not raw or not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _richest_context(contexts: list[Dict[str, str]]) -> Dict[str, str]:
    if not contexts:
        return {}
    return max(contexts, key=lambda c: len(c))


def build_usage_resource_label(
    context: Optional[Dict[str, Any]],
    resource_type: Optional[str],
    resolver: UsageNameResolver,
) -> str:
    """Hierarchical label: call import · evaluation · conversation."""
    ctx = _normalize_context(context)
    parts: list[str] = []

    call_import_id = ctx.get("call_import_id")
    if call_import_id:
        parts.append(resolver.call_import_name(call_import_id))
    elif resource_type == "call_import" and ctx.get("resource_id"):
        parts.append(resolver.call_import_name(ctx["resource_id"]))

    evaluation_id = ctx.get("evaluation_id")
    agent_id = ctx.get("agent_id")
    resource_id = ctx.get("resource_id")
    if evaluation_id:
        parts.append(resolver.evaluation_name(evaluation_id))
    elif resource_type == "call_import_evaluation" and resource_id:
        parts.append(resolver.evaluation_name(resource_id))
    elif resource_type == "tts_comparison" and resource_id:
        parts.append(resolver.tts_comparison_name(resource_id))
    elif resource_type == "evaluator_result" and resource_id:
        parts.append(resolver.evaluator_result_name(resource_id))
    elif resource_type == "evaluator" and resource_id:
        parts.append(resolver.evaluator_name(resource_id))
    elif resource_type == "agent" and resource_id:
        parts.append(resolver.agent_name(resource_id))
    elif agent_id:
        parts.append(resolver.agent_name(agent_id))
    elif resource_type and resource_id:
        parts.append(resolver.resource_name(resource_id, resource_type))

    row_id = ctx.get("call_import_row_id")
    if row_id:
        parts.append(resolver.call_import_row_name(row_id))

    if not parts:
        rid = resource_id or agent_id
        if rid and (resource_type == "agent" or agent_id):
            return resolver.agent_name(rid)
        if resource_type:
            prefix = RESOURCE_TYPE_LABELS.get(resource_type, resource_type)
            uid = parse_uuid(rid)
            if uid:
                return format_entity_label(None, uid, prefix)
            return prefix
        return "Unscoped"

    return " / ".join(parts)


def labels_for_resource_buckets(
    buckets: list[tuple[Optional[str], Optional[str], list[Dict[str, Any]]]],
    resolver: UsageNameResolver,
) -> Dict[str, str]:
    """Map resource_id string -> label; buckets are (resource_id, resource_type, contexts)."""
    labels: Dict[str, str] = {}
    for raw_id, resource_type, contexts in buckets:
        if not raw_id:
            continue
        ctx = _richest_context([_normalize_context(c) for c in contexts])
        merged = dict(ctx)
        merged.setdefault("resource_id", raw_id)
        if resource_type:
            merged.setdefault("resource_type", resource_type)
        labels[str(raw_id)] = build_usage_resource_label(
            merged, resource_type, resolver
        )
    return labels


def labels_for_call_import_ids(
    import_ids: list[UUID],
    resolver: UsageNameResolver,
) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for uid in import_ids:
        labels[str(uid)] = resolver.call_import_name(str(uid))
    return labels


def collect_contexts_from_rows(rows: list[Any]) -> list[Dict[str, Any]]:
    return [_normalize_context(r[0]) for r in rows if r and r[0]]
