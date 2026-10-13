"""Prompt improvements compose base must not double-apply after save."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.call_import_prompt_push import (
    compose_accepted_prompt,
    mark_prompt_improvements_applied,
    preview_evaluation_push,
)
from unittest.mock import MagicMock


def test_mark_applied_prevents_double_compose(monkeypatch):
    base = "Line one"
    suggestions = [
        {
            "id": "1",
            "review_status": "accepted",
            "change_type": "add",
            "suggested_text": "Extra rule",
        }
    ]
    once = compose_accepted_prompt(base, suggestions)
    evaluation = SimpleNamespace(
        prompt_improvements={
            "compose_base_prompt": base,
            "suggestions": [dict(s) for s in suggestions],
        }
    )
    mark_prompt_improvements_applied(evaluation, once)
    again = compose_accepted_prompt(once, evaluation.prompt_improvements["suggestions"])
    assert again == once


def test_preview_uses_frozen_compose_base(monkeypatch):
    org_id = uuid4()
    ws_id = uuid4()
    partial_id = uuid4()
    partial = SimpleNamespace(
        id=partial_id,
        content="already saved composed text",
        name="Agent",
        current_version=2,
    )
    evaluation = SimpleNamespace(
        prompt_improvements={
            "imported_agent_id": str(partial_id),
            "compose_base_prompt": "original base",
            "suggestions": [
                {
                    "id": "1",
                    "review_status": "accepted",
                    "change_type": "add",
                    "suggested_text": "Addendum",
                }
            ],
        }
    )
    call_import = SimpleNamespace(
        source_format="platform",
        voice_integration_id=uuid4(),
        platform_filters={"agent_ids": ["a1"], "agents": [{"id": "a1", "name": "A"}]},
        content_modality=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = partial
    monkeypatch.setattr(
        "app.services.call_import_prompt_push.fetch_provider_prompt",
        lambda *_a, **_k: "original base",
    )
    monkeypatch.setattr(
        "app.services.call_import_prompt_push._load_integration",
        lambda *_a, **_k: SimpleNamespace(
            id=uuid4(),
            platform=SimpleNamespace(value="elevenlabs"),
        ),
    )
    preview = preview_evaluation_push(db, evaluation, call_import, org_id, ws_id)
    assert preview["base_prompt"] == "original base"
    assert "Addendum" in preview["composed_prompt"]
    assert preview["composed_prompt"] != partial.content
