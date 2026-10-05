"""Voice vs text chat wording for generated scenario descriptions."""

from __future__ import annotations

from typing import Literal, Optional

ScenarioModality = Literal["voice", "chat"]

VOICE_SCENARIO_SECTIONS: tuple[str, ...] = (
    "### Background (2-3 sentences)",
    "### Caller intent (1-2 sentences)",
    "### Conversation flow (4-6 numbered steps)",
    "### Success criteria (2-4 bullet points)",
    "### Edge cases to probe (2-3 bullet points)",
)

CHAT_SCENARIO_SECTIONS: tuple[str, ...] = (
    "### Background (2-3 sentences)",
    "### Customer intent (1-2 sentences)",
    "### Conversation flow (4-6 numbered steps)",
    "### Success criteria (2-4 bullet points)",
    "### Edge cases to probe (2-3 bullet points)",
)


def scenario_modality_from_call_medium(call_medium: Optional[str]) -> ScenarioModality:
    if (call_medium or "").lower() == "chat":
        return "chat"
    return "voice"


def scenario_description_sections(modality: ScenarioModality) -> tuple[str, ...]:
    return CHAT_SCENARIO_SECTIONS if modality == "chat" else VOICE_SCENARIO_SECTIONS


def generate_scenarios_system_prompt(modality: ScenarioModality) -> str:
    if modality == "chat":
        return (
            "You generate high-quality test scenarios for text chat AI agents (messaging UI, not phone calls). "
            "Use customer/user language only — never caller, phone call, dial, or hang up. "
            "Return ONLY valid JSON array with objects: "
            '{ "name": string, "description": string, "goal": string }.'
        )
    return (
        "You generate high-quality test scenarios for voice AI agents (phone or web voice). "
        "Return ONLY valid JSON array with objects: "
        '{ "name": string, "description": string, "goal": string }.'
    )


def build_scenario_generation_requirements(modality: ScenarioModality) -> str:
    sections = scenario_description_sections(modality)
    lines = [
        "Requirements:",
        "- Each scenario must test a different user intent or edge case.",
        "- Keep each name short (under 80 characters).",
        "- Each description must be 150-300 words.",
        "- Each description MUST include all of these markdown sections:",
    ]
    lines.extend(f"  - {section}" for section in sections)
    if modality == "chat":
        lines.extend(
            [
                "- Descriptions are for TEXT CHAT: write about messages, typing, and chat threads.",
                "- Refer to the human side as the customer or user, not caller.",
                "- Refer to ending the interaction as closing the chat or conversation, not hanging up.",
                "- Include a concise goal string summarizing what the customer should achieve in chat.",
            ]
        )
    else:
        lines.extend(
            [
                "- Descriptions should reflect a spoken phone or web voice conversation.",
                "- Include a concise goal string summarizing what the caller should achieve.",
            ]
        )
    lines.extend(
        [
            "- Descriptions should be specific, test-oriented, and suitable for QA evaluation.",
            "- Return only JSON array, no markdown wrapper, no explanation.",
        ]
    )
    return "\n".join(lines)


def scenario_edit_generation_system_prompt(modality: ScenarioModality) -> str:
    channel = "text chat" if modality == "chat" else "voice"
    return (
        f"You write detailed, structured scenario descriptions for QA test scenarios ({channel}). "
        "Use the required markdown sections and aim for 150-300 words unless the user request specifies otherwise."
    )
