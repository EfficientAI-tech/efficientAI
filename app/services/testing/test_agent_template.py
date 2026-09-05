"""Structured test agent template: sections, first-message config, and assembly."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

CANONICAL_SECTION_KEYS: tuple[str, ...] = (
    "complementary_goal",
    "talking_style",
    "questions_to_ask",
    "information_to_relay",
    "constraints",
)

CANONICAL_SECTION_TITLES: dict[str, str] = {
    "complementary_goal": "Role and Goal",
    "talking_style": "Talking Style",
    "questions_to_ask": "Questions to Ask",
    "information_to_relay": "Information to Relay",
    "constraints": "Constraints",
}

PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST = "assistant_speaks_first"
PRODUCTION_MODE_ASSISTANT_WAITS = "assistant_waits_for_user"
PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST_MODEL = "assistant_speaks_first_model_generated"

PRODUCTION_MODE_LABELS: dict[str, str] = {
    PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST: "Assistant speaks first",
    PRODUCTION_MODE_ASSISTANT_WAITS: "Assistant waits for user",
    PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST_MODEL: "Assistant speaks first with model-generated message",
}

VALID_PRODUCTION_MODES: frozenset[str] = frozenset(PRODUCTION_MODE_LABELS)

CALLER_MODE_WAIT = "wait"
CALLER_MODE_SPEAK_FIRST = "speak_first"

DEFAULT_CALLER_MESSAGE = "Hello, I'm calling because I need some help."

SPOKEN_IDENTITY_GUARDRAIL = (
    "Never say you are a test agent, AI, bot, simulator, or that you are testing or evaluating anything. "
    "Never mention prompts, scenarios, personas, or automation. Speak only as the named caller."
)


def ensure_opening_includes_persona_name(opening: str, persona_name: str) -> str:
    """Ensure the caller's first spoken line identifies as the persona when missing."""
    text = (opening or "").strip()
    name = (persona_name or "").strip()
    if not name:
        return text
    if text and name.lower() in text.lower():
        return text
    if not text:
        return f"Hello, this is {name} calling."
    return f"Hi, this is {name}. {text}"


@dataclass
class TestAgentPromptSection:
    key: str
    title: str
    content: str


@dataclass
class TestAgentFirstMessage:
    production_mode: str = PRODUCTION_MODE_ASSISTANT_WAITS
    production_message: Optional[str] = None
    caller_mode: str = CALLER_MODE_SPEAK_FIRST
    caller_message: Optional[str] = DEFAULT_CALLER_MESSAGE

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestAgentTemplate:
    sections: List[TestAgentPromptSection]
    first_message: TestAgentFirstMessage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sections": [
                {"key": s.key, "title": s.title, "content": s.content}
                for s in self.sections
            ],
            "first_message": self.first_message.to_dict(),
        }


def default_first_message() -> TestAgentFirstMessage:
    """Legacy default: production waits, caller speaks first (matches Retell/Vapi bridge)."""
    return TestAgentFirstMessage(
        production_mode=PRODUCTION_MODE_ASSISTANT_WAITS,
        production_message=None,
        caller_mode=CALLER_MODE_SPEAK_FIRST,
        caller_message=DEFAULT_CALLER_MESSAGE,
    )


def derive_caller_first_message(production_mode: str, production_message: Optional[str] = None) -> TestAgentFirstMessage:
    """Invert production who-speaks-first into complementary caller behavior."""
    mode = production_mode if production_mode in VALID_PRODUCTION_MODES else PRODUCTION_MODE_ASSISTANT_WAITS
    prod_msg = (production_message or "").strip() or None

    if mode in (PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST, PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST_MODEL):
        return TestAgentFirstMessage(
            production_mode=mode,
            production_message=prod_msg if mode == PRODUCTION_MODE_ASSISTANT_SPEAKS_FIRST else None,
            caller_mode=CALLER_MODE_WAIT,
            caller_message=None,
        )

    return TestAgentFirstMessage(
        production_mode=PRODUCTION_MODE_ASSISTANT_WAITS,
        production_message=None,
        caller_mode=CALLER_MODE_SPEAK_FIRST,
        caller_message=DEFAULT_CALLER_MESSAGE,
    )


