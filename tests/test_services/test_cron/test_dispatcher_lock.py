"""Cron dispatcher lock fail-closed on Redis errors."""

from app.services.cron.dispatcher_lock import acquire_dispatcher_run_lock


def test_acquire_dispatcher_run_lock_fails_closed_on_redis_error(monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        "app.services.cron.dispatcher_lock._client",
        lambda: type("C", (), {"set": staticmethod(boom)})(),
    )
    assert acquire_dispatcher_run_lock() is False
