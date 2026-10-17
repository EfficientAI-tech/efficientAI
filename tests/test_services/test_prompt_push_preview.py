"""Preview payload for evaluation prompt push."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.call_import_prompt_push import preview_evaluation_push


def test_preview_fetches_live_prompt_and_blocks_when_saved_mismatch(monkeypatch):
    org_id = uuid4()
    ws_id = uuid4()
    partial_id = uuid4()
    partial = SimpleNamespace(
        id=partial_id,
        content="saved prompt",
        name="Ola Agent",
        current_version=3,
    )
    call_import = SimpleNamespace(
        source_format="platform",
        voice_integration_id=uuid4(),
        platform_filters={"agent_ids": ["agent-1"], "agents": [{"id": "agent-1", "name": "Ola"}]},
        content_modality=None,
    )
    evaluation = SimpleNamespace(
        prompt_improvements={
            "imported_agent_id": str(partial_id),
            "suggestions": [
                {
                    "id": "1",
                    "review_status": "accepted",
                    "change_type": "add",
                    "suggested_text": "New rule",
                }
            ],
        }
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = partial
    monkeypatch.setattr(
        "app.services.call_import_prompt_push.fetch_provider_prompt",
        lambda _integration, _agent_id: "live different",
    )
    monkeypatch.setattr(
        "app.services.call_import_prompt_push._load_integration",
        lambda *_args, **_kwargs: SimpleNamespace(
            id=uuid4(),
            platform=SimpleNamespace(value="elevenlabs"),
        ),
    )

    preview = preview_evaluation_push(db, evaluation, call_import, org_id, ws_id)

    assert preview["live_prompt"] == "live different"
    assert preview["saved_prompt_matches_live"] is False
    assert preview["can_push"] is False
    assert "Saved partial differs" in (preview["block_reason"] or "")
