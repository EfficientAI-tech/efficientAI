"""Tests for evaluation row pair sampling."""

from uuid import uuid4

from app.db_sharding.scatter_gather import load_completed_evaluation_row_pairs_sample


def test_sample_subsample_by_sorted_position_not_row_index_parity(monkeypatch):
    from app.models.database import CallImportEvaluationRow, CallImportRow

    eval_id = uuid4()
    pairs = [
        (
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=eval_id,
                call_import_row_id=uuid4(),
                status="completed",
            ),
            CallImportRow(id=uuid4(), row_index=i, conversation_id=f"c-{i}"),
        )
        for i in range(1, 7)
    ]

    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.count_completed_evaluation_row_pairs",
        lambda _db, _eid: len(pairs),
    )
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather._load_completed_evaluation_row_pair_keys",
        lambda _db, _eid: [
            (p[0].id, int(p[1].row_index or 0), p[0].call_import_row_id)
            for p in pairs
        ],
    )
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.load_completed_evaluation_row_pairs_for_eval_row_ids",
        lambda _db, _eid, eval_row_ids: [
            p for p in pairs if p[0].id in eval_row_ids
        ],
    )

    out = load_completed_evaluation_row_pairs_sample(None, eval_id, max_pairs=3)
    assert len(out) == 3
    assert [p[1].row_index for p in out] == [1, 3, 5]


def test_sample_returns_all_when_under_cap(monkeypatch):
    from app.models.database import CallImportEvaluationRow, CallImportRow

    eval_id = uuid4()
    pairs = [
        (
            CallImportEvaluationRow(
                id=uuid4(),
                evaluation_id=eval_id,
                call_import_row_id=uuid4(),
                status="completed",
            ),
            CallImportRow(id=uuid4(), row_index=i, conversation_id=f"c-{i}"),
        )
        for i in range(5)
    ]

    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.is_sharding_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather.count_completed_evaluation_row_pairs",
        lambda _db, _eid: 5,
    )
    monkeypatch.setattr(
        "app.db_sharding.scatter_gather._completed_evaluation_row_pairs_query",
        lambda _db, _eid: _QueryStub(pairs),
    )

    out = load_completed_evaluation_row_pairs_sample(None, eval_id, max_pairs=100)
    assert len(out) == 5
    assert [p[1].row_index for p in out] == [0, 1, 2, 3, 4]


class _QueryStub:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def filter(self, *_a, **_k):
        return self
