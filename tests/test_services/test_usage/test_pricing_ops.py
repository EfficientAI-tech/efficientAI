"""Tests for usage pricing ops helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.services.usage.pricing_ops as pricing_ops
from app.services.usage.pricing_ops import (
    models_missing_pricing_blocks,
    pricing_sync_on_startup_enabled,
    sync_rates_from_models_json,
)


def test_models_missing_pricing_blocks_is_sorted_list():
    missing = models_missing_pricing_blocks()
    assert missing == sorted(missing)


def _diff_report(*, only_in_json=(), mismatched=(), only_in_db=()):
    return {
        "only_in_models_json": [{"model": m, "usage_kind": "llm"} for m in only_in_json],
        "mismatches": [{"model": m, "usage_kind": "llm", "fields": {}} for m in mismatched],
        "only_in_database": [{"model": m, "usage_kind": "llm"} for m in only_in_db],
    }


def test_sync_rates_seeds_only_new_and_changed_models(monkeypatch):
    calls = []
    db = MagicMock()
    db.commit.side_effect = lambda: calls.append("commit")
    monkeypatch.setattr(
        pricing_ops,
        "diff_models_json_vs_db",
        lambda _db, effective_from=None: _diff_report(
            only_in_json=["claude-opus-5-5"],
            mismatched=["claude-fable-5-1"],
            only_in_db=["retired-model"],
        ),
    )
    seeded = {}

    def fake_seed(_db, *, effective_from=None, models=None):
        calls.append("seed")
        seeded["models"] = models
        return len(models)

    monkeypatch.setattr(pricing_ops, "seed_pricing_rates", fake_seed)
    monkeypatch.setattr(pricing_ops, "_models_with_later_rates", lambda _db, effective_from: set())
    monkeypatch.setattr(
        pricing_ops, "invalidate_all_pricing_cache", lambda: calls.append("invalidate")
    )

    result = sync_rates_from_models_json(db)

    assert result == {
        "added": ["claude-opus-5-5"],
        "updated": ["claude-fable-5-1"],
        "skipped": [],
    }
    assert seeded["models"] == {"claude-opus-5-5", "claude-fable-5-1"}
    # Cache must be cleared after the rows are committed, not before.
    assert calls == ["seed", "commit", "invalidate"]


def test_sync_rates_is_noop_when_in_sync(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(
        pricing_ops,
        "diff_models_json_vs_db",
        lambda _db, effective_from=None: _diff_report(only_in_db=["retired-model"]),
    )
    seed = MagicMock()
    invalidate = MagicMock()
    monkeypatch.setattr(pricing_ops, "seed_pricing_rates", seed)
    monkeypatch.setattr(pricing_ops, "invalidate_all_pricing_cache", invalidate)

    assert sync_rates_from_models_json(db) == {"added": [], "updated": [], "skipped": []}
    seed.assert_not_called()
    db.commit.assert_not_called()
    invalidate.assert_not_called()


def test_sync_rates_skips_models_with_later_dated_rates(monkeypatch):
    # A later-dated row wins at runtime, so updating the default row would be a no-op
    # that reports success; those models must be skipped and reported instead.
    db = MagicMock()
    monkeypatch.setattr(
        pricing_ops,
        "diff_models_json_vs_db",
        lambda _db, effective_from=None: _diff_report(
            only_in_json=["new-model", "dated-new-model"],
            mismatched=["claude-opus-5-5", "claude-fable-5-1"],
        ),
    )
    monkeypatch.setattr(
        pricing_ops,
        "_models_with_later_rates",
        lambda _db, effective_from: {"claude-opus-5-5", "dated-new-model", "unrelated"},
    )
    seed = MagicMock()
    monkeypatch.setattr(pricing_ops, "seed_pricing_rates", seed)
    monkeypatch.setattr(pricing_ops, "invalidate_all_pricing_cache", lambda: None)

    result = sync_rates_from_models_json(db)

    assert result == {
        "added": ["new-model"],
        "updated": ["claude-fable-5-1"],
        "skipped": ["claude-opus-5-5", "dated-new-model"],
    }
    assert seed.call_args.kwargs["models"] == {"new-model", "claude-fable-5-1"}


def test_seed_pricing_rates_models_filter(monkeypatch):
    import app.services.usage.pricing as pricing_mod
    import app.services.usage.pricing_cache as pricing_cache_mod

    monkeypatch.setattr(pricing_mod, "_rates_table", lambda _db: "model_pricing_rates")
    monkeypatch.setattr(pricing_cache_mod, "invalidate_all_pricing_cache", lambda: None)
    db = MagicMock()
    db.execute.return_value.first.return_value = None  # no currency column
    db.execute.return_value.rowcount = 1

    count = pricing_mod.seed_pricing_rates(db, models={"claude-opus-5-5", "claude-fable-5-1"})

    upserted = [
        call.args[1]["model"]
        for call in db.execute.call_args_list
        if len(call.args) > 1 and "model" in call.args[1]
    ]
    assert count == 2
    assert sorted(upserted) == ["claude-fable-5-1", "claude-opus-5-5"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("true", True), ("1", True), ("false", False), ("off", False), ("0", False)],
)
def test_pricing_sync_setting_parses_env(monkeypatch, value, expected):
    from app.config import Settings

    if value is None:
        monkeypatch.delenv("USAGE_PRICING_SYNC_ON_STARTUP", raising=False)
    else:
        monkeypatch.setenv("USAGE_PRICING_SYNC_ON_STARTUP", value)
    assert Settings(_env_file=None).USAGE_PRICING_SYNC_ON_STARTUP is expected


def test_pricing_sync_opt_out_survives_later_env_override(monkeypatch):
    # voice_bundle.py calls load_dotenv(override=True) during app import; a .env
    # containing "true" must not re-enable a sync the operator turned off.
    from app.config import settings

    monkeypatch.setattr(settings, "USAGE_PRICING_SYNC_ON_STARTUP", False)
    monkeypatch.setenv("USAGE_PRICING_SYNC_ON_STARTUP", "true")
    assert pricing_sync_on_startup_enabled() is False
