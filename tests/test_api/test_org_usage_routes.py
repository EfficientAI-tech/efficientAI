"""Ensure org usage API routes are mounted on the v1 router."""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

import inspect

from app.api.v1.routes.org_usage import (
    _breakdown_sort_exprs,
    _call_import_ids_scope_filter,
    _direct_call_import_id_expr,
    _evaluation_scope_filter,
    _filters_share_facet_scan,
    _grouped_resource_filter_rows,
    _scoped_call_import_id_select,
    _usage_range_is_historical,
    get_usage_summary,
)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.api import api_router
from app.api.v1.routes import usage_pricing
from app.database import get_db
from app.dependencies import get_organization_id


def test_org_usage_routes_are_registered():
    paths = {route.path for route in api_router.routes if hasattr(route, "path")}
    assert "/organizations/usage/summary" in paths
    assert "/organizations/usage/breakdown" in paths
    assert "/organizations/usage/filters" in paths
    assert "/organizations/usage/fx-rate" in paths
    assert "/organizations/usage/pricing/overrides" in paths
    assert "/organizations/usage/pricing/overrides/{model:path}" in paths


def _override_client(monkeypatch, seen: list[str]) -> TestClient:
    def fake_get_effective_rate(db, *, organization_id, model, usage_kind, as_of):
        del db, organization_id
        seen.append(model)
        return {
            "model": model,
            "usage_kind": usage_kind,
            "as_of": as_of,
            "catalog_rates": {"input_per_1m": 1.5, "output_per_1m": 9.0},
            "catalog_rate_id": None,
            "override": None,
            "effective_rates": {"input_per_1m": 1.5, "output_per_1m": 9.0},
            "effective_source": "catalog",
            "effective_rate_id": None,
            "has_override": False,
        }

    monkeypatch.setattr(usage_pricing, "get_effective_rate", fake_get_effective_rate)
    app = FastAPI()
    app.include_router(usage_pricing.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_organization_id] = lambda: uuid4()
    for dep in usage_pricing.router.dependencies:
        app.dependency_overrides[dep.dependency] = lambda: None
    return TestClient(app)


def test_pricing_override_get_accepts_encoded_slash_model_id(monkeypatch):
    seen: list[str] = []
    client = _override_client(monkeypatch, seen)

    response = client.get(
        "/organizations/usage/pricing/overrides/google%2Fgemini-3.5-flash",
        params={"usage_kind": "llm", "as_of": "2026-11-10"},
    )

    assert response.status_code == 200
    assert seen == ["google/gemini-3.5-flash"]
    body = response.json()
    assert body["model"] == "google/gemini-3.5-flash"
    assert body["as_of"] == date(2026, 11, 10).isoformat()
    assert body["effective_rates"]["input_per_1m"] == 1.5


def test_pricing_override_get_still_accepts_plain_model_id(monkeypatch):
    seen: list[str] = []
    client = _override_client(monkeypatch, seen)

    response = client.get(
        "/organizations/usage/pricing/overrides/gpt-4o",
        params={"usage_kind": "llm"},
    )

    assert response.status_code == 200
    assert seen == ["gpt-4o"]
    assert response.json()["model"] == "gpt-4o"


