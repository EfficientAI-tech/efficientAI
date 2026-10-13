"""Tests for platform historical call import helpers."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.call_imports.debounced_rollup import platform_discovery_blocks_terminal_status
from app.services.call_imports.platform_discovery import (
    _should_skip_item,
    list_failure_disposition,
    platform_row_id,
    plan_time_slices,
)
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    SkipReason,
    build_canonical_recording_url,
    parse_canonical_recording_url,
)


def test_build_and_parse_canonical_recording_url():
    url = build_canonical_recording_url("elevenlabs", "conv-123")
    assert url == "elevenlabs://conversations/conv-123"
    provider, conv_id = parse_canonical_recording_url(url)
    assert provider == "elevenlabs"
    assert conv_id == "conv-123"


def test_platform_row_id_is_deterministic():
    import_id = uuid4()
    a = platform_row_id(import_id, "abc")
    b = platform_row_id(import_id, "abc")
    c = platform_row_id(import_id, "xyz")
    assert a == b
    assert a != c


def test_plan_time_slices_splits_by_day_and_agent():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 3, tzinfo=timezone.utc)
    slices = plan_time_slices(start, end, ["agent-a", "agent-b"])
    assert len(slices) == 4


def test_chat_import_keeps_transcript_without_audio():
    item = HistoricalListItem(
        conversation_id="chat_1",
        status="ended",
        has_audio=False,
        duration_seconds=1,
    )
    assert _should_skip_item(item, {"medium": "chat"}) is None
    voice = HistoricalListItem(
        conversation_id="call_1",
        status="ended",
        has_audio=False,
        duration_seconds=30,
    )
    assert _should_skip_item(voice, {"medium": "voice"}) is SkipReason.NO_AUDIO


def test_clear_expired_claims_drops_task_without_live_lease(monkeypatch):
    from unittest.mock import MagicMock

    from app.models.enums import CallImportRowStatus
    from app.workers.concurrency.platform_import_dispatch import (
        clear_expired_platform_row_claims,
    )

    monkeypatch.setattr(
        "app.workers.concurrency.platform_import_dispatch.lease_is_active",
        lambda _tid: False,
    )
    row = MagicMock()
    row.celery_task_id = "task-stale"
    row.attempts = 0
    row.status = CallImportRowStatus.PENDING
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = [row]
    count = clear_expired_platform_row_claims(db)
    assert count == 1
    assert row.celery_task_id is None
    db.commit.assert_called_once()


def test_clear_expired_claims_keeps_live_lease(monkeypatch):
    from unittest.mock import MagicMock

    from app.workers.concurrency.platform_import_dispatch import (
        clear_expired_platform_row_claims,
    )

    monkeypatch.setattr(
        "app.workers.concurrency.platform_import_dispatch.lease_is_active",
        lambda _tid: True,
    )
    row = MagicMock()
    row.celery_task_id = "task-live"
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = [row]
    count = clear_expired_platform_row_claims(db)
    assert count == 0
    assert row.celery_task_id == "task-live"


def test_acquire_lease_fails_closed(monkeypatch):
    from app.workers.concurrency.platform_import_limits import acquire_platform_lease

    class _Down:
        def eval(self, *_args, **_kwargs):
            import redis

            raise redis.RedisError("redis down")

    monkeypatch.setattr(
        "app.workers.concurrency.platform_import_limits._client",
        lambda: _Down(),
    )
    assert acquire_platform_lease(
        celery_task_id="t1",
        workspace_id="ws",
        organization_id="org",
        call_import_id="imp",
    ) is False


def test_vapi_hydrate_fetches_call_when_list_has_no_audio():
    from app.services.voice_providers.historical.base import HistoricalListItem
    from app.services.voice_providers.historical.vapi import VapiHistoricalAdapter

    fetched = {"id": "call-1", "transcript": "hello", "recordingUrl": "https://audio.example/a.mp3"}
    adapter = VapiHistoricalAdapter.__new__(VapiHistoricalAdapter)
    adapter._provider = type("P", (), {"retrieve_call_metrics": lambda self, _cid: fetched})()
    item = HistoricalListItem(conversation_id="call-1", raw={"id": "call-1"})
    call = adapter.hydrate(item)
    assert call.audio_url == "https://audio.example/a.mp3"
    assert "hello" in call.transcript


def test_retell_list_calls_uses_v3_agent_filter():
    from app.services.voice_providers.historical.base import TimeSlice
    from app.services.voice_providers.historical.retell import (
        RETELL_LIST_CALLS_URL,
        RetellHistoricalAdapter,
    )

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"items": [], "has_more": False}

    adapter = RetellHistoricalAdapter.__new__(RetellHistoricalAdapter)
    adapter._api_key = "k"
    import app.services.voice_providers.historical.retell as retell_mod

    def _post(url, *args, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _Resp()

    original = retell_mod.requests.post
    retell_mod.requests.post = _post
    try:
        window = TimeSlice(
            slice_id=0,
            slice_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            slice_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
            agent_id="agent_abc123",
        )
        adapter.list_page(window, None)
        assert captured["url"] == RETELL_LIST_CALLS_URL
        fc = captured["json"]["filter_criteria"]
        assert fc.get("agent") == [{"agent_id": "agent_abc123"}]
        assert "agent_id" not in fc
        ts = fc.get("start_timestamp") or {}
        assert ts.get("type") == "range"
        assert ts.get("op") == "bt"
        assert ts.get("value") == [
            int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
            int(datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp() * 1000),
        ]
    finally:
        retell_mod.requests.post = original


def test_retell_pagination_stops_on_repeated_cursor():
    from app.services.voice_providers.historical.base import TimeSlice
    from app.services.voice_providers.historical.retell import (
        RETELL_LIST_CALLS_URL,
        RetellHistoricalAdapter,
    )

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [{"call_id": "c1", "start_timestamp": 1}],
                "pagination_key": "same",
            }

    adapter = RetellHistoricalAdapter.__new__(RetellHistoricalAdapter)
    adapter._api_key = "k"
    import app.services.voice_providers.historical.retell as retell_mod

    captured_url: list[str] = []
    original = retell_mod.requests.post

    def _post(url, *args, **kwargs):
        captured_url.append(url)
        return _Resp()

    retell_mod.requests.post = _post
    try:
        window = TimeSlice(
            slice_id=0,
            slice_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            slice_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        items, nxt = adapter.list_page(window, "same")
        assert nxt is None
        assert len(items) == 1
        assert items[0].conversation_id == "c1"
        assert captured_url == [RETELL_LIST_CALLS_URL]
    finally:
        retell_mod.requests.post = original


def test_retell_list_chat_uses_v3_endpoint():
    from app.services.voice_providers.historical.base import TimeSlice
    from app.services.voice_providers.historical.retell import (
        RETELL_LIST_CHATS_URL,
        RetellHistoricalAdapter,
    )

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [{"chat_id": "chat_1", "start_timestamp": 1000, "end_timestamp": 2000}],
                "has_more": False,
            }

    adapter = RetellHistoricalAdapter.__new__(RetellHistoricalAdapter)
    adapter._api_key = "k"
    import app.services.voice_providers.historical.retell as retell_mod

    captured_url: list[str] = []
    original = retell_mod.requests.post
    retell_mod.requests.post = lambda url, *a, **k: (captured_url.append(url), _Resp())[1]
    try:
        window = TimeSlice(
            slice_id=0,
            slice_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            slice_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
            medium="chat",
        )
        items, nxt = adapter.list_page(window, None)
        assert nxt is None
        assert len(items) == 1
        assert items[0].conversation_id == "chat_1"
        assert captured_url == [RETELL_LIST_CHATS_URL]
    finally:
        retell_mod.requests.post = original


def test_token_lua_does_not_record_denied_calls():
    from app.workers.concurrency.platform_import_limits import _TOKEN_LUA

    before_allow = _TOKEN_LUA.split("return 0", 1)[0]
    assert "ZADD" not in before_allow


def test_ninety_day_window_is_one_slice_per_day():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 1, tzinfo=timezone.utc)
    slices = plan_time_slices(start, end, None, tz_name="UTC")
    assert len(slices) == 90
    seen = set()
    for begin, finish, _agent in slices:
        assert begin < finish
        assert (begin, finish) not in seen
        seen.add((begin, finish))


class _FakeRedis:
    def __init__(self, depth: int = 0):
        self.values: dict[str, str] = {}
        self.depth = depth

    def eval(self, script: str, _numkeys: int, key: str, *args):
        current = self.values.get(key)
        if "current == false" in script:
            owner = args[0]
            if current is None or current == owner:
                self.values[key] = owner
                return 1
            return 0
        if "ARGV[2]" in script and "SET" in script:
            old, new = args[0], args[1]
            if current != old:
                return 0
            self.values[key] = new
            return 1
        if current == args[0]:
            del self.values[key]
            return 1
        return 0

    def get(self, key: str):
        return self.values.get(key)

    def delete(self, key: str):
        self.values.pop(key, None)
        return 1

    def llen(self, _key: str):
        return self.depth


def test_slice_lock_is_single_owner(monkeypatch):
    from app.workers.concurrency import platform_import_limits as limits

    fake = _FakeRedis()
    monkeypatch.setattr(limits, "_client", lambda: fake)
    import_id = uuid4()
    assert limits.acquire_slice_lock(import_id, 3, "owner-a") is True
    assert limits.acquire_slice_lock(import_id, 3, "owner-b") is False
    assert limits.acquire_slice_lock(import_id, 3, "owner-a") is True
    assert limits.transfer_slice_lock(import_id, 3, "owner-b", "owner-c") is False
    assert limits.transfer_slice_lock(import_id, 3, "owner-a", "owner-c") is True
    assert limits.slice_lock_owner(import_id, 3) == "owner-c"
    limits.release_slice_lock(import_id, 3, "owner-a")
    assert limits.slice_lock_owner(import_id, 3) == "owner-c"
    limits.release_slice_lock(import_id, 3, "owner-c")
    assert limits.slice_lock_owner(import_id, 3) is None


def test_discovery_enqueue_stops_when_queue_is_deep(monkeypatch):
    from app.workers.concurrency import platform_import_limits as limits

    fake = _FakeRedis(depth=500)
    monkeypatch.setattr(limits, "_client", lambda: fake)
    assert limits.discovery_enqueue_blocked() is True
    fake.depth = 0
    assert limits.discovery_enqueue_blocked() is False


def test_list_failure_retries_rate_limit_without_counting_attempt():
    class RateLimited(Exception):
        def __init__(self):
            self.response = SimpleNamespace(status_code=429, headers={"Retry-After": "12"})

    kind, wait = list_failure_disposition(RateLimited())
    assert kind == "retry"
    assert wait == 12


def test_list_failure_auth_does_not_fail_the_slice():
    class Denied(Exception):
        def __init__(self):
            self.response = SimpleNamespace(status_code=401, headers={})

    kind, wait = list_failure_disposition(Denied())
    assert kind == "auth"
    assert wait >= 30


def test_list_failure_timeout_retries():
    kind, wait = list_failure_disposition(TimeoutError("timed out"))
    assert kind == "retry"
    assert wait == 5


def test_discovery_blocks_terminal_status_while_running():
    batch = SimpleNamespace(source_format="platform", discovery_status="running")
    assert platform_discovery_blocks_terminal_status(batch) is True
    batch.discovery_status = "completed"
    assert platform_discovery_blocks_terminal_status(batch) is False
