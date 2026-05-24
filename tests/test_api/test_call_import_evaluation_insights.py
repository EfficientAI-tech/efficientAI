"""API tests for the LLM-driven TLDR insights endpoint.

Covers ``POST /call-imports/{id}/evaluations/{eval_id}/insights`` and
its companion ``GET`` endpoint. The LLM client is stubbed out so the
tests run without network / API keys; we instead assert that the
provider-and-model resolver is fed the right inputs and that the
cached blob is persisted exactly once per logical generation.
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict, List
from uuid import UUID, uuid4

import pytest

from app.api.v1.routes import call_import_evaluations as routes_module
from app.models.database import (
    AIProvider,
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import (
    CallImportRowStatus,
    CallImportStatus,
    ModelProvider,
)


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _ensure_default_workspace(db_session, org_id) -> Workspace:
    ws = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    if ws is None:
        ws = Workspace(
            organization_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db_session.add(ws)
        db_session.commit()
        db_session.refresh(ws)
    return ws


@pytest.fixture(autouse=True)
def stub_workers():
    """Stub the worker task modules transitively imported by the route."""
    fake_import_module = types.ModuleType("app.workers.tasks.process_call_import_row")

    class _ImportTask:
        @staticmethod
        def delay(*_a, **_kw):
            return types.SimpleNamespace(id="import-task-id")

    fake_import_module.process_call_import_row_task = _ImportTask()

    fake_eval_module = types.ModuleType("app.workers.tasks.evaluate_call_import_row")
    fake_eval_module.evaluate_call_import_row_task = types.SimpleNamespace(
        s=lambda *_a, **_kw: types.SimpleNamespace(args=_a, kwargs=_kw),
    )

    fake_celery = types.ModuleType("celery")
    fake_celery.group = lambda sigs: types.SimpleNamespace(
        apply_async=lambda: types.SimpleNamespace(id="celery-group-id"),
    )

    previous = {
        "app.workers.tasks.process_call_import_row": sys.modules.get(
            "app.workers.tasks.process_call_import_row"
        ),
        "app.workers.tasks.evaluate_call_import_row": sys.modules.get(
            "app.workers.tasks.evaluate_call_import_row"
        ),
        "celery": sys.modules.get("celery"),
    }
    sys.modules["app.workers.tasks.process_call_import_row"] = fake_import_module
    sys.modules["app.workers.tasks.evaluate_call_import_row"] = fake_eval_module
    sys.modules["celery"] = fake_celery
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


class _LlmStub:
    """Tiny stand-in for ``llm_service`` that records every call."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.next_text: str = (
            '{"narrative": "Calls cluster around polite resolutions.", '
            '"patterns": ["Most calls ended with a confirmed action.", '
            '"Hold music played in 32% of escalations."]}'
        )

    def generate_response(self, *, messages, llm_provider, llm_model, **kwargs):
        self.calls.append(
            {
                "messages": messages,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "kwargs": kwargs,
            }
        )
        return {"text": self.next_text}


@pytest.fixture
def llm_stub(monkeypatch):
    stub = _LlmStub()
    fake_module = types.ModuleType("app.services.ai.llm_service")
    fake_module.llm_service = stub
    monkeypatch.setitem(sys.modules, "app.services.ai.llm_service", fake_module)
    return stub


def _seed_eval_with_data(
    db_session,
    org_id,
    *,
    completed_rows: int = 2,
    rationales: List[str] | None = None,
):
    """Seed the smallest CallImport + Evaluation graph the endpoint needs."""
    workspace = _ensure_default_workspace(db_session, org_id)

    integration = TelephonyIntegration(
        id=uuid4(),
        organization_id=org_id,
        provider="exotel",
        auth_id="enc",
        auth_token="enc",
        is_active=True,
        is_default=True,
    )
    db_session.add(integration)
    # Flush the integration before adding the CallImport that references
    # it. SQLAlchemy's dependency sort isn't guaranteed to place this
    # parent before the child when no ORM relationship is declared, and
    # Postgres (CI) enforces the FK immediately even on the same flush
    # - SQLite (local) silently lets it through.
    db_session.flush()

    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Politeness",
        metric_type="rating",
        trigger="always",
        enabled=True,
        supported_surfaces=["agent"],
        enabled_surfaces=["agent"],
    )
    db_session.add(metric)

    call_import = CallImport(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        provider="exotel",
        telephony_integration_id=integration.id,
        original_filename="batch.csv",
        column_mapping={
            "external_call_id": "CallID",
            "transcript": "Transcript",
        },
        extra_columns=[],
        total_rows=2,
        completed_rows=2,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    source_rows = []
    for i in range(2):
        row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=i,
            # ``conversation_id`` is the renamed-from-``external_call_id``
            # canonical column on CallImportRow (kept consistent with the
            # schema-driven upload flow).
            conversation_id=f"ext-{i}",
            transcript=f"transcript {i}",
            raw_columns={"CallID": f"ext-{i}", "Transcript": f"transcript {i}"},
            status=CallImportRowStatus.COMPLETED,
        )
        db_session.add(row)
        source_rows.append(row)

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        name="QA Pass",
        selected_metric_ids=[str(metric.id)],
        status="completed",
        total_rows=2,
        completed_rows=completed_rows,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()

    rationale_pool = rationales or [
        "Agent politely confirmed the next steps and the customer agreed.",
        "Customer thanked the agent before disconnecting cleanly.",
    ]
    for source_row, rationale in zip(source_rows, rationale_pool):
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status="completed",
                metric_scores={
                    str(metric.id): {
                        "metric_name": "Politeness",
                        "type": "rating",
                        "value": 4,
                        "rationale": rationale,
                    }
                },
            )
        )

    db_session.commit()
    db_session.refresh(evaluation)
    return call_import, evaluation, metric


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_persists_summary_and_returns_provider_model(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["narrative"].startswith("Calls cluster around")
    assert len(body["patterns"]) == 2
    assert body["provider"] == "openai"
    assert body["model"]
    assert body["is_stale"] is False
    assert body["generated_at_completed_rows"] == evaluation.completed_rows
    assert len(llm_stub.calls) == 1

    # Cached blob should round-trip on the model.
    refreshed = (
        db_session.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation.id)
        .first()
    )
    assert isinstance(refreshed.tldr_summary, dict)
    assert refreshed.tldr_summary["provider"] == "openai"


