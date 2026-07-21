"""Sharded evaluation row pagination must not load every pair per request."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
    TelephonyIntegration,
    Workspace,
)
from app.models.enums import CallImportRowStatus, CallImportStatus


def _seed_eval(db_session, org_id, *, num_rows: int):
    workspace = (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
    )
    if workspace is None:
        workspace = Workspace(
            organization_id=org_id,
            name="Default",
            slug="default",
            is_default=True,
        )
        db_session.add(workspace)
        db_session.flush()

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
    db_session.flush()

    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Quality",
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
        column_mapping={"external_call_id": "CallID", "transcript": "Transcript"},
        extra_columns=[],
        total_rows=num_rows,
        completed_rows=num_rows,
        failed_rows=0,
        status=CallImportStatus.COMPLETED,
    )
    db_session.add(call_import)
    db_session.flush()

    evaluation = CallImportEvaluation(
        id=uuid4(),
        call_import_id=call_import.id,
        organization_id=org_id,
        workspace_id=workspace.id,
        name="Large pass",
        selected_metric_ids=[str(metric.id)],
        status="completed",
        total_rows=num_rows,
        completed_rows=num_rows,
        failed_rows=0,
    )
    db_session.add(evaluation)
    db_session.flush()

    for idx in range(num_rows):
        source_row = CallImportRow(
            id=uuid4(),
            call_import_id=call_import.id,
            organization_id=org_id,
            row_index=idx,
            conversation_id=f"call-{idx:05d}",
            transcript=f"transcript-{idx}",
            raw_columns={"CallID": f"call-{idx:05d}", "Transcript": f"transcript-{idx}"},
            status=CallImportRowStatus.COMPLETED,
        )
        db_session.add(source_row)
        db_session.flush()
        db_session.add(
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=evaluation.id,
                call_import_row_id=source_row.id,
                status="completed",
                metric_scores={
                    str(metric.id): {
                        "value": idx % 5,
                        "type": "rating",
                        "metric_name": "Quality",
                    }
                },
            )
        )

    db_session.commit()
    return call_import, evaluation


def test_fetch_page_applies_per_shard_limit(monkeypatch):
    from app.db_sharding.eval_rows import fetch_evaluation_row_pairs_page

    limits: list[tuple[str, int]] = []

    def make_pair(row_index: int):
        eval_row = SimpleNamespace(status="completed", metric_scores={})
        source_row = SimpleNamespace(
            row_index=row_index,
            conversation_id=f"c{row_index}",
        )
        return (eval_row, source_row)

    class FakeQuery:
        def __init__(self, shard_id: str):
            self.shard_id = shard_id
            self._limit = 0

        def limit(self, n: int):
            limits.append((self.shard_id, n))
            self._limit = n
            return self

        def all(self):
            if self.shard_id == "shard-a":
                pairs = [make_pair(i) for i in range(0, 200, 2)]
            else:
                pairs = [make_pair(i) for i in range(1, 200, 2)]
            return pairs[: self._limit]

    class FakeSession:
        def __init__(self, shard_id: str):
            self.shard_id = shard_id

        def close(self):
            return None

    class FakeRouter:
        shard_ids = ["shard-a", "shard-b"]

    class FakePoolManager:
        router = FakeRouter()

        @staticmethod
        def shard_session_factory(shard_id: str):
            def factory():
                return FakeSession(shard_id)

            return factory

    def build_query(session):
        return FakeQuery(session.shard_id)

    monkeypatch.setattr("app.db_sharding.eval_rows.is_sharding_enabled", lambda: True)
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.scatter_gather_eval_query_count",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.db_pool_manager",
        FakePoolManager(),
    )

    total, rows = fetch_evaluation_row_pairs_page(
        None,
        build_query,
        page=1,
        page_size=50,
        sort_key=lambda pair: int(pair[1].row_index or 0),
    )

    assert total == 100
    assert len(rows) == 50
    assert limits == [("shard-a", 50), ("shard-b", 50)]
    assert int(rows[0][1].row_index) == 0
    assert int(rows[1][1].row_index) == 1


def test_fetch_page_status_filter_count_and_slice(monkeypatch):
    from app.db_sharding.eval_rows import fetch_evaluation_row_pairs_page

    pairs = [
        (
            SimpleNamespace(status="pending", metric_scores={}),
            SimpleNamespace(row_index=0, conversation_id="a"),
        ),
        (
            SimpleNamespace(status="completed", metric_scores={}),
            SimpleNamespace(row_index=1, conversation_id="b"),
        ),
        (
            SimpleNamespace(status="pending", metric_scores={}),
            SimpleNamespace(row_index=2, conversation_id="c"),
        ),
    ]

    class FakeQuery:
        def limit(self, n: int):
            self._limit = n
            return self

        def offset(self, n: int):
            self._offset = n
            return self

        def all(self):
            start = getattr(self, "_offset", 0)
            end = start + getattr(self, "_limit", len(pairs))
            return pairs[start:end]

    monkeypatch.setattr("app.db_sharding.eval_rows.is_sharding_enabled", lambda: False)
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.scatter_gather_eval_query_count",
        lambda *_args, **_kwargs: 2,
    )

    total, rows = fetch_evaluation_row_pairs_page(
        object(),
        lambda _session: FakeQuery(),
        page=1,
        page_size=1,
        sort_key=lambda pair: int(pair[1].row_index or 0),
    )

    assert total == 2
    assert len(rows) == 1
    assert rows[0][0].status == "pending"


def test_list_rows_sharded_uses_bounded_page_fetch(
    authenticated_client,
    db_session,
    org_id,
    monkeypatch,
):
    call_import, evaluation = _seed_eval(db_session, org_id, num_rows=120)

    load_all_called = False

    def forbidden_load_all(*_args, **_kwargs):
        nonlocal load_all_called
        load_all_called = True
        raise AssertionError("load_evaluation_row_pairs must not be called")

    captured: dict[str, int] = {}

    def fake_fetch_page(
        _db,
        build_query,
        *,
        page,
        page_size,
        sort_key,
        sort_desc=False,
    ):
        del sort_key, sort_desc
        captured["page"] = page
        captured["page_size"] = page_size
        rows = build_query(db_session).limit(page_size).all()
        return 120, rows

    monkeypatch.setattr("app.db_sharding.sessions.is_sharding_enabled", lambda: True)
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.load_evaluation_row_pairs",
        forbidden_load_all,
    )
    monkeypatch.setattr(
        "app.db_sharding.eval_rows.fetch_evaluation_row_pairs_page",
        fake_fetch_page,
    )

    response = authenticated_client.get(
        f"/api/v1/call-imports/{call_import.id}/evaluations/{evaluation.id}/rows",
        params={"page": 1, "page_size": 50},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 120
    assert len(body["items"]) == 50
    assert captured == {"page": 1, "page_size": 50}
    assert load_all_called is False


def test_register_shard_slices_scales_with_slice_count(monkeypatch):
    from app.db_sharding.row_ops import register_shard_slices

    shard_calls: list[int] = []

    class FakeRouter:
        row_chunk_size = 500

        def shard_id_for_row(self, _call_import_id, row_index: int) -> str:
            shard_calls.append(row_index)
            return f"shard-{row_index // 500}"

    monkeypatch.setattr(
        "app.db_sharding.row_ops.is_sharding_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.db_sharding.row_ops.router_for_import",
        lambda *_args, **_kwargs: (FakeRouter(), None),
    )

    merged: list[object] = []

    class FakeCatalog:
        def merge(self, obj):
            merged.append(obj)

        def flush(self):
            return None

    register_shard_slices(FakeCatalog(), uuid4(), total_rows=70_000)

    assert len(shard_calls) == 140
    assert len(merged) == 140
