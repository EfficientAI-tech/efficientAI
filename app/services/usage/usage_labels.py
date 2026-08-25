"""Human-readable labels for usage attribution context (no raw UUIDs in UI)."""

from __future__ import annotations

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
    EvaluatorResult,
    TTSComparison,
)

RESOURCE_TYPE_LABELS = {
    "call_import_evaluation": "Evaluation",
    "call_import": "Import",
    "tts_comparison": "Simulation",
    "evaluator_result": "Evaluator result",
    "agent": "Agent",
    "metric": "Metric",
}

_USAGE_KIND_LABELS = {
    "llm": "LLM",
    "stt": "STT",
    "tts": "TTS",
}


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

    def preload(self, contexts: list[Dict[str, Any]]) -> None:
        eval_ids: Set[UUID] = set()
        import_ids: Set[UUID] = set()
        row_ids: Set[UUID] = set()
        comparison_ids: Set[UUID] = set()
        agent_ids: Set[UUID] = set()
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
                        eval_ids.add(uid)
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

        if evaluator_result_ids:
            for row in (
                self._db.query(EvaluatorResult)
                .filter(
                    EvaluatorResult.organization_id == self._organization_id,
                    EvaluatorResult.id.in_(evaluator_result_ids),
                )
                .all()
            ):
                if row.agent_id:
                    agent_ids.add(row.agent_id)

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

    def resource_name(self, raw_id: str, resource_type: Optional[str]) -> str:
        if resource_type == "call_import_evaluation":
            return self.evaluation_name(raw_id)
        if resource_type == "call_import":
            return self.call_import_name(raw_id)
        if resource_type == "tts_comparison":
            return self.tts_comparison_name(raw_id)
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
    name = (row.name or "").strip() or "Simulation"
    sim = (row.simulation_id or "").strip()
    if sim:
        return f"{name} #{sim}"
    return format_entity_label(name, row.id, "Simulation")


def _agent_display_name(row: Agent) -> str:
    name = (row.name or "").strip() or "Agent"
    short = (row.agent_id or "").strip()
    if short:
        return f"{name} #{short}"
    return format_entity_label(name, row.id, "Agent")


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
    elif resource_type == "agent" and resource_id:
        parts.append(resolver.agent_name(resource_id))
    elif agent_id:
        parts.append(resolver.agent_name(agent_id))
    elif resource_type == "evaluator_result" and resource_id:
        parts.append(resolver.resource_name(resource_id, resource_type))
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