def test_repeated_generate_returns_cached_summary_without_llm_call(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    first = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    assert first.status_code == 200

    second = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    assert second.status_code == 200
    assert second.json()["narrative"] == first.json()["narrative"]
    assert len(llm_stub.calls) == 1, "LLM stub should not be re-invoked"


def test_regenerate_true_always_calls_llm(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )

    llm_stub.next_text = (
        '{"narrative": "Updated narrative.", '
        '"patterns": ["Pattern A", "Pattern B"]}'
    )
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={"regenerate": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["narrative"] == "Updated narrative."
    assert len(llm_stub.calls) == 2


def test_explicit_provider_and_model_are_forwarded_to_llm(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    # Two providers seeded so auto-detect would otherwise pick OpenAI.
    make_ai_provider(provider="openai", is_active=True)
    make_ai_provider(provider="anthropic", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
    )
    assert response.status_code == 200, response.text

    assert len(llm_stub.calls) == 1
    call = llm_stub.calls[0]
    assert call["llm_provider"] == ModelProvider.ANTHROPIC
    assert call["llm_model"] == "claude-sonnet-4-20250514"
    assert response.json()["provider"] == "anthropic"
    assert response.json()["model"] == "claude-sonnet-4-20250514"


def test_returns_400_when_no_ai_provider_configured(
    authenticated_client, db_session, org_id, seed_org, llm_stub
):
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    assert response.status_code == 400
    assert "AI provider" in response.json()["detail"]
    assert llm_stub.calls == []


def test_get_returns_null_before_generation_and_summary_after(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    initial = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights"
    )
    assert initial.status_code == 200
    assert initial.json() is None

    authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    after = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights"
    )
    assert after.status_code == 200
    assert after.json()["narrative"]


def test_stale_flag_set_when_completed_rows_advances(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    first = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    assert first.status_code == 200
    assert first.json()["is_stale"] is False

    # Simulate more rows finishing without regenerating.
    evaluation.completed_rows = evaluation.completed_rows + 5
    db_session.commit()

    cached = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights"
    )
    body = cached.json()
    assert body is not None
    assert body["is_stale"] is True
    # GET hitting the cache should NOT have triggered another LLM call.
    assert len(llm_stub.calls) == 1


def test_post_with_stale_cache_returns_cached_until_explicit_regenerate(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider, llm_stub
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, evaluation, _ = _seed_eval_with_data(db_session, org_id)

    authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    evaluation.completed_rows += 5
    db_session.commit()

    # Default POST returns the (stale) cached summary, no LLM call.
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={},
    )
    assert response.status_code == 200
    assert response.json()["is_stale"] is True
    assert len(llm_stub.calls) == 1

    # regenerate=True bypasses the cache and re-calls the LLM.
    fresh = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/insights",
        json={"regenerate": True},
    )
    assert fresh.status_code == 200
    assert fresh.json()["is_stale"] is False
    assert len(llm_stub.calls) == 2


def test_404_for_unknown_evaluation(
    authenticated_client, db_session, org_id, seed_org, make_ai_provider
):
    make_ai_provider(provider="openai", is_active=True)
    call_import, _, _ = _seed_eval_with_data(db_session, org_id)
    response = authenticated_client.post(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{uuid4()}/insights",
        json={},
    )
    assert response.status_code == 404


# Make sure we keep the helper exported via the route module's namespace
# so future patches stay aware of it.
def test_route_module_exports_summary_helper():
    assert hasattr(routes_module, "_tldr_summary_payload")
