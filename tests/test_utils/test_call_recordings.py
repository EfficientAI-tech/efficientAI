"""Unit tests for call recording helpers."""

import pytest
from fastapi import HTTPException

from app.utils.call_recordings import generate_unique_call_short_id


class _FakeQuery:
    def __init__(self, existing_ids):
        self._existing_ids = existing_ids
        self._candidate = None

    def filter(self, expression):
        self._candidate = str(expression.right.value)
        return self

    def first(self):
        return object() if self._candidate in self._existing_ids else None


class _FakeDB:
    def __init__(self, existing_ids):
        self._existing_ids = existing_ids

    def query(self, _model):
        return _FakeQuery(self._existing_ids)


def test_generate_unique_call_short_id_returns_first_available(monkeypatch):
    fake_db = _FakeDB(existing_ids={"111111", "222222"})
    candidates = iter([111111, 222222, 333333])
    monkeypatch.setattr("app.utils.call_recordings.random.randint", lambda _a, _b: next(candidates))

    generated = generate_unique_call_short_id(fake_db)

    assert generated == "333333"


def test_generate_unique_call_short_id_raises_after_max_attempts(monkeypatch):
    fake_db = _FakeDB(existing_ids={"123456"})
    monkeypatch.setattr("app.utils.call_recordings.random.randint", lambda _a, _b: 123456)

    with pytest.raises(HTTPException, match="Failed to generate unique call short ID"):
        generate_unique_call_short_id(fake_db, max_attempts=3)
