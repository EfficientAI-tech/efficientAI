import pytest

from tests.helpers.eval_buffer_test_redis import (
    _redis_url_with_db,
    eval_buffer_test_redis_url,
)


@pytest.fixture
def default_eval_buffer_env(monkeypatch):
    """Default-value tests must not inherit CI/local ``EVAL_BUFFER_TEST_REDIS_URL``."""
    monkeypatch.delenv("EVAL_BUFFER_TEST_REDIS_URL", raising=False)


def test_eval_buffer_test_redis_url_serial_uses_base(default_eval_buffer_env):
    assert eval_buffer_test_redis_url("master") == "redis://localhost:6379/15"


def test_eval_buffer_test_redis_url_parallel_maps_worker_to_db(default_eval_buffer_env):
    assert eval_buffer_test_redis_url("gw0") == "redis://localhost:6379/1"
    assert eval_buffer_test_redis_url("gw14") == "redis://localhost:6379/15"


def test_eval_buffer_test_redis_url_respects_configured_host(monkeypatch):
    monkeypatch.setenv("EVAL_BUFFER_TEST_REDIS_URL", "redis://redis:6379/15")
    assert eval_buffer_test_redis_url("master") == "redis://redis:6379/15"
    assert eval_buffer_test_redis_url("gw0") == "redis://redis:6379/1"


def test_redis_url_with_db_preserves_query_options(monkeypatch):
    monkeypatch.setenv(
        "EVAL_BUFFER_TEST_REDIS_URL",
        "redis://localhost:6379/15?db=15&socket_timeout=0.2",
    )
    url = eval_buffer_test_redis_url("gw2")
    assert url.startswith("redis://localhost:6379/3?")
    assert "socket_timeout=0.2" in url
    assert "db=3" in url
    assert "/3/3" not in url


def test_redis_url_with_db_simple_path():
    assert _redis_url_with_db("redis://127.0.0.1:6379/15", 1) == "redis://127.0.0.1:6379/1"