"""Tool-group selection, docs search, the action-kind catalog and the eval scorer."""

import json

import pytest

from app.services.copilot import registry
from app.services.copilot.actions.base import all_kinds
from app.services.copilot.evals.harness import Transcript, load_cases, score_case, summarize
from app.services.copilot.skills import (
    ALL_GROUPS,
    select_groups,
    tool_names_from_history,
    user_texts_from_history,
)
from app.services.copilot.tools.docs import get_index


class TestSkills:
    def test_keywords_page_and_continuity(self):
        assert select_groups(user_texts=["show my latest call imports"], page_context=None) == {"core", "imports"}
        assert "simulations" in select_groups(user_texts=["why?"], page_context={"entity_type": "simulation_run"})
        assert "setup" in select_groups(user_texts=["ok do it"], page_context=None, recent_tool_groups={"setup"})

    def test_unmatched_message_gets_everything(self):
        assert select_groups(user_texts=["hello"], page_context=None) == set(ALL_GROUPS) | {"core"}

    def test_event_notes_do_not_select_groups(self):
        history = [{"role": "user", "content": "[Update since your last reply: The user confirmed \"Create persona\".]\n\nthanks"}]
        assert user_texts_from_history(history) == ["\n\nthanks"]

    def test_tool_names_from_history(self):
        history = [{"role": "assistant", "content": None,
                    "tool_calls": [{"function": {"name": "list_agents"}}]}]
        assert tool_names_from_history(history) == ["list_agents"]

    def test_every_tool_is_in_a_known_group(self):
        assert {t.group for t in registry.all_tools()} <= set(ALL_GROUPS) | {"core"}


def test_every_action_kind_has_a_capability_and_propose_tool():
    names = {t.name for t in registry.all_tools()}
    proposal_kinds = set()
    for tool in registry.all_tools():
        if tool.side_effect == registry.SIDE_EFFECT_PROPOSE:
            assert tool.name.startswith("propose_")
            proposal_kinds.add(tool.name)
    assert len(proposal_kinds) == len(all_kinds())
    for kind in all_kinds():
        assert kind.capability, f"{kind.kind} must declare a capability"
    assert "open_create_agent_wizard" in names


def test_docs_index_ships_and_finds_answers():
    hits = get_index().search("connect twilio phone number", 3)
    assert hits and "twilio" in hits[0][1]["url"]
    assert all(h[1]["url"].startswith("https://docs.efficientai.cloud/docs") for h in hits)
    assert get_index().search("zzqx unrelated gibberish", 3) == []


class TestEvalScorer:
    def test_cases_file_is_valid(self):
        cases = load_cases()
        assert len(cases) >= 10 and all("expect" in c for c in cases)

    def test_scoring(self):
        case = {
            "id": "c",
            "expect": {
                "tools_called": ["get_evaluation_activity"],
                "tool_args": {"get_evaluation_activity": {"period": "this_week"}},
                "tools_not_called": ["propose_*"],
                "answer_not_contains": ["has been created"],
                "max_tool_calls": 2,
            },
        }
        good = Transcript(tool_calls=[("get_evaluation_activity", {"period": "this_week"})], answer="2 ran.")
        assert score_case(case, good).passed
        bad = Transcript(
            tool_calls=[("get_evaluation_activity", {"period": "today"}), ("propose_create_persona", {}),
                        ("list_agents", {})],
            answer="Persona has been created.",
        )
        failures = score_case(case, bad).failures
        assert len(failures) == 4
        report = summarize([score_case(case, good), score_case(case, bad)])
        assert report["pass_rate"] == 0.5 and report["ran"] == 2
