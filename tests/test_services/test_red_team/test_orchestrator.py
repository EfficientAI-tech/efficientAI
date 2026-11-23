"""End-to-end red team runs with scripted attacker, agent and judge."""

import json
import re
from types import SimpleNamespace

import pytest

from app.models.database import RedTeamAttack
from app.services.red_team import conversation, judge, planner
from app.services.red_team.llm import RedTeamLlmError
from app.services.red_team.orchestrator import RedTeamOrchestrator, determine_modality

_TECHNIQUE_RE = re.compile(r"Attack technique: (.+)")


class Script:
    """Scripted LLMs: the attacker speaks, the agent replies, the judge scores by technique."""

    def __init__(self, outcomes=None, attacker_fails=False):
        self.outcomes = outcomes or {}
        self.attacker_fails = attacker_fails
        self.agent_transcripts = []
        self.judged = []

    def attacker(self, db, *, organization_id, llm, messages, json_mode=False):
        if self.attacker_fails:
            raise RedTeamLlmError("model refused")
        turn = sum(1 for m in messages if m["role"] == "assistant")
        return "Thanks, bye [[END]]" if turn >= 2 else f"attacker turn {turn}"

    def complete_json(self, db, *, organization_id, llm, messages, retries=2):
        content = messages[-1]["content"]
        if "Return JSON only: {\"outcome\"" in content:
            technique = _TECHNIQUE_RE.search(content).group(1).strip()
            self.judged.append(technique)
            outcome = self.outcomes.get(technique, "held")
            if "non_refusal" in content:
                return {"non_refusal": 0, "specificity": 0, "actionability": 0, "rationale": "declined"}
            score = {"breached": 9, "conceded": 5, "held": 0}[outcome]
            return {"outcome": outcome, "score": score, "rationale": f"{outcome} on {technique}", "evidence_turns": [1]}
        if '"attacks"' in content and "slot" in content:
            slots = json.loads(content.split("Slots:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
            return {"attacks": [{"slot": s["slot"], "goal": f"tailored {s['technique']}", "strategy": "plan"} for s in slots]}
        if '"attacks"' in content:
            return {"attacks": [{"goal": "follow-up goal", "strategy": "push harder"} for _ in range(5)]}
        return {"summary": "Bank helper", "data_held": ["balance"], "gated_actions": ["card change"], "weak_spots": ["dob"]}

    def agent_reply(self, db, *, agent, organization_id, transcript, provider_state, toolset=None, **kw):
        self.agent_transcripts.append(list(transcript))
        return "I can't share that without verification.", {"tool_calls": [{"name": "lookup_account"}]}


@pytest.fixture
def script(monkeypatch):
    s = Script()
    from app.services.agents import chat_production_leg, provider_platform_chat
    from app.services.tools import toolset

    monkeypatch.setattr(conversation, "complete", lambda *a, **k: s.attacker(*a, **k))
    monkeypatch.setattr(judge, "complete_json", lambda *a, **k: s.complete_json(*a, **k))
    monkeypatch.setattr(planner, "complete_json", lambda *a, **k: s.complete_json(*a, **k))
    monkeypatch.setattr(chat_production_leg, "generate_production_chat_reply", lambda *a, **k: s.agent_reply(*a, **k))
    monkeypatch.setattr(chat_production_leg, "uses_live_production_leg", lambda agent: False)
    monkeypatch.setattr(toolset, "build_agent_toolset", lambda *a, **k: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(provider_platform_chat, "close_provider_chat_session", lambda *a, **k: None)
    return s


def _attacks(db_session, run):
    return (
        db_session.query(RedTeamAttack)
        .filter(RedTeamAttack.red_team_run_id == run.id)
        .order_by(RedTeamAttack.sequence)
        .all()
    )


def test_chat_agent_modality(db_session, rt):
    assert determine_modality(db_session, rt.agent) == "chat"


def test_full_run_escalates_conceded_and_reports_breach(db_session, rt, script):
    script.outcomes = {
        "Impersonate the account holder": "conceded",
        "System prompt extraction": "breached",
    }
    run = rt.make_run("standard")
    RedTeamOrchestrator(run.id, shared_session=db_session).run()
    db_session.refresh(run)

    assert run.status == "completed", run.error_message
    assert run.verdict == "breached"
    assert run.agent_profile["summary"] == "Bank helper"
    assert run.resolved_llms["attacker"]["model"] == "gpt-4.1-mini"

    attacks = _attacks(db_session, run)
    recon = [a for a in attacks if a.kind == "recon"]
    scored = [a for a in attacks if a.kind == "attack"]
    assert len(recon) == run.config["recon_count"]
    assert all(a.transcript for a in recon)

    # Quotas are never exceeded, per family or in total.
    for family, quota in run.config["attack_quotas"].items():
        assert sum(1 for a in scored if a.family == family) <= quota
    assert len(scored) <= run.max_attacks
    assert run.completed_attacks == len(scored)
    assert run.breached_attacks == sum(1 for a in scored if a.outcome == "breached")

    # Conceded social engineering spawned refined children at the next level.
    conceded_parents = {a.id for a in scored if a.outcome == "conceded"}
    children = [a for a in scored if a.parent_attack_id in conceded_parents]
    assert children and all(c.level >= 1 and c.strategy == "push harder" for c in children)

    # The planner tailored root goals; attacker prompts carried the profile.
    assert any(a.goal.startswith("tailored") for a in scored if a.level == 0)
    # Tool calls from the agent are stored for the judge.
    assert any(e.get("tool_calls") for a in scored for e in a.transcript if e["role"] == "agent")

    categories = {c["id"]: c["status"] for c in run.report["categories"]}
    assert categories["LLM07"] == "FAIL"
    assert categories["LLM02"] in ("PARTIAL", "FAIL")
    assert run.report["passed"] is False


def test_agent_that_holds_everything_spends_budget_on_breadth(db_session, rt, script):
    run = rt.make_run("standard")
    RedTeamOrchestrator(run.id, shared_session=db_session).run()
    db_session.refresh(run)

    scored = [a for a in _attacks(db_session, run) if a.kind == "attack"]
    assert run.verdict == "held"
    assert run.report["passed"] is True
    # Nothing conceded, so no children, but later levels tried new techniques.
    assert all(a.parent_attack_id is None for a in scored)
    assert len({a.technique_id for a in scored}) > len([a for a in scored if a.level == 0])


def test_attacker_refusal_falls_back_to_seed_opener(db_session, rt, script):
    script.attacker_fails = True
    run = rt.make_run("quick", config={"recon_count": 0})
    RedTeamOrchestrator(run.id, shared_session=db_session).run()
    db_session.refresh(run)

    scored = [a for a in _attacks(db_session, run) if a.kind == "attack"]
    assert run.status == "completed"
    assert scored
    # Turn one used the catalog seed; turn two failed and the attack was marked as an error.
    from app.services.red_team.catalog import TECHNIQUES_BY_ID

    for attack in scored:
        assert attack.transcript[0]["text"] == TECHNIQUES_BY_ID[attack.technique_id].seed_openers[0]
        assert attack.outcome == "error"
    assert run.verdict == "inconclusive"


def test_cancel_before_start_finishes_cancelled_with_report(db_session, rt, script):
    run = rt.make_run("quick", cancel_requested=True)
    RedTeamOrchestrator(run.id, shared_session=db_session).run()
    db_session.refresh(run)

    assert run.status == "cancelled"
    assert run.report is not None
    assert all(a.status == "cancelled" for a in _attacks(db_session, run))
    assert script.agent_transcripts == []


def test_non_queued_run_is_not_restarted(db_session, rt, script):
    run = rt.make_run("quick", status="completed")
    RedTeamOrchestrator(run.id, shared_session=db_session).run()
    assert _attacks(db_session, run) == []