def test_summary_releases_single_flight_lock_when_query_raises(monkeypatch):
    import pytest
    from app.api.v1.routes import org_usage as usage_routes

    released: list[tuple] = []
    monkeypatch.setattr(
        usage_routes,
        "_prepare_usage_read",
        lambda org_id, endpoint, key, model: (None, True, 1),
    )
    monkeypatch.setattr(
        usage_routes,
        "release_read_lock",
        lambda org_id, endpoint, key: released.append((org_id, endpoint, key)),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(usage_routes, "_summary_aggregate_query", boom)

    org_id = uuid4()
    with pytest.raises(RuntimeError, match="db unavailable"):
        get_usage_summary(
            start=date(2026, 8, 1),
            end=date(2026, 8, 2),
            tz="UTC",
            workspace_id=None,
            product_section=None,
            model=None,
            resource_id=None,
            usage_kind=None,
            call_import_id=None,
            evaluation_id=None,
            evaluation_row_id=None,
            dataset=None,
            tag_id=None,
            organization_id=org_id,
            db=MagicMock(),
        )

    assert len(released) == 1
    assert released[0][0] == org_id
    assert released[0][1] == "summary"


def test_evaluation_scope_filter_does_not_scan_eval_rows():
    db = MagicMock()
    expr = _evaluation_scope_filter(uuid4(), uuid4(), db)
    db.query.assert_not_called()
    sql = str(
        expr.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "evaluation_id" in sql
    assert "evaluation_row_id" not in sql
    assert "call_import_evaluation_rows" not in sql


def test_call_import_grouping_does_not_join_row_tables():
    sql = str(
        _direct_call_import_id_expr().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "call_import_id" in sql
    assert "call_import_rows" not in sql
    assert "call_import_evaluation_rows" not in sql


def test_breakdown_sort_weights_tokens_before_cost():
    sql = " ".join(
        str(expr.compile(dialect=postgresql.dialect())) for expr in _breakdown_sort_exprs()
    )
    assert "prompt_tokens" in sql
    assert "completion_tokens" in sql
    assert sql.index("prompt_tokens") < sql.index("total_cost_micro_usd")


def test_resource_filter_bundle_labels_evaluations_from_grouped_rows(monkeypatch):
    from app.api.v1.routes import org_usage as usage_routes

    monkeypatch.setattr(
        usage_routes,
        "_grouped_resource_filter_rows",
        lambda query, extra_resource_ids=None: [
            (
                "res-1",
                "agent",
                "agents",
                "eval-1",
                {"evaluation_id": "eval-1", "resource_id": "res-1"},
            )
        ],
    )
    monkeypatch.setattr(
        usage_routes, "_infer_agent_types_for_label_buckets", lambda *args, **kwargs: None
    )

    class Resolver:
        def __init__(self, db, organization_id):
            del db, organization_id

        def preload(self, contexts):
            del contexts

        def evaluation_name(self, raw_id):
            return f"Evaluation {raw_id}"

    monkeypatch.setattr(usage_routes, "UsageNameResolver", Resolver)
    monkeypatch.setattr(
        usage_routes,
        "labels_for_resource_buckets",
        lambda buckets, resolver: {"res-1": "Agent"},
    )

    labels, meta, evaluations = usage_routes._resource_filter_bundle(
        MagicMock(), uuid4(), MagicMock()
    )

    assert labels == {"res-1": "Agent"}
    assert meta["res-1"]["type"] == "agent"
    assert evaluations["eval-1"] == "Evaluation eval-1"


def test_unscoped_usage_filters_share_one_facet_scan():
    assert (
        _filters_share_facet_scan(
            workspace_id=None,
            product_section=None,
            model=None,
            resource_id=None,
            usage_kind=None,
            call_import_id=None,
            evaluation_id=None,
        )
        is True
    )
    assert (
        _filters_share_facet_scan(
            workspace_id=uuid4(),
            product_section=None,
            model=None,
            resource_id=None,
            usage_kind=None,
            call_import_id=None,
            evaluation_id=None,
        )
        is False
    )


def test_resource_filter_scan_does_not_aggregate_context_json():
    source = inspect.getsource(_grouped_resource_filter_rows)
    assert "func.array_agg" not in source
    assert ".distinct(" in source


def test_dataset_filter_stays_a_sql_subquery():
    expr = _call_import_ids_scope_filter(
        _scoped_call_import_id_select(
            organization_id=uuid4(),
            dataset="billing",
            tag_id=uuid4(),
        )
    )
    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))
    assert "call_imports" in sql
    assert ".all(" not in inspect.getsource(_scoped_call_import_id_select)


def test_closed_utc_range_is_historical_even_when_local_today_is_behind():
    access = MagicMock()
    access.filter_end = date(2020, 1, 1)
    assert _usage_range_is_historical(access) is True
    access.filter_end = date(2999, 1, 1)
    assert _usage_range_is_historical(access) is False
