"""Startup pricing sync from models.json (app_factory._sync_pricing_rates)."""

from __future__ import annotations

from unittest.mock import MagicMock

import app.database as database_mod
import app.services.usage.pricing_ops as pricing_ops
from app.app_factory import _sync_pricing_rates
from app.config import settings


def _patch_session(monkeypatch) -> MagicMock:
    session = MagicMock()
    monkeypatch.setattr(database_mod, "SessionLocal", lambda: session)
    return session


def test_sync_failure_does_not_block_startup(monkeypatch):
    session = _patch_session(monkeypatch)
    monkeypatch.setattr(settings, "USAGE_PRICING_SYNC_ON_STARTUP", True)

    def boom(_db):
        raise RuntimeError("rates table missing")

    monkeypatch.setattr(pricing_ops, "sync_rates_from_models_json", boom)

    _sync_pricing_rates()  # must not raise

    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_sync_skipped_when_disabled(monkeypatch):
    _patch_session(monkeypatch)
    monkeypatch.setattr(settings, "USAGE_PRICING_SYNC_ON_STARTUP", False)
    sync = MagicMock()
    monkeypatch.setattr(pricing_ops, "sync_rates_from_models_json", sync)

    _sync_pricing_rates()

    sync.assert_not_called()
