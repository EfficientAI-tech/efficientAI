"""Tests for call-import STT token bucket."""

from unittest.mock import MagicMock, patch

import pytest
import redis

from app.workers.concurrency import stt_token_bucket as bucket


@pytest.fixture(autouse=True)
def reset_redis_client():
    bucket._redis = None
    yield
    bucket._redis = None


def test_consume_stt_token_fail_closed_on_redis_error():
    client = MagicMock()
    client.eval.side_effect = redis.RedisError("down")
    with patch.object(bucket, "_client", return_value=client):
        result = bucket.consume_stt_token("deepgram", member="task-1")
    assert result.allowed is False
    assert result.wait_seconds == 5


def test_consume_stt_token_respects_rpm_limit():
    client = MagicMock()
    client.eval.side_effect = [1, 1, 0]
    with patch.object(bucket, "_client", return_value=client):
        with patch.object(bucket, "stt_rpm_for_provider", return_value=2):
            first = bucket.consume_stt_token("deepgram", member="task-1")
            second = bucket.consume_stt_token("deepgram", member="task-2")
            third = bucket.consume_stt_token("deepgram", member="task-3")
    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.wait_seconds == 1
