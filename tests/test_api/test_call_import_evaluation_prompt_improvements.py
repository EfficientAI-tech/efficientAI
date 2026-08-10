"""API tests for evaluation prompt-improvements enqueue and audit stamping."""

from __future__ import annotations

import types

from app.models.database import PromptPartial
from app.services.imported_agent_constants import IMPORTED_AGENT_TAG
from tests.test_api.test_call_import_evaluation_insights import _seed_eval_with_data


def test_post_prompt_improvements_stamps_last_updated_by_email(
    authenticated_client,
    db_session,
    org_id,
    seed_org,
    make_ai_provider,
    monkeypatch,
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    evaluation.metric_clusters = {
        "status": "completed",
        "groups": [],
        "overview": "done",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "generated_at_completed_rows": 1,
    }
    evaluation.last_updated_by_user_id = None
    db_session.flush()

    agent = PromptPartial(
        organization_id=org_id,
        workspace_id=call_import.workspace_id,
        name="Imported agent",
        content="You are a helpful agent.",
        tags=[IMPORTED_AGENT_TAG],
    )
    db_session.add(agent)
    db_session.commit()

    def fake_apply_async(*, kwargs=None, **_kw):
        return types.SimpleNamespace(id="prompt-improvements-task-1")

    monkeypatch.setattr(
        "app.workers.tasks.generate_evaluation_prompt_improvements.generate_evaluation_prompt_improvements_task.apply_async",
        fake_apply_async,
    )

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/prompt-improvements",
        json={
            "imported_agent_id": str(agent.id),
            "regenerate": True,
            "force": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"

    detail = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["last_updated_by_email"] == "owner@example.com"
