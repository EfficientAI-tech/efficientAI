"""Recover deleted import-linked partials for evaluation prompt push."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.call_import_prompt_push import resolve_imported_partial_for_evaluation


def test_resolve_relinks_when_stored_partial_missing(monkeypatch):
    org_id = uuid4()
    ws_id = uuid4()
    stale_id = uuid4()
    new_id = uuid4()
    new_partial = SimpleNamespace(id=new_id, name="Agent · Import batch")
    evaluation = SimpleNamespace(
        prompt_improvements={
            "imported_agent_id": str(stale_id),
            "imported_agent_name": "Old",
        }
    )
    call_import = SimpleNamespace(id=uuid4())

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    monkeypatch.setattr(
        "app.services.platform_import_imported_agent.resolve_imported_agent_for_call_import",
        lambda *_args, **_kwargs: new_partial,
    )

    partial, relinked = resolve_imported_partial_for_evaluation(
        db, evaluation, org_id, ws_id, call_import
    )

    assert relinked is True
    assert partial.id == new_id
    assert evaluation.prompt_improvements["imported_agent_id"] == str(new_id)
    assert evaluation.prompt_improvements["imported_agent_name"] == "Agent · Import batch"
