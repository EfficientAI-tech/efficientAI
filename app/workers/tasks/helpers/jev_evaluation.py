"""Evaluate Jev metrics via TypeSafe ``/v1/systemone`` or provider chat."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import ModelProvider
from app.services.ai.jev_client import JevClientError, decide
from app.services.ai.model_config_service import model_config_service
from app.services.credentials import resolve_ai_provider

JEV_TAG = "jev"
JEV_MISSING_MODEL_ERROR = (
    "Jev metrics require a Jev-capable model "
    "(Together Tev1, TypeSafe Jev, or OpenRouter Jev)"
)
_JEV_NAME_RE = re.compile(r"(tev1|jev)", re.IGNORECASE)
_CHAT_KV_RE = re.compile(
    r"""
    ^\s*
    (?:[-*•]\s+)?
    (?:\*\*|__)?
    ["']?
    (?P<key>[A-Za-z_][\w\s/.-]*?)
    ["']?
    (?:\*\*|__)?
    \s*
    (?::|=|—|–)\s*
    (?P<value>.*?)
    \s*$
    """,
    re.VERBOSE,
)

_USER_LABEL_RE = re.compile(
    r"\b(user|caller|customer|human|visitor|client|patient|guest|"
    r"consumer|caller_a|party_a)\b",
    re.IGNORECASE,
)
_AGENT_LABEL_RE = re.compile(
    r"\b(agent|bot|assistant|ai|operator|support|representative|"
    r"advisor|exec|executive|rep|caller_b|party_b|host|system)\b",
    re.IGNORECASE,
)
_TURN_LINE_RE = re.compile(
    r"^(?:\[.*?\]\s*)?(?P<speaker>[^:]{1,64}):\s*(?P<text>.*)$"
)


def is_jev_metric(metric) -> bool:
    raw = getattr(metric, "custom_data_type", None)
    if str(raw or "").strip().lower() == JEV_TAG:
        return True
    tags = getattr(metric, "tags", None)
    if isinstance(tags, list):
        return any(str(tag or "").strip().lower() == JEV_TAG for tag in tags)
    return False


def snapshot_jev_metric(metric) -> Any:
    """Copy Jev fields so scoring still works after the DB session closes."""
    from types import SimpleNamespace

    cfg = getattr(metric, "custom_config", None)
    tags = getattr(metric, "tags", None)
    return SimpleNamespace(
        id=getattr(metric, "id", None),
        name=getattr(metric, "name", "metric"),
        description=getattr(metric, "description", None),
        custom_data_type=getattr(metric, "custom_data_type", None) or JEV_TAG,
        custom_config=dict(cfg) if isinstance(cfg, dict) else {},
        tags=list(tags) if isinstance(tags, list) else ["jev"],
    )


def is_jev_model(provider: str | None, model: str | None) -> bool:
    """True for TypeSafe Jev, Together Tev1, or any slug containing jev/tev1."""
    name = (model or "").strip()
    if not name:
        return False
    provider_key = (provider or "").strip().lower()
    if provider_key == ModelProvider.TYPESAFE.value:
        return True
    if _JEV_NAME_RE.search(name):
        return True
    cfg = model_config_service.get_model_config(name) or {}
    catalog_provider = (cfg.get("provider") or "").strip().lower()
    return catalog_provider == ModelProvider.TYPESAFE.value


def _systemone_model_name(model: str | None) -> str:
    """TypeSafe ``/v1/systemone`` wants ``jev-1.13.0``, not ``typesafe/jev-1.13.0``."""
    name = (model or "").strip()
    if name.lower().startswith("typesafe/"):
        return name.split("/", 1)[1] or name
    return name


def uses_typesafe_systemone(provider: str | None) -> bool:
    """Native TypeSafe credentials call ``/v1/systemone``; others use chat."""
    return (provider or "").strip().lower() == ModelProvider.TYPESAFE.value


def classify_speaker(speaker: str) -> str:
    text = (speaker or "").strip()
    if not text:
        return "other"
    if _USER_LABEL_RE.search(text):
        return "user"
    if _AGENT_LABEL_RE.search(text):
        return "agent"
    return "other"


def _try_parse_json_turns(transcript: str) -> list[dict[str, str]] | None:
    trimmed = (transcript or "").strip()
    if not (trimmed.startswith("[") or trimmed.startswith("{")):
        return None
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        return None
    messages = parsed
    if isinstance(parsed, dict):
        messages = parsed.get("messages") or parsed.get("turns")
    if not isinstance(messages, list):
        return None
    turns: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        speaker = str(
            item.get("speaker") or item.get("role") or item.get("name") or ""
        ).strip()
        text = str(item.get("text") or item.get("content") or "").strip()
        if speaker and text:
            turns.append({"speaker": speaker, "text": text})
    return turns or None


def parse_transcript_turns(transcript: str) -> list[dict[str, str]]:
    """Parse ``speaker: text`` lines or a JSON turn array."""
    json_turns = _try_parse_json_turns(transcript)
    if json_turns is not None:
        return json_turns

    turns: list[dict[str, str]] = []
    pending: dict[str, str] | None = None
    for raw_line in (transcript or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TURN_LINE_RE.match(line)
        if match:
            if pending:
                turns.append(pending)
            pending = {
                "speaker": match.group("speaker").strip(),
                "text": match.group("text").strip(),
            }
            continue
        if pending:
            extra = line
            pending["text"] = (
                f"{pending['text']} {extra}".strip() if pending["text"] else extra
            )
    if pending and pending.get("text"):
        turns.append(pending)
    return turns


def build_state(transcript: str, source: str = "both") -> Any:
    """Build Jev ``state``: filtered turns, or the raw transcript for ``both``."""
    wanted = (source or "both").strip().lower()
    if wanted not in {"user", "agent", "both"}:
        wanted = "both"
    turns = parse_transcript_turns(transcript)
    if not turns:
        return (transcript or "").strip() if wanted == "both" else []

    filtered: list[dict[str, str]] = []
    for turn in turns:
        side = classify_speaker(turn["speaker"])
        if wanted == "both":
            if side in {"user", "agent"}:
                filtered.append({"speaker": side, "text": turn["text"]})
        elif side == wanted:
            filtered.append({"speaker": side, "text": turn["text"]})
    if filtered:
        return filtered
    if wanted == "both":
        return (transcript or "").strip()
    return []


def _jev_config(metric) -> dict[str, Any]:
    cfg = getattr(metric, "custom_config", None)
    return dict(cfg) if isinstance(cfg, dict) else {}


def _jev_instructions(metric) -> str:
    return (
        getattr(metric, "description", None) or getattr(metric, "name", "") or ""
    ).strip() or str(getattr(metric, "name", "metric"))


def _question_from_block(
    jev_type: str,
    block: dict[str, Any],
    *,
    instructions: str,
    include_other: bool = False,
) -> dict[str, Any]:
    question: dict[str, Any] = {"type": jev_type, "instructions": instructions}
    criteria = block.get("criteria")
    if jev_type == "choice":
        choice_criteria = dict(criteria) if isinstance(criteria, dict) else {}
        if include_other and not any(
            str(k).strip().lower() == "other" for k in choice_criteria
        ):
            choice_criteria["other"] = "None of the listed options fit"
        question["criteria"] = choice_criteria
    elif criteria is not None:
        question["criteria"] = criteria
    return question


def iter_jev_question_specs(metric) -> list[tuple[str, dict[str, Any], Any]]:
    """Yield ``(jev_type, question, confidence_threshold)`` for a metric."""
    cfg = _jev_config(metric)
    instructions = _jev_instructions(metric)
    raw_questions = cfg.get("questions")
    specs: list[tuple[str, dict[str, Any], Any]] = []
    if isinstance(raw_questions, dict):
        for jev_type in ("noul", "choice", "score"):
            block = raw_questions.get(jev_type)
            if not isinstance(block, dict):
                continue
            question = _question_from_block(
                jev_type,
                block,
                instructions=instructions,
                include_other=bool(block.get("include_other")),
            )
            specs.append((jev_type, question, block.get("confidence_threshold")))
    if specs:
        return specs
    jev_type = str(cfg.get("jev_type") or "noul").strip().lower() or "noul"
    question = _question_from_block(
        jev_type,
        cfg,
        instructions=instructions,
        include_other=bool(cfg.get("include_other")),
    )
    return [(jev_type, question, cfg.get("confidence_threshold"))]


def build_jev_question(metric) -> dict[str, Any]:
    """First (or only) Jev question. Kept for single-type callers."""
    return iter_jev_question_specs(metric)[0][1]


def build_jev_questions(metric) -> dict[str, dict[str, Any]]:
    metric_id = str(getattr(metric, "id", "metric"))
    return {
        f"{metric_id}:{jev_type}": question
        for jev_type, question, _threshold in iter_jev_question_specs(metric)
    }


def jev_question_answer_key(metric, jev_type: str) -> str:
    return f"{getattr(metric, 'id', 'metric')}:{jev_type}"


def _needs_review(confidence: Any, threshold: Any) -> bool:
    """Flag review only when we have a numeric confidence below the threshold.

    Together Tev1 often omits confidence. Treating that as review sent every
    choice/score to humans.
    """
    if threshold is None or confidence is None:
        return False
    try:
        return float(confidence) < float(threshold)
    except (TypeError, ValueError):
        return False


def _noul_boolean(noul: Any) -> bool | None:
    parsed = _parse_float(noul) if noul is not None else None
    if parsed is None:
        return None
    return parsed >= 0.5


def format_noul_compact(noul: Any, value: Any = None) -> str:
    flag = value if isinstance(value, bool) else _noul_boolean(noul)
    label = "Yes" if flag else "No"
    parsed = _parse_float(noul)
    if parsed is None:
        return label
    return f"{label} ({parsed:.2f})"


def winner_score_level(
    answer: dict[str, Any],
    *,
    criteria: list | None = None,
    legend: dict | None = None,
) -> Any:
    levels = [str(item) for item in criteria] if isinstance(criteria, list) else []
    legend_map = legend if isinstance(legend, dict) else {}
    if isinstance(answer.get("legend"), dict):
        legend_map = {**legend_map, **answer["legend"]}
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict) and probabilities:
        best_key = None
        best_prob = None
        for key, raw in probabilities.items():
            parsed = _parse_float(raw)
            if parsed is None:
                continue
            if best_prob is None or parsed > best_prob:
                best_key = str(key)
                best_prob = parsed
        if best_key is not None:
            if best_key in legend_map:
                return str(legend_map[best_key])
            try:
                idx = int(float(best_key))
            except (TypeError, ValueError):
                idx = None
            if idx is not None and 0 <= idx < len(levels):
                return levels[idx]
            return best_key
    score = answer.get("score")
    idx = _parse_int(score)
    if idx is not None:
        if str(idx) in legend_map:
            return str(legend_map[str(idx)])
        if 0 <= idx < len(levels):
            return levels[idx]
    return score


def _map_question_answer(
    jev_type: str,
    answer: Any,
    *,
    threshold: Any,
    question: dict[str, Any],
) -> dict[str, Any]:
    mapped: dict[str, Any] = {
        "type": jev_type,
        "value": None,
        "needs_review": False,
    }
    if not isinstance(answer, dict):
        mapped["error"] = "Invalid Jev answer"
        return mapped
    if answer.get("error") and all(
        answer.get(field) is None for field in ("noul", "choice", "score")
    ):
        mapped["error"] = str(answer["error"])
        return mapped
    if jev_type == "noul":
        noul = _parse_float(answer.get("noul"))
        mapped["noul"] = noul if noul is not None else answer.get("noul")
        mapped["value"] = _noul_boolean(mapped["noul"])
        mapped["needs_review"] = False
        return mapped

    confidence = answer.get("confidence")
    mapped["confidence"] = confidence
    if threshold is not None:
        try:
            mapped["confidence_threshold"] = float(threshold)
        except (TypeError, ValueError):
            mapped["confidence_threshold"] = threshold
    mapped["needs_review"] = _needs_review(confidence, threshold)
    if mapped["needs_review"] and confidence is None:
        mapped["review_reason"] = "missing_confidence"
    if jev_type == "choice":
        mapped["value"] = answer.get("choice")
        mapped["choice"] = answer.get("choice")
        criteria_map = (
            question.get("criteria") if isinstance(question.get("criteria"), dict) else {}
        )
        if criteria_map:
            mapped["options"] = {str(key): str(label) for key, label in criteria_map.items()}
        incoming = answer.get("probabilities")
        if isinstance(incoming, dict) and incoming:
            mapped["probabilities"] = incoming
        return mapped

    criteria = question.get("criteria") if isinstance(question.get("criteria"), list) else []
    mapped["score"] = answer.get("score")
    if isinstance(answer.get("legend"), dict):
        mapped["legend"] = answer["legend"]
    elif criteria:
        mapped["legend"] = {str(idx): str(label) for idx, label in enumerate(criteria)}
    incoming = answer.get("probabilities")
    if isinstance(incoming, dict) and incoming:
        mapped["probabilities"] = incoming
    mapped["value"] = winner_score_level(
        answer,
        criteria=criteria,
        legend=mapped.get("legend") if isinstance(mapped.get("legend"), dict) else None,
    )
    return mapped


def compact_jev_value(questions: dict[str, Any]) -> Any:
    parts: list[str] = []
    noul = questions.get("noul")
    if isinstance(noul, dict) and noul.get("value") is not None:
        parts.append(format_noul_compact(noul.get("noul"), noul.get("value")))
    choice = questions.get("choice")
    if isinstance(choice, dict) and choice.get("value") not in (None, ""):
        parts.append(str(choice["value"]))
    score = questions.get("score")
    if isinstance(score, dict) and score.get("value") not in (None, ""):
        parts.append(str(score["value"]))
    if len(parts) == 1:
        if noul and noul.get("value") is not None and len(questions) == 1:
            return noul["value"]
        if choice and "choice" in questions and "score" not in questions and "noul" not in questions:
            return choice["value"]
        if score and "score" in questions and "choice" not in questions and "noul" not in questions:
            return score["value"]
        return parts[0]
    return " · ".join(parts) if parts else None


def official_jev_value(entry: dict[str, Any]) -> Any:
    review = entry.get("review")
    if isinstance(review, dict) and review.get("resolved"):
        if "resolved_value" in review:
            return review.get("resolved_value")
    return entry.get("value")


def map_jev_answers(metric, answers: dict[str, Any] | None) -> dict[str, Any]:
    specs = iter_jev_question_specs(metric)
    name = getattr(metric, "name", "metric")
    types = [jev_type for jev_type, _q, _t in specs]
    entry: dict[str, Any] = {
        "type": "jev",
        "jev_type": types[0] if len(types) == 1 else "bundle",
        "metric_name": name,
        "value": None,
        "needs_review": False,
        "questions": {},
        "raw": answers if isinstance(answers, dict) else {"error": "invalid_answer"},
    }
    if not isinstance(answers, dict):
        entry["error"] = "Invalid Jev answer"
        return entry

    answer_payloads: dict[str, Any] = {}
    for jev_type, question, threshold in specs:
        key = jev_question_answer_key(metric, jev_type)
        payload = answers.get(key)
        if payload is None and len(specs) == 1:
            payload = answers.get(str(getattr(metric, "id", "")))
        if payload is None and len(specs) == 1 and answers.get("type") == jev_type:
            payload = answers
        if payload is None and len(specs) == 1 and (
            "noul" in answers or "choice" in answers or "score" in answers
        ):
            payload = answers
        mapped = _map_question_answer(
            jev_type, payload, threshold=threshold, question=question
        )
        entry["questions"][jev_type] = mapped
        answer_payloads[jev_type] = mapped
        if mapped.get("error") and not entry.get("question_error"):
            entry["question_error"] = mapped["error"]

    failed_questions = [
        item
        for item in answer_payloads.values()
        if isinstance(item, dict) and item.get("error")
    ]
    if failed_questions and len(failed_questions) == len(answer_payloads):
        entry["error"] = failed_questions[0]["error"]

    entry["needs_review"] = any(
        bool(item.get("needs_review"))
        for typ, item in answer_payloads.items()
        if typ in {"choice", "score"} and isinstance(item, dict)
    )
    for typ in ("choice", "score"):
        mapped = answer_payloads.get(typ)
        if isinstance(mapped, dict) and mapped.get("needs_review") and mapped.get("review_reason"):
            entry["review_reason"] = mapped["review_reason"]
            break
    if len(types) == 1:
        only = answer_payloads[types[0]]
        entry["value"] = only.get("value")
        if types[0] == "noul":
            entry["noul"] = only.get("noul")
        if types[0] in {"choice", "score"}:
            if "confidence" in only:
                entry["confidence"] = only.get("confidence")
            if "confidence_threshold" in only:
                entry["confidence_threshold"] = only.get("confidence_threshold")
            if "probabilities" in only:
                entry["probabilities"] = only.get("probabilities")
            if "legend" in only:
                entry["legend"] = only.get("legend")
            if "choice" in only:
                entry["choice"] = only.get("choice")
            if "score" in only:
                entry["score"] = only.get("score")
    else:
        entry["value"] = compact_jev_value(entry["questions"])
    return entry


def map_jev_answer(metric, answer: Any) -> dict[str, Any]:
    if isinstance(answer, dict) and any(
        str(key).endswith(f":{typ}") for key in answer for typ in ("noul", "choice", "score")
    ):
        return map_jev_answers(metric, answer)
    return map_jev_answers(metric, answer if isinstance(answer, dict) else None)


def apply_jev_review(
    score: dict[str, Any],
    *,
    question: str | None,
    value: Any,
    resolved_by: str | None,
    resolved_at: str,
) -> dict[str, Any]:
    updated = dict(score)
    questions = (
        dict(updated["questions"])
        if isinstance(updated.get("questions"), dict)
        else {}
    )
    original = updated.get("value")
    target = (question or "").strip().lower() or None
    if target in {"noul", "choice", "score"} and target in questions:
        block = dict(questions[target])
        original = block.get("value")
        official = original if value is None else value
        block["value"] = official
        block["needs_review"] = False
        questions[target] = block
    else:
        official = original if value is None else value
        for typ in ("choice", "score"):
            if typ in questions and isinstance(questions[typ], dict):
                questions[typ] = {**questions[typ], "needs_review": False}
        if official is None:
            official = original
    if questions:
        updated["questions"] = questions
        if target is None and value is None:
            official = compact_jev_value(questions)
    updated["value"] = official
    updated["needs_review"] = False
    updated["review"] = {
        "resolved": True,
        "resolved_by": resolved_by,
        "resolved_at": resolved_at,
        "resolved_value": official,
        "original_value": original,
    }
    return updated


def jev_error_score(metric, message: str) -> dict[str, Any]:
    specs = iter_jev_question_specs(metric)
    types = [jev_type for jev_type, _q, _t in specs]
    return {
        "type": "jev",
        "jev_type": types[0] if len(types) == 1 else "bundle",
        "metric_name": getattr(metric, "name", "metric"),
        "value": None,
        "needs_review": False,
        "error": message,
    }


def _resolve_override(
    metric,
    *,
    overrides: dict,
    run_provider: str | None,
    run_model: str | None,
    run_credential_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    override = overrides.get(str(getattr(metric, "id", ""))) or {}
    provider = override.get("provider") or run_provider or None
    model = override.get("model") or run_model or None
    credential_id = override.get("credential_id") or run_credential_id
    return (
        str(provider).strip() if provider else None,
        str(model).strip() if model else None,
        str(credential_id).strip() if credential_id else None,
    )


def _resolve_api_key(
    *,
    db: Session,
    organization_id: UUID,
    credential_id: str | None,
) -> str:
    parsed_id: Optional[UUID] = None
    if credential_id:
        try:
            parsed_id = UUID(str(credential_id))
        except (TypeError, ValueError):
            parsed_id = None
    row = resolve_ai_provider(
        ModelProvider.TYPESAFE.value,
        db,
        organization_id,
        parsed_id,
    )
    if row is None or not getattr(row, "api_key", None):
        raise JevClientError("No TypeSafe API key configured for this organization.")
    return decrypt_api_key(row.api_key)


def _parse_uuid(value: str | None) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def format_state_text(state: Any) -> str:
    if isinstance(state, list):
        lines: list[str] = []
        for turn in state:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker") or "speaker").strip() or "speaker"
            text = str(turn.get("text") or "").strip()
            if text:
                lines.append(f"{speaker}: {text}")
        if lines:
            return "\n".join(lines)
    return str(state or "").strip()


def build_jev_chat_prompt(question: dict[str, Any], state_text: str) -> str:
    jev_type = str(question.get("type") or "noul").strip().lower()
    instructions = str(question.get("instructions") or "").strip()
    criteria = question.get("criteria")
    lines = [
        "Score one question about this conversation.",
        "",
        "Conversation:",
        state_text or "(empty)",
        "",
        f"Question: {instructions or 'Score the conversation.'}",
    ]
    if jev_type == "noul":
        true_label = "Yes"
        false_label = "No"
        if isinstance(criteria, dict):
            true_label = str(criteria.get("true") or true_label)
            false_label = str(criteria.get("false") or false_label)
        lines.extend(
            [
                f"YES means: {true_label}",
                f"NO means: {false_label}",
                "",
                "Do NOT emit JSON, markdown fences, or curly braces.",
                "Reply with exactly one line:",
                "noul: <number from 0 to 1, probability that YES is correct>",
            ]
        )
    elif jev_type == "choice":
        options = (
            {str(k): str(v) for k, v in criteria.items()}
            if isinstance(criteria, dict)
            else {}
        )
        if options:
            lines.append("Options:")
            lines.extend(f"- {key}: {label}" for key, label in options.items())
        lines.extend(
            [
                "",
                "Reply with one line per option: <option> <probability from 0 to 1>.",
                "Include every option. Probabilities should sum to 1.",
                "Do not reply with only the winning option name.",
                "Example:",
            ]
        )
        example_keys = list(options)[:2] or ["option"]
        if len(example_keys) == 1:
            lines.append(f"{example_keys[0]} 1.00")
        else:
            lines.append(f"{example_keys[0]} 0.81")
            lines.append(f"{example_keys[1]} 0.19")
        lines.extend(f"{key} <probability>" for key in options)
    else:
        levels = criteria if isinstance(criteria, list) else []
        if levels:
            lines.append("Score levels:")
            lines.extend(f"- {idx}: {label}" for idx, label in enumerate(levels))
        last_idx = max(len(levels) - 1, 0)
        lines.extend(
            [
                "",
                "Reply with one line per level: <index> <probability from 0 to 1>.",
                "Include every level. Probabilities should sum to 1.",
                "Do not reply with only the winning index.",
                "Example:",
                "0 0.10",
                f"{min(1, last_idx)} 0.90" if last_idx > 0 else "0 1.00",
            ]
        )
        lines.extend(f"{idx} <probability>" for idx in range(len(levels)))
    return "\n".join(lines)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%").strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"yes", "true", "y"}:
        return 1.0
    if lowered in {"no", "false", "n"}:
        return 0.0
    try:
        number = float(text.split()[0])
    except (TypeError, ValueError):
        return None
    if 1.0 < number <= 100.0:
        number = number / 100.0
    return number


def _parse_int(value: Any) -> int | None:
    """Parse a score index. Do not reuse ``_parse_float`` — that treats ``2`` as 2%."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        return None
    text = str(value).strip()
    match = re.match(r"^-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_kv_lines(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        match = _CHAT_KV_RE.match(raw_line.strip())
        if not match:
            continue
        key = re.sub(r"\s+", " ", match.group("key").strip().lower())
        pairs[key] = match.group("value").strip()
    return pairs


def _extract_json_object(text: str) -> dict[str, Any] | None:
    trimmed = (text or "").strip()
    if not trimmed:
        return None
    if trimmed.startswith("```"):
        trimmed = re.sub(r"^```(?:json)?\s*", "", trimmed)
        trimmed = re.sub(r"\s*```$", "", trimmed)
    start = trimmed.find("{")
    end = trimmed.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(trimmed[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _choice_key(value: Any, options: dict[str, str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    for key in options:
        if key.lower() == lowered:
            return key
    for key, label in options.items():
        if str(label).strip().lower() == lowered:
            return key
    return text


def _known_choice(value: Any, options: dict[str, str]) -> str | None:
    found = _choice_key(value, options)
    if found is None:
        return None
    lowered = str(found).strip().lower()
    for key in options:
        if key.lower() == lowered:
            return key
    for key, label in options.items():
        if str(label).strip().lower() == lowered:
            return key
    return None


def _find_choice_in_text(text: str, options: dict[str, str]) -> str | None:
    if not text or not options:
        return None
    lowered = text.lower()
    ranked = sorted(
        options.items(),
        key=lambda item: max(len(str(item[0])), len(str(item[1] or ""))),
        reverse=True,
    )
    for key, label in ranked:
        if re.search(rf"\b{re.escape(str(key).lower())}\b", lowered):
            return key
        lab = str(label).strip()
        if lab and re.search(rf"\b{re.escape(lab.lower())}\b", lowered):
            return key
    return None


def _floats_in_text(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", text or ""):
        raw = match.group(1)
        if re.fullmatch(r"\d+", raw):
            continue
        parsed = _parse_float(raw)
        if parsed is not None and 0.0 <= parsed <= 1.0:
            values.append(parsed)
    return values


def _probability_beside_name(text: str, name: str) -> float | None:
    if not name or not text:
        return None
    pattern = re.compile(
        rf"(?im)(?:^|\n)\s*(?:[-*•]\s*)?{re.escape(name)}\s*(?::|=)?\s*"
        rf"([01](?:\.\d+)?|\.\d+)"
    )
    match = pattern.search(text)
    return _parse_float(match.group(1)) if match else None


def _extract_named_probabilities(
    text: str,
    names: dict[str, str],
    *,
    winner: str | None = None,
) -> dict[str, float]:
    kv = _parse_kv_lines(text)
    probabilities: dict[str, float] = {}
    for key, label in names.items():
        parsed = _parse_float(kv.get(str(key).lower()))
        if parsed is None and label:
            parsed = _parse_float(kv.get(str(label).strip().lower()))
        if parsed is None:
            parsed = _probability_beside_name(text, str(key))
        if parsed is None and label:
            parsed = _probability_beside_name(text, str(label).strip())
        if parsed is not None:
            probabilities[str(key)] = parsed
    if len(probabilities) >= len(names) or not names:
        return probabilities
    floats = _floats_in_text(text)
    if not floats:
        return probabilities
    if not probabilities:
        ordered = list(names)
        if winner and winner in names:
            ordered = [winner] + [key for key in names if key != winner]
        for key, val in zip(ordered, floats):
            probabilities[str(key)] = val
        return probabilities
    leftover = floats[len(probabilities) :]
    missing = [key for key in names if str(key) not in probabilities]
    for key, val in zip(missing, leftover):
        probabilities[str(key)] = val
    return probabilities


def parse_jev_chat_answer(question: dict[str, Any], text: str) -> dict[str, Any]:
    """Parse TypeSafe-shaped JSON or English ``key: value`` lines into a Jev answer."""
    jev_type = str(question.get("type") or "noul").strip().lower()
    blob = _extract_json_object(text)
    if isinstance(blob, dict):
        if jev_type == "noul" and blob.get("noul") is not None:
            noul = _parse_float(blob.get("noul"))
            if noul is not None:
                return {"type": "noul", "noul": noul, "source": "chat", "raw_text": text}
        if jev_type == "choice" and blob.get("choice") is not None:
            answer = {
                "type": "choice",
                "choice": blob.get("choice"),
                "source": "chat",
                "raw_text": text,
            }
            confidence = _parse_float(blob.get("confidence"))
            if confidence is not None:
                answer["confidence"] = confidence
            if isinstance(blob.get("probabilities"), dict) and blob["probabilities"]:
                answer["probabilities"] = blob["probabilities"]
            else:
                criteria = question.get("criteria")
                options = (
                    {str(k): str(v) for k, v in criteria.items()}
                    if isinstance(criteria, dict)
                    else {}
                )
                extracted = _extract_named_probabilities(
                    text,
                    options,
                    winner=_known_choice(blob.get("choice"), options),
                )
                if extracted:
                    answer["probabilities"] = extracted
                    if "confidence" not in answer:
                        answer["confidence"] = max(extracted.values())
            return answer
        if jev_type == "score" and blob.get("score") is not None:
            answer = {
                "type": "score",
                "score": blob.get("score"),
                "source": "chat",
                "raw_text": text,
            }
            confidence = _parse_float(blob.get("confidence"))
            if confidence is not None:
                answer["confidence"] = confidence
            if isinstance(blob.get("legend"), dict):
                answer["legend"] = blob["legend"]
            if isinstance(blob.get("probabilities"), dict) and blob["probabilities"]:
                answer["probabilities"] = blob["probabilities"]
            else:
                criteria = question.get("criteria")
                levels = criteria if isinstance(criteria, list) else []
                names = {str(idx): str(label) for idx, label in enumerate(levels)}
                winner_idx = _parse_int(blob.get("score"))
                extracted = _extract_named_probabilities(
                    text,
                    names,
                    winner=str(winner_idx) if winner_idx is not None else None,
                )
                if extracted:
                    answer["probabilities"] = extracted
                    if "confidence" not in answer:
                        answer["confidence"] = max(extracted.values())
            return answer

    kv = _parse_kv_lines(text)
    if jev_type == "noul":
        noul = _parse_float(kv.get("noul"))
        if noul is None:
            yes = _parse_float(kv.get("yes") or kv.get("true"))
            no = _parse_float(kv.get("no") or kv.get("false"))
            if yes is not None and no is not None and (yes + no) > 0:
                noul = yes / (yes + no)
            elif yes is not None:
                noul = yes
        if noul is None:
            for key in ("probability", "p", "p_yes", "value"):
                noul = _parse_float(kv.get(key))
                if noul is not None:
                    break
        if noul is None:
            # Together Tev1 often replies with a bare probability, e.g. "0.1".
            noul = _parse_float((text or "").strip())
        if noul is None:
            raise JevClientError(
                f"Could not parse Jev noul from chat response. Tail: {text[-180:]}"
            )
        return {"type": "noul", "noul": max(0.0, min(1.0, noul)), "source": "chat", "raw_text": text}

    if jev_type == "choice":
        criteria = question.get("criteria")
        options = (
            {str(k): str(v) for k, v in criteria.items()}
            if isinstance(criteria, dict)
            else {}
        )
        probabilities = _extract_named_probabilities(text, options)
        choice = _known_choice(kv.get("choice") or kv.get("answer"), options)
        if choice is None:
            for key in options:
                if key.lower() in kv:
                    choice = key
                    break
        if choice is None and probabilities and (
            not options or len(probabilities) >= len(options)
        ):
            choice = max(probabilities, key=probabilities.get)
        if choice is None:
            choice = _find_choice_in_text(text, options)
        if choice is None and probabilities:
            choice = max(probabilities, key=probabilities.get)
        if choice is None:
            raise JevClientError(
                f"Could not parse Jev choice from chat response. Tail: {text[-180:]}"
            )
        if not probabilities:
            probabilities = _extract_named_probabilities(
                text, options, winner=choice
            )
        confidence = _parse_float(kv.get("confidence"))
        if confidence is None and probabilities:
            confidence = max(probabilities.values())
        answer = {
            "type": "choice",
            "choice": choice,
            "source": "chat",
            "raw_text": text,
        }
        if confidence is not None:
            answer["confidence"] = confidence
        if probabilities:
            answer["probabilities"] = probabilities
        return answer

    criteria = question.get("criteria")
    levels = criteria if isinstance(criteria, list) else []
    names = {str(idx): str(label) for idx, label in enumerate(levels)}
    probabilities = _extract_named_probabilities(text, names)
    score_raw = kv.get("score") or kv.get("value")
    score: Any = None
    parsed_score = _parse_int(score_raw)
    if parsed_score is not None:
        score = parsed_score
    elif score_raw:
        lowered = str(score_raw).strip().lower()
        for idx, label in enumerate(levels):
            if str(label).strip().lower() == lowered:
                score = idx
                break
        if score is None:
            score = score_raw
    if score is None:
        first = next(
            (line.strip() for line in (text or "").splitlines() if line.strip()),
            "",
        )
        first_token = first.split()[0] if first else ""
        parsed_first = _parse_int(first_token)
        if parsed_first is not None:
            score = parsed_first
        else:
            lowered = first.lower()
            for idx, label in enumerate(levels):
                if str(label).strip().lower() == lowered or lowered == str(idx):
                    score = idx
                    break
            if score is None:
                for idx, label in enumerate(levels):
                    if str(label).strip().lower() in (text or "").lower():
                        score = idx
                        break
    if probabilities and (score is None or (names and len(probabilities) >= len(names))):
        best = max(probabilities, key=probabilities.get)
        try:
            score = int(best)
        except (TypeError, ValueError):
            score = best
    if not probabilities:
        probabilities = _extract_named_probabilities(
            text, names, winner=str(score) if score is not None else None
        )
    if score is None:
        raise JevClientError(
            f"Could not parse Jev score from chat response. Tail: {text[-180:]}"
        )
    confidence = _parse_float(kv.get("confidence"))
    if confidence is None and probabilities:
        confidence = max(probabilities.values())
    legend = {str(idx): str(label) for idx, label in enumerate(levels)} if levels else None
    answer = {
        "type": "score",
        "score": score,
        "source": "chat",
        "raw_text": text,
    }
    if confidence is not None:
        answer["confidence"] = confidence
    if probabilities:
        answer["probabilities"] = probabilities
    if legend:
        answer["legend"] = legend
    return answer


def _generate_jev_chat_response(
    *,
    messages: list[dict[str, str]],
    provider: str,
    model: str,
    organization_id: UUID,
    db: Session,
    credential_id: str | None,
) -> dict[str, Any]:
    from app.services.ai.llm_service import llm_service

    try:
        provider_enum = ModelProvider(provider)
    except ValueError as exc:
        raise JevClientError(f"Unknown Jev provider '{provider}'.") from exc
    return llm_service.generate_response(
        messages=messages,
        llm_provider=provider_enum,
        llm_model=model,
        organization_id=organization_id,
        db=db,
        temperature=0.0,
        max_tokens=256,
        credential_id=_parse_uuid(credential_id),
    )


def _evaluate_via_chat(
    question: dict[str, Any],
    *,
    state: Any,
    provider: str,
    model: str,
    organization_id: UUID,
    db: Session,
    credential_id: str | None,
) -> dict[str, Any]:
    prompt = build_jev_chat_prompt(question, format_state_text(state))
    result = _generate_jev_chat_response(
        messages=[{"role": "user", "content": prompt}],
        provider=provider,
        model=model,
        organization_id=organization_id,
        db=db,
        credential_id=credential_id,
    )
    text = ""
    if isinstance(result, dict):
        text = str(result.get("text") or "")
    return parse_jev_chat_answer(question, text)


def evaluate_with_jev(
    metrics: list,
    transcript: str,
    *,
    organization_id: UUID,
    db: Session,
    overrides: dict | None = None,
    run_provider: str | None = None,
    run_model: str | None = None,
    run_credential_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Score Jev metrics via TypeSafe systemone or provider chat."""
    scores: dict[str, dict[str, Any]] = {}
    if not metrics:
        return scores

    override_map = overrides if isinstance(overrides, dict) else {}
    ready: dict[tuple[str, str, str, str], list] = defaultdict(list)

    for metric in metrics:
        provider, model, credential_id = _resolve_override(
            metric,
            overrides=override_map,
            run_provider=run_provider,
            run_model=run_model,
            run_credential_id=run_credential_id,
        )
        if not is_jev_model(provider, model):
            scores[str(metric.id)] = jev_error_score(metric, JEV_MISSING_MODEL_ERROR)
            continue
        cfg = _jev_config(metric)
        state_source = str(cfg.get("state_source") or "both").strip().lower()
        ready[(provider or "", model or "", credential_id or "", state_source)].append(
            metric
        )

    for (provider, model, credential_id, state_source), bucket in ready.items():
        state = build_state(transcript, state_source)
        if state in ([], "", None):
            message = (
                f"No {state_source} turns found in the transcript for Jev state."
            )
            for metric in bucket:
                scores[str(metric.id)] = jev_error_score(metric, message)
            continue

        if uses_typesafe_systemone(provider):
            questions: dict[str, dict[str, Any]] = {}
            for metric in bucket:
                questions.update(build_jev_questions(metric))
            try:
                api_key = _resolve_api_key(
                    db=db,
                    organization_id=organization_id,
                    credential_id=credential_id or None,
                )
                payload = decide(
                    state=state,
                    questions=questions,
                    model=_systemone_model_name(model),
                    api_key=api_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Jev evaluation failed for model={}", model)
                for metric in bucket:
                    scores[str(metric.id)] = jev_error_score(metric, str(exc))
                continue

            answers = payload.get("answers") if isinstance(payload, dict) else None
            if not isinstance(answers, dict):
                for metric in bucket:
                    scores[str(metric.id)] = jev_error_score(
                        metric, "Jev response missing answers map."
                    )
                continue

            for metric in bucket:
                metric_answers = {
                    key: answers.get(key) for key in build_jev_questions(metric)
                }
                if all(item is None for item in metric_answers.values()) and answers.get(
                    str(metric.id)
                ) is not None:
                    metric_answers = {str(metric.id): answers.get(str(metric.id))}
                if all(item is None for item in metric_answers.values()):
                    scores[str(metric.id)] = jev_error_score(
                        metric, "Jev response missing this metric's answer."
                    )
                    continue
                scores[str(metric.id)] = map_jev_answers(metric, metric_answers)
            continue

        for metric in bucket:
            metric_answers: dict[str, Any] = {}
            for key, question in build_jev_questions(metric).items():
                try:
                    metric_answers[key] = _evaluate_via_chat(
                        question,
                        state=state,
                        provider=provider,
                        model=model,
                        organization_id=organization_id,
                        db=db,
                        credential_id=credential_id or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "Jev chat evaluation failed for provider={} model={} key={}",
                        provider,
                        model,
                        key,
                    )
                    metric_answers[key] = {
                        "type": question.get("type"),
                        "error": str(exc),
                    }
            scores[str(metric.id)] = map_jev_answers(metric, metric_answers)

    return scores