def assemble_test_agent_prompt(sections: Sequence[TestAgentPromptSection]) -> str:
    """Deterministically assemble canonical sections into markdown."""
    by_key = {section.key: section for section in sections}
    parts: list[str] = []
    for key in CANONICAL_SECTION_KEYS:
        section = by_key.get(key)
        title = (section.title.strip() if section else "") or CANONICAL_SECTION_TITLES[key]
        content = (section.content.strip() if section and section.content else "") or "Not specified in source prompt."
        parts.append(f"## {title}\n\n{content}")
    return "\n\n".join(parts)


def empty_prompt_sections() -> List[TestAgentPromptSection]:
    return [
        TestAgentPromptSection(key=key, title=CANONICAL_SECTION_TITLES[key], content="")
        for key in CANONICAL_SECTION_KEYS
    ]


def normalize_sections(raw_sections: Any) -> List[TestAgentPromptSection]:
    if not isinstance(raw_sections, list):
        raise ValueError("LLM response sections must be a list")

    by_key: dict[str, TestAgentPromptSection] = {}
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key not in CANONICAL_SECTION_KEYS:
            continue
        title = str(item.get("title") or CANONICAL_SECTION_TITLES[key]).strip()
        content = str(item.get("content") or "").strip()
        by_key[key] = TestAgentPromptSection(key=key, title=title, content=content)

    sections: list[TestAgentPromptSection] = []
    for key in CANONICAL_SECTION_KEYS:
        if key in by_key:
            sections.append(by_key[key])
        else:
            sections.append(
                TestAgentPromptSection(
                    key=key,
                    title=CANONICAL_SECTION_TITLES[key],
                    content="Not specified in source prompt.",
                )
            )
    return sections


def normalize_first_message(raw: Any) -> TestAgentFirstMessage:
    if not isinstance(raw, dict):
        return default_first_message()

    production_mode = str(raw.get("production_mode") or PRODUCTION_MODE_ASSISTANT_WAITS).strip()
    production_message = raw.get("production_message")
    production_message_str = str(production_message).strip() if production_message else None

    derived = derive_caller_first_message(production_mode, production_message_str)

    caller_mode = str(raw.get("caller_mode") or derived.caller_mode).strip()
    if caller_mode not in (CALLER_MODE_WAIT, CALLER_MODE_SPEAK_FIRST):
        caller_mode = derived.caller_mode

    caller_message = raw.get("caller_message")
    caller_message_str = str(caller_message).strip() if caller_message else derived.caller_message

    return TestAgentFirstMessage(
        production_mode=derived.production_mode,
        production_message=derived.production_message,
        caller_mode=caller_mode,
        caller_message=caller_message_str if caller_mode == CALLER_MODE_SPEAK_FIRST else None,
    )


def parse_test_agent_template(raw: Any) -> Optional[TestAgentTemplate]:
    if not isinstance(raw, dict):
        return None
    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list):
        return None
    sections = normalize_sections(sections_raw)
    first_message = normalize_first_message(raw.get("first_message"))
    return TestAgentTemplate(sections=sections, first_message=first_message)


def template_from_generation(
    sections: Sequence[TestAgentPromptSection],
    first_message: TestAgentFirstMessage,
) -> TestAgentTemplate:
    return TestAgentTemplate(sections=list(sections), first_message=first_message)


def resolve_first_message_from_agent(agent: Any) -> TestAgentFirstMessage:
    """Read first-message config from agent row, with legacy default."""
    raw = getattr(agent, "test_agent_template", None)
    parsed = parse_test_agent_template(raw)
    if parsed is not None:
        return parsed.first_message
    return default_first_message()


def resolve_caller_opening_text(
    *,
    first_message: TestAgentFirstMessage,
    persona_name: str,
    scenario_first_message: Optional[str] = None,
) -> Optional[str]:
    """Return caller opening line when caller speaks first; None when caller waits."""
    if first_message.caller_mode == CALLER_MODE_WAIT:
        return None

    name = (persona_name or "Test Caller").strip()
    opening: Optional[str] = None

    if scenario_first_message and str(scenario_first_message).strip():
        opening = str(scenario_first_message).strip()
    elif first_message.caller_message and str(first_message.caller_message).strip():
        opening = str(first_message.caller_message).strip()
    else:
        opening = f"Hello, this is {name} calling."

    return ensure_opening_includes_persona_name(opening, name)


def should_caller_speak_first(first_message: TestAgentFirstMessage) -> bool:
    return first_message.caller_mode == CALLER_MODE_SPEAK_FIRST
