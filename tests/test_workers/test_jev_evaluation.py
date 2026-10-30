"""Unit tests for Jev state building, question mapping, and the TypeSafe client."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.ai import jev_client
from app.workers.tasks.helpers import jev_evaluation


def _metric(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Urgency",
        "description": "Does this convey urgency?",
        "custom_data_type": "jev",
        "custom_config": {
            "jev_type": "noul",
            "state_source": "both",
            "criteria": {"true": "Time-sensitive", "false": "No rush"},
        },
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_build_state_filters_user_and_agent_turns():
    transcript = (
        "User: Help, my payout failed.\n"
        "Agent: I can look that up.\n"
        "Narrator: hold music\n"
    )
    both = jev_evaluation.build_state(transcript, "both")
    assert both == [
        {"speaker": "user", "text": "Help, my payout failed."},
        {"speaker": "agent", "text": "I can look that up."},
    ]
    assert jev_evaluation.build_state(transcript, "user") == [
        {"speaker": "user", "text": "Help, my payout failed."}
    ]
    assert jev_evaluation.build_state(transcript, "agent") == [
        {"speaker": "agent", "text": "I can look that up."}
    ]


def test_build_jev_question_adds_other_option():
    metric = _metric(
        custom_config={
            "jev_type": "choice",
            "state_source": "both",
            "include_other": True,
            "criteria": {"billing": "money"},
            "confidence_threshold": 0.7,
        }
    )
    question = jev_evaluation.build_jev_question(metric)
    assert question["type"] == "choice"
    assert question["criteria"]["billing"] == "money"
    assert question["criteria"]["other"] == "None of the listed options fit"


def test_map_jev_answer_flags_low_choice_confidence():
    metric = _metric(
        custom_config={
            "jev_type": "choice",
            "state_source": "both",
            "criteria": {"billing": "money"},
            "confidence_threshold": 0.7,
        }
    )
    low = jev_evaluation.map_jev_answer(
        metric,
        {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.51,
            "probabilities": {"billing": 0.58, "other": 0.42},
        },
    )
    assert low["value"] == "billing"
    assert low["needs_review"] is True
    high = jev_evaluation.map_jev_answer(
        metric,
        {"type": "choice", "choice": "billing", "confidence": 0.7},
    )
    assert high["needs_review"] is False


def test_map_jev_answer_noul_never_needs_review():
    metric = _metric()
    mapped = jev_evaluation.map_jev_answer(metric, {"type": "noul", "noul": 0.4})
    assert mapped["value"] is False
    assert mapped["questions"]["noul"]["noul"] == 0.4
    assert mapped["needs_review"] is False


def test_is_jev_metric_accepts_tag_fallback():
    tagged = _metric(custom_data_type="number", tags=["jev"])
    assert jev_evaluation.is_jev_metric(tagged)
    assert not jev_evaluation.is_jev_metric(_metric(custom_data_type="number", tags=[]))


def test_map_jev_answer_missing_choice_confidence_does_not_review():
    metric = _metric(
        custom_config={
            "jev_type": "choice",
            "state_source": "both",
            "criteria": {"billing": "money"},
            "confidence_threshold": 0.7,
        }
    )
    mapped = jev_evaluation.map_jev_answer(
        metric, {"type": "choice", "choice": "billing"}
    )
    assert mapped["needs_review"] is False
    assert mapped.get("review_reason") != "missing_confidence"


def test_snapshot_jev_metric_copies_config():
    metric = _metric()
    snap = jev_evaluation.snapshot_jev_metric(metric)
    assert snap.id == metric.id
    assert snap.custom_config["jev_type"] == "noul"
    assert jev_evaluation.is_jev_metric(snap)


def test_evaluate_with_jev_missing_model_returns_error():
    metric = _metric()
    scores = jev_evaluation.evaluate_with_jev(
        [metric],
        "User: hi",
        organization_id=uuid4(),
        db=MagicMock(),
        overrides={},
        run_provider="openai",
        run_model="gpt-4o",
    )
    entry = scores[str(metric.id)]
    assert entry["error"] == jev_evaluation.JEV_MISSING_MODEL_ERROR
    assert entry["value"] is None


def test_evaluate_with_jev_maps_answers(monkeypatch):
    metric = _metric()
    monkeypatch.setattr(jev_evaluation, "is_jev_model", lambda *_a, **_k: True)
    monkeypatch.setattr(jev_evaluation, "_resolve_api_key", lambda **_k: "key")
    monkeypatch.setattr(
        jev_evaluation,
        "decide",
        lambda **_k: {
            "answers": {f"{metric.id}:noul": {"type": "noul", "noul": 0.91}}
        },
    )
    scores = jev_evaluation.evaluate_with_jev(
        [metric],
        "User: Help now\nAgent: On it",
        organization_id=uuid4(),
        db=MagicMock(),
        overrides={str(metric.id): {"provider": "typesafe", "model": "jev-latest"}},
    )
    assert scores[str(metric.id)]["value"] is True
    assert scores[str(metric.id)]["questions"]["noul"]["noul"] == 0.91


def test_jev_client_retries_on_429(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    def fake_post(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(429)
        return FakeResponse(
            200,
            {"answers": {"q": {"type": "noul", "noul": 1.0}}},
        )

    monkeypatch.setattr(jev_client.requests, "post", fake_post)
    monkeypatch.setattr(jev_client.time, "sleep", lambda _s: None)
    data = jev_client.decide(
        state="hello",
        questions={"q": {"type": "noul", "instructions": "yes?"}},
        model="jev-latest",
        api_key="k",
    )
    assert calls["n"] == 3
    assert data["answers"]["q"]["noul"] == 1.0


def test_jev_client_raises_on_401(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "nope"

        def json(self):
            return {"error": "bad key"}

    monkeypatch.setattr(
        jev_client.requests, "post", lambda *_a, **_k: FakeResponse()
    )
    with pytest.raises(jev_client.JevClientError, match="401"):
        jev_client.decide(
            state="hello",
            questions={"q": {"type": "noul", "instructions": "yes?"}},
            model="jev-latest",
            api_key="k",
        )


def test_parse_jev_chat_answer_noul_english():
    question = {
        "type": "noul",
        "instructions": "Urgent?",
        "criteria": {"true": "hurry", "false": "calm"},
    }
    answer = jev_evaluation.parse_jev_chat_answer(question, "noul: 0.82")
    assert answer["noul"] == 0.82
    assert answer["source"] == "chat"


def test_parse_jev_chat_answer_noul_bare_probability():
    question = {
        "type": "noul",
        "instructions": "Urgent?",
        "criteria": {"true": "hurry", "false": "calm"},
    }
    answer = jev_evaluation.parse_jev_chat_answer(question, "0.1")
    assert answer["noul"] == 0.1


def test_parse_jev_chat_answer_choice_bare_option_and_numbers():
    question = {
        "type": "choice",
        "instructions": "topic",
        "criteria": {"billing": "money", "other": "none"},
    }
    answer = jev_evaluation.parse_jev_chat_answer(question, "other 0.95 0")
    assert answer["choice"] == "other"
    assert answer["confidence"] == 0.95
    assert answer["probabilities"]["other"] == 0.95


def test_parse_jev_chat_answer_choice_probability_lines():
    question = {
        "type": "choice",
        "instructions": "topic",
        "criteria": {
            "Issue in the product": "product defect",
            "other": "none",
        },
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        "Issue in the product 0.81\nother 0.19",
    )
    assert answer["choice"] == "Issue in the product"
    assert answer["probabilities"]["Issue in the product"] == 0.81
    assert answer["probabilities"]["other"] == 0.19
    assert answer["confidence"] == 0.81


def test_parse_jev_chat_answer_score_probability_lines():
    question = {
        "type": "score",
        "instructions": "mood",
        "criteria": ["frustrated", "neutral", "satisfied"],
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        "0 0.05\n1 0.15\n2 0.80",
    )
    assert answer["score"] == 2
    assert answer["probabilities"]["0"] == 0.05
    assert answer["probabilities"]["1"] == 0.15
    assert answer["probabilities"]["2"] == 0.80
    assert answer["confidence"] == 0.80


def test_parse_jev_chat_answer_ignores_empty_json_probabilities():
    question = {
        "type": "choice",
        "instructions": "topic",
        "criteria": {
            "Issue in the product": "product defect",
            "other": "none",
        },
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        '{"type": "choice", "choice": "Issue in the product", "probabilities": {}, "confidence": null}',
    )
    assert answer["choice"] == "Issue in the product"
    assert not answer.get("probabilities")


def test_map_score_index_two_is_not_percent():
    metric = _metric(
        custom_config={
            "jev_type": "score",
            "state_source": "both",
            "criteria": [
                "Customer seems frustrated",
                "customer seems neutral",
                "customer seems satisfied",
            ],
            "confidence_threshold": 0.7,
        }
    )
    mapped = jev_evaluation.map_jev_answer(
        metric,
        {
            "type": "score",
            "score": "2",
            "value": "Customer seems frustrated",
            "probabilities": {},
            "confidence": None,
            "legend": {
                "0": "Customer seems frustrated",
                "1": "customer seems neutral",
                "2": "customer seems satisfied",
            },
        },
    )
    assert mapped["value"] == "customer seems satisfied"
    assert "probabilities" not in mapped["questions"]["score"]


def test_parse_jev_chat_answer_choice_probability_lines():
    question = {
        "type": "choice",
        "instructions": "topic",
        "criteria": {
            "Issue in the product": "product defect",
            "other": "none",
        },
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        "Issue in the product 0.81\nother 0.19",
    )
    assert answer["choice"] == "Issue in the product"
    assert answer["probabilities"]["Issue in the product"] == 0.81
    assert answer["probabilities"]["other"] == 0.19
    assert answer["confidence"] == 0.81


def test_parse_jev_chat_answer_score_probability_lines():
    question = {
        "type": "score",
        "instructions": "mood",
        "criteria": ["frustrated", "neutral", "satisfied"],
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        "0 0.05\n1 0.15\n2 0.80",
    )
    assert answer["score"] == 2
    assert answer["probabilities"]["2"] == 0.80
    assert answer["confidence"] == 0.80


def test_parse_jev_chat_answer_choice_english():
    question = {
        "type": "choice",
        "instructions": "topic",
        "criteria": {"billing": "money", "other": "none"},
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        "choice: billing\nconfidence: 0.61\nbilling: 0.61\nother: 0.39",
    )
    assert answer["choice"] == "billing"
    assert answer["confidence"] == 0.61
    assert answer["probabilities"]["billing"] == 0.61


def test_parse_jev_chat_answer_score_json():
    question = {
        "type": "score",
        "instructions": "quality",
        "criteria": ["poor", "ok", "great"],
    }
    answer = jev_evaluation.parse_jev_chat_answer(
        question,
        '{"type": "score", "score": 2, "confidence": 0.88}',
    )
    assert answer["score"] == 2
    assert answer["confidence"] == 0.88


def test_evaluate_with_jev_together_parses_english(monkeypatch):
    metric = _metric()
    monkeypatch.setattr(
        jev_evaluation,
        "_generate_jev_chat_response",
        lambda **_k: {"text": "noul: 0.77"},
    )
    decide_calls = {"n": 0}

    def boom(**_k):
        decide_calls["n"] += 1
        raise AssertionError("TypeSafe decide should not run for Together")

    monkeypatch.setattr(jev_evaluation, "decide", boom)
    scores = jev_evaluation.evaluate_with_jev(
        [metric],
        "User: Help now\nAgent: On it",
        organization_id=uuid4(),
        db=MagicMock(),
        overrides={
            str(metric.id): {
                "provider": "together",
                "model": "together/Tev1-4B-experimental",
            }
        },
    )
    assert scores[str(metric.id)]["value"] is True
    assert scores[str(metric.id)]["questions"]["noul"]["noul"] == 0.77
    assert decide_calls["n"] == 0


def test_score_winner_level_uses_argmax():
    metric = _metric(
        custom_config={
            "jev_type": "score",
            "state_source": "both",
            "criteria": ["Calm", "Frustrated", "Very angry"],
            "confidence_threshold": 0.7,
        }
    )
    mapped = jev_evaluation.map_jev_answer(
        metric,
        {
            "type": "score",
            "score": 1.05,
            "confidence": 0.92,
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
        },
    )
    assert mapped["value"] == "Frustrated"
    assert mapped["needs_review"] is False


def test_official_jev_value_prefers_resolved():
    assert (
        jev_evaluation.official_jev_value(
            {
                "type": "jev",
                "value": "billing",
                "review": {"resolved": True, "resolved_value": "refund"},
            }
        )
        == "refund"
    )


def test_apply_jev_review_overrides_and_clears_badge():
    score = {
        "type": "jev",
        "jev_type": "choice",
        "value": "billing",
        "needs_review": True,
        "questions": {
            "choice": {"type": "choice", "value": "billing", "needs_review": True}
        },
    }
    updated = jev_evaluation.apply_jev_review(
        score,
        question="choice",
        value="refund",
        resolved_by="owner@example.com",
        resolved_at="2026-09-28T00:00:00+00:00",
    )
    assert updated["needs_review"] is False
    assert updated["value"] == "refund"
    assert updated["questions"]["choice"]["needs_review"] is False
    assert updated["review"]["resolved"] is True
    assert updated["review"]["resolved_value"] == "refund"
    assert updated["review"]["original_value"] == "billing"


def test_together_bundle_uses_one_chat_call_per_question(monkeypatch):
    metric = _metric(
        custom_config={
            "state_source": "both",
            "questions": {
                "noul": {"criteria": {"true": "yes", "false": "no"}},
                "choice": {
                    "criteria": {"billing": "money"},
                    "confidence_threshold": 0.7,
                },
            },
        }
    )
    calls: list[str] = []

    def fake_generate(**kwargs):
        content = kwargs["messages"][0]["content"]
        calls.append(content)
        if "noul:" in content:
            return {"text": "noul: 0.91"}
        return {"text": "choice: billing\nconfidence: 0.8"}

    monkeypatch.setattr(jev_evaluation, "_generate_jev_chat_response", fake_generate)
    scores = jev_evaluation.evaluate_with_jev(
        [metric],
        "User: Help now\nAgent: On it",
        organization_id=uuid4(),
        db=MagicMock(),
        overrides={
            str(metric.id): {
                "provider": "together",
                "model": "together/Tev1-4B-experimental",
            }
        },
    )
    assert len(calls) == 2
    assert "noul:" in calls[0] or "noul:" in calls[1]
    entry = scores[str(metric.id)]
    assert entry["jev_type"] == "bundle"
    assert entry["questions"]["noul"]["value"] is True
    assert entry["questions"]["choice"]["value"] == "billing"


def test_jev_client_retries_on_529(monkeypatch):
    class FakeResponse:
        status_code = 529
        text = "busy"

        def json(self):
            return {}

    monkeypatch.setattr(
        jev_client.requests, "post", lambda *_a, **_k: FakeResponse()
    )
    monkeypatch.setattr(jev_client.time, "sleep", lambda _s: None)
    with pytest.raises(jev_client.JevClientError, match="529"):
        jev_client.decide(
            state="hello",
            questions={"q": {"type": "noul", "instructions": "yes?"}},
            model="jev-latest",
            api_key="k",
            max_attempts=2,
        )


def test_is_jev_model_accepts_catalogued_typesafe():
    assert jev_evaluation.is_jev_model("typesafe", "jev-latest")
    assert jev_evaluation.is_jev_model("typesafe", "jev-1.13.0")
    assert jev_evaluation.is_jev_model("typesafe", "typesafe/jev-1.13.0")
    assert jev_evaluation.is_jev_model("together", "together/Tev1-4B-experimental")
    assert jev_evaluation.is_jev_model("openrouter", "typesafe/jev-latest")
    assert jev_evaluation.is_jev_model("openrouter", "typesafe/jev-1.13.0")
    assert jev_evaluation.is_jev_model(None, "typesafe/jev-1.13.0")
    assert not jev_evaluation.is_jev_model("openai", "gpt-4o")
    assert not jev_evaluation.is_jev_model("together", "zai-org/GLM-4.6")
    assert not jev_evaluation.is_jev_model("typesafe", "")
    assert jev_evaluation.uses_typesafe_systemone("typesafe")
    assert not jev_evaluation.uses_typesafe_systemone("together")
