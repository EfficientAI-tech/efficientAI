from __future__ import annotations

import pytest

from efficientai_sdk import _base_client
from efficientai_sdk._config import ENV_API_KEY, ENV_BASE_URL, ENV_BASE_URL_LEGACY, ENV_WORKSPACE_ID

BASE_URL = "https://api.test"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not pick up a developer's real EFFICIENTAI_* settings."""
    for name in (ENV_API_KEY, ENV_WORKSPACE_ID, ENV_BASE_URL, ENV_BASE_URL_LEGACY):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry sleeps instead of waiting."""
    recorded: list[float] = []

    async def fake_async_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(_base_client.time, "sleep", recorded.append)
    monkeypatch.setattr(_base_client.asyncio, "sleep", fake_async_sleep)
    return recorded
