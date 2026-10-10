"""Generate evaluation metric drafts from scenario definitions and agent prompts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import Metric
from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service
from app.services.metrics.surfaces import ALLOWED_METRIC_SURFACES
from app.services.testing.scenario_generation_modality import scenario_modality_from_call_medium


@dataclass
class ScenarioMetricInput:
    name: str
    description: str
    goal: Optional[str] = None
    # When set to boolean|rating|number|text, the generated metric must use that type.
    metric_type: Optional[str] = None


@dataclass
class ScenarioMetricDraft:
    name: str
    description: str
    metric_type: str
    custom_data_type: Optional[str]
    custom_config: Dict[str, Any]
    supported_surfaces: List[str]
    enabled_surfaces: List[str]
    tags: List[str]
    scenario_name: str


@dataclass
class ScenarioMetricGenerationResult:
    metrics: List[ScenarioMetricDraft]
    provider: str
    model: str


def evaluation_surface_for_call_medium(call_medium: Optional[str]) -> str:
    return "chat_agent" if scenario_modality_from_call_medium(call_medium) == "chat" else "agent"


def _extract_json_array(text: str) -> List[Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON array")
    return json.loads(cleaned[start : end + 1])


def _build_messages(
    *,
    agent_name: str,
    production_prompt: str,
    surface: str,
    scenarios: Sequence[ScenarioMetricInput],
) -> List[Dict[str, str]]:
    scenario_blocks = []
    for index, scenario in enumerate(scenarios, start=1):
        parts = [
            f"Scenario {index}: {scenario.name}",
            f"Description:\n{scenario.description.strip()}",
        ]
        if scenario.goal:
            parts.append(f"Goal: {scenario.goal.strip()}")
        requested_type = (scenario.metric_type or "").strip().lower()
        if requested_type in {"boolean", "rating", "number", "text"}:
            parts.append(
                f'Requested metric type: {requested_type} '
                f'(you MUST set "metric_type" to "{requested_type}")'
            )
        else:
            parts.append(
                "Requested metric type: auto (choose the best structured type for this scenario)"
            )
        scenario_blocks.append("\n".join(parts))

    schema_block = f"""
You MUST respond with ONLY a JSON array (no markdown, no commentary) with exactly {len(scenarios)} objects, in the same order as the scenarios below. Each object:
{{
  "name": str (concise, Title Case, <= 60 chars),
  "description": str (1-3 sentences: LLM-judge rubric for whether the agent handled THIS scenario per the production prompt),
  "metric_type": "rating" | "boolean" | "number" | "text",
  "custom_data_type": "boolean" | "enum" | "number_range" | null,
  "custom_config": {{}},
  "supported_surfaces": ["{surface}"],
  "enabled_surfaces": ["{surface}"]
}}

Rules:
  - Prefer structured types (boolean, rating/enum, number) over free text.
  - metric_type must align with custom_data_type (boolean/boolean, rating/enum, number/number_range).
  - Each metric must be specific to its scenario's success criteria and edge cases.
  - Do not reuse identical names across scenarios.
