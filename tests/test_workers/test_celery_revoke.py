from unittest.mock import MagicMock

import pytest


def test_revoke_defaults_to_no_terminate(monkeypatch):
    revoke = MagicMock()
    fake = MagicMock()
    fake.celery_app.control.revoke = revoke
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.workers.celery_app",
        fake,
    )
    from app.config import settings

    settings.CELERY_REVOKE_USE_TERMINATE = False
    from app.workers.celery_revoke import revoke_celery_tasks

    assert revoke_celery_tasks(["a", "b"]) == 2
    revoke.assert_called_once_with(["a", "b"], terminate=False)


def test_revoke_honors_config_terminate(monkeypatch):
    revoke = MagicMock()
    fake = MagicMock()
    fake.celery_app.control.revoke = revoke
    monkeypatch.setitem(
        __import__("sys").modules,
        "app.workers.celery_app",
        fake,
    )
    from app.config import settings

    settings.CELERY_REVOKE_USE_TERMINATE = True
    from app.workers.celery_revoke import revoke_celery_tasks

    revoke_celery_tasks(["x"], terminate=None)
    revoke.assert_called_once_with(["x"], terminate=True, signal="SIGTERM")
