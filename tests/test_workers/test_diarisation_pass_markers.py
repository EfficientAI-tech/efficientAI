"""Per-pass diarisation markers keep overwrite runs from re-scoring old text."""

from uuid import uuid4

import pytest


class _FakeRedis:
    """Minimal set / get / delete surface used by the pass markers."""

    def __init__(self):
        self.sets: dict[str, set[str]] = {}
        self.strings: dict[str, str] = {}

    def delete(self, key):
        self.sets.pop(key, None)
        self.strings.pop(key, None)
        return 1

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)
        return 1

    def expire(self, key, ttl):
        return True

    def sismember(self, key, value):
        return value in self.sets.get(key, set())

    def setex(self, key, ttl, value):
        self.strings[key] = value
        return True

    def get(self, key):
        return self.strings.get(key)

    def pipeline(self, transaction=False):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client):
        self._client = client
        self._ops = []

    def sadd(self, key, value):
        self._ops.append(("sadd", key, value))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "sadd":
                results.append(self._client.sadd(op[1], op[2]))
            else:
                results.append(self._client.expire(op[1], op[2]))
        self._ops.clear()
        return results


@pytest.fixture
def fake_redis(monkeypatch):
    from app.workers.concurrency import fair_dispatch

    client = _FakeRedis()
    monkeypatch.setattr(fair_dispatch, "_get_redis", lambda: client)
    return client


def test_row_diarised_in_pass_is_false_before_the_worker_finishes(fake_redis):
    from app.workers.concurrency.fair_dispatch import row_diarised_in_pass

    evaluation_id = uuid4()
    source_row_id = uuid4()

    assert row_diarised_in_pass(evaluation_id, source_row_id) is False


def test_mark_then_read_reports_the_row_diarised(fake_redis):
    from app.workers.concurrency.fair_dispatch import (
        mark_row_diarised_in_pass,
        row_diarised_in_pass,
    )

    evaluation_id = uuid4()
    source_row_id = uuid4()

    mark_row_diarised_in_pass(evaluation_id, source_row_id)

    assert row_diarised_in_pass(evaluation_id, source_row_id) is True
    # Markers are scoped per evaluation, not global per source row.
    assert row_diarised_in_pass(uuid4(), source_row_id) is False


def test_store_overwrite_clears_stale_pass_markers(fake_redis):
    from app.workers.concurrency.fair_dispatch import (
        mark_row_diarised_in_pass,
        row_diarised_in_pass,
        store_evaluation_transcribe_overwrite,
    )

    evaluation_id = uuid4()
    source_row_id = uuid4()
    mark_row_diarised_in_pass(evaluation_id, source_row_id)

    store_evaluation_transcribe_overwrite(evaluation_id, overwrite=True)

    assert row_diarised_in_pass(evaluation_id, source_row_id) is False


def test_store_overwrite_false_clears_the_overwrite_flag(fake_redis):
    """A plain retry must not inherit an earlier run's overwrite flag."""
    from app.workers.concurrency.fair_dispatch import (
        evaluation_transcribe_overwrite,
        store_evaluation_transcribe_overwrite,
    )

    evaluation_id = uuid4()
    store_evaluation_transcribe_overwrite(evaluation_id, overwrite=True)
    assert evaluation_transcribe_overwrite(evaluation_id) is True

    store_evaluation_transcribe_overwrite(evaluation_id, overwrite=False)

    assert evaluation_transcribe_overwrite(evaluation_id) is False