"""

    system_message = (
        "You are an expert evaluation designer. For each test scenario, define one "
        "LLM-as-judge metric that scores whether an agent conversation satisfied that "
        "scenario given the agent's production system prompt. Always respond with valid JSON only."
    )

    user_message = (
        f"Agent Name: {agent_name}\n"
        f"Evaluation surface: {surface}\n\n"
        f"Production system prompt:\n{production_prompt.strip()}\n\n"
        f"Scenarios:\n\n"
        + "\n\n---\n\n".join(scenario_blocks)
        + schema_block
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def normalize_generated_metric_fields(
    parsed: Dict[str, Any],
    *,
    surface: str,
    forced_metric_type: Optional[str] = None,
) -> Dict[str, Any]:
    allowed_surfaces = set(ALLOWED_METRIC_SURFACES)
    supported = [s for s in (parsed.get("supported_surfaces") or []) if s in allowed_surfaces]
    if surface not in supported:
        supported = list({*supported, surface})
    enabled_surfaces = [s for s in (parsed.get("enabled_surfaces") or supported) if s in supported]
    if not enabled_surfaces:
        enabled_surfaces = list(supported)

    forced = (forced_metric_type or "").strip().lower()
    if forced in {"rating", "boolean", "number", "text"}:
        metric_type = forced
    else:
        metric_type = (parsed.get("metric_type") or "rating").lower()
        if metric_type not in {"rating", "boolean", "number", "text"}:
            metric_type = "rating"

    custom_data_type = parsed.get("custom_data_type")
    if custom_data_type not in {"boolean", "enum", "number_range", None}:
        custom_data_type = None

    if metric_type == "text":
        custom_data_type = None
        custom_config: Dict[str, Any] = {}
    else:
        if custom_data_type is None:
            custom_data_type = (
                "boolean"
                if metric_type == "boolean"
                else "number_range"
                if metric_type == "number"
                else "enum"
            )
        custom_config = parsed.get("custom_config") or {}
        if custom_data_type == "enum" and not isinstance(custom_config.get("options"), list):
            custom_config = {"options": ["Excellent", "Good", "Neutral", "Poor"]}
        if custom_data_type == "number_range":
            custom_config = {
                "min": float(custom_config.get("min", 0)),
                "max": float(custom_config.get("max", 10)),
                "step": float(custom_config.get("step", 1)),
            }
        if custom_data_type == "boolean":
            custom_config = {}

    name = (parsed.get("name") or "Scenario Metric").strip()[:60]
    description = (parsed.get("description") or "").strip()[:1000]

    return {
        "name": name,
        "description": description,
        "metric_type": metric_type,
        "custom_data_type": custom_data_type,
        "custom_config": custom_config,
        "supported_surfaces": supported,
        "enabled_surfaces": enabled_surfaces,
    }


def _dedupe_metric_name(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    name: str,
) -> str:
    workspace_filter = Metric.workspace_id == workspace_id
    existing = (
        db.query(Metric)
        .filter(
            Metric.name == name,
            Metric.organization_id == organization_id,
            workspace_filter,
            Metric.parent_metric_id.is_(None),
        )
        .first()
    )
    if not existing:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"[:60]
        collision = (
            db.query(Metric)
            .filter(
                Metric.name == candidate,
                Metric.organization_id == organization_id,
                workspace_filter,
                Metric.parent_metric_id.is_(None),
            )
            .first()
        )
        if not collision:
            return candidate
        suffix += 1


def _build_tags(agent_name: str, extra: Optional[List[str]] = None) -> List[str]:
    reserved = {agent_name.strip(), "auto-generated"}
    tags: List[str] = []
    for value in [agent_name.strip(), "auto-generated"]:
        if value and value not in tags:
            tags.append(value)
    for item in extra or []:
        text = str(item).strip()
        if text and text not in reserved and text not in tags:
            tags.append(text)
    return tags[:12]


def generate_metrics_from_scenarios(
    *,
    agent_name: str,
    production_prompt: str,
    call_medium: Optional[str],
    scenarios: Sequence[ScenarioMetricInput],
    organization_id: UUID,
    workspace_id: UUID,
    db: Session,
    llm_provider: ModelProvider,
    llm_model: str,
    llm_config: Optional[Dict[str, Any]] = None,
    credential_id: Optional[UUID] = None,
) -> ScenarioMetricGenerationResult:
    if not production_prompt.strip():
        raise ValueError("Production prompt is required")
    if not scenarios:
        raise ValueError("At least one scenario is required")
    if len(scenarios) > 10:
        raise ValueError("At most 10 scenarios per request")

    surface = evaluation_surface_for_call_medium(call_medium)
    messages = _build_messages(
        agent_name=agent_name,
        production_prompt=production_prompt,
        surface=surface,
        scenarios=scenarios,
    )

    result = llm_service.generate_response(
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        llm_config=llm_config,
        task_defaults={"temperature": 0.4, "max_tokens": 8000},
        credential_id=credential_id,
    )

    try:
        raw = _extract_json_array(result["text"])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[ScenarioMetrics] Failed to parse metric JSON array: {exc}")
        raise ValueError("Could not parse generated metrics from LLM response") from exc

    if not isinstance(raw, list) or len(raw) < len(scenarios):
        raise ValueError("LLM response did not contain enough metric definitions")

    drafts: List[ScenarioMetricDraft] = []
    for index, scenario in enumerate(scenarios):
        item = raw[index]
        if not isinstance(item, dict):
            raise ValueError(f"Metric at index {index} is not an object")
        forced_type = (scenario.metric_type or "").strip().lower()
        if forced_type == "auto":
            forced_type = ""
        normalized = normalize_generated_metric_fields(
            item,
            surface=surface,
            forced_metric_type=forced_type or None,
        )
        name = _dedupe_metric_name(
            db, organization_id, workspace_id, normalized["name"]
        )
        drafts.append(
            ScenarioMetricDraft(
                name=name,
                description=normalized["description"],
                metric_type=normalized["metric_type"],
                custom_data_type=normalized["custom_data_type"],
                custom_config=normalized["custom_config"],
                supported_surfaces=normalized["supported_surfaces"],
                enabled_surfaces=normalized["enabled_surfaces"],
                tags=_build_tags(agent_name, item.get("suggested_tags")),
                scenario_name=scenario.name,
            )
        )

    return ScenarioMetricGenerationResult(
        metrics=drafts,
        provider=llm_provider.value,
        model=llm_model,
    )
