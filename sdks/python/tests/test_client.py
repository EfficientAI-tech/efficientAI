from __future__ import annotations

import httpx
import pytest
import respx

from efficientai_sdk import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncEfficientAI,
    AuthenticationError,
    EfficientAI,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    UnprocessableEntityError,
    __version__,
)

from .conftest import BASE_URL

VALIDATE = f"{BASE_URL}/api/v1/auth/validate"


def make_client(**kwargs: object) -> EfficientAI:
    return EfficientAI(api_key="test-key", base_url=BASE_URL, **kwargs)  # type: ignore[arg-type]


# ---- headers and verify ------------------------------------------------


@respx.mock
def test_verify_honours_custom_api_prefix() -> None:
    route = respx.post(f"{BASE_URL}/api/auth/validate").respond(200, json={"valid": True})
    make_client(api_prefix="/api").verify()
    assert route.called


@respx.mock
def test_verify_sends_auth_headers() -> None:
    route = respx.post(VALIDATE).respond(200, json={"valid": True})
    with make_client(workspace_id="ws-123") as client:
        assert client.verify() is True
    req = route.calls.last.request
    assert req.headers["X-API-Key"] == "test-key"
    assert req.headers["X-Workspace-Id"] == "ws-123"
    assert req.headers["User-Agent"].startswith(f"efficientai-sdk-python/{__version__}")


@respx.mock
def test_workspace_header_omitted_when_unset() -> None:
    route = respx.post(VALIDATE).respond(200, json={"valid": True})
    make_client().verify()
    assert "X-Workspace-Id" not in route.calls.last.request.headers


@respx.mock
def test_verify_bad_key_raises_authentication_error() -> None:
    respx.post(VALIDATE).respond(401, json={"detail": "Invalid API key"})
    with pytest.raises(AuthenticationError) as info:
        make_client().verify()
    assert info.value.status_code == 401
    assert "Invalid API key" in str(info.value)


# ---- response handling -------------------------------------------------


@respx.mock
def test_returns_parsed_json_and_none_for_204() -> None:
    respx.get(f"{BASE_URL}/api/v1/things").respond(200, json={"a": 1})
    respx.delete(f"{BASE_URL}/api/v1/things/1").respond(204)
    client = make_client()
    assert client.request("GET", "/api/v1/things") == {"a": 1}
    assert client.request("DELETE", "/api/v1/things/1") is None


@respx.mock
def test_validation_error_message_is_readable() -> None:
    respx.post(f"{BASE_URL}/api/v1/x").respond(
        422,
        json={
            "detail": [{"loc": ["body", "agent_id"], "msg": "field required", "type": "missing"}]
        },
    )
    with pytest.raises(UnprocessableEntityError, match="agent_id: field required"):
        make_client().request("POST", "/api/v1/x", json={})


@respx.mock
def test_unmapped_status_and_request_id() -> None:
    respx.get(f"{BASE_URL}/api/v1/x").respond(418, text="teapot", headers={"x-request-id": "req-1"})
    with pytest.raises(APIStatusError) as info:
        make_client().request("GET", "/api/v1/x")
    assert type(info.value) is APIStatusError
    assert info.value.request_id == "req-1"
    assert info.value.body == "teapot"


@respx.mock
def test_404_maps_to_not_found() -> None:
    respx.get(f"{BASE_URL}/api/v1/x").respond(404, json={"detail": "Not found"})
    with pytest.raises(NotFoundError):
        make_client().request("GET", "/api/v1/x")


# ---- retries -----------------------------------------------------------


@respx.mock
def test_get_retries_5xx_then_succeeds(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").mock(
        side_effect=[httpx.Response(502), httpx.Response(503), httpx.Response(200, json={"ok": 1})]
    )
    assert make_client().request("GET", "/api/v1/x") == {"ok": 1}
    assert route.call_count == 3
    assert len(sleeps) == 2


@respx.mock
def test_gives_up_after_max_retries(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").respond(500, json={"detail": "boom"})
    with pytest.raises(InternalServerError, match="boom"):
        make_client(max_retries=2).request("GET", "/api/v1/x")
    assert route.call_count == 3


@respx.mock
def test_max_retries_zero_disables_retries(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").respond(503)
    with pytest.raises(InternalServerError):
        make_client(max_retries=0).request("GET", "/api/v1/x")
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_post_not_retried_on_500(sleeps: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/x").respond(500)
    with pytest.raises(InternalServerError):
        make_client().request("POST", "/api/v1/x", json={})
    assert route.call_count == 1


@respx.mock
def test_post_retried_when_forced(sleeps: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/x").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={})]
    )
    make_client().request("POST", "/api/v1/x", json={}, retry=True)
    assert route.call_count == 2


@respx.mock
def test_retry_false_disables_retries(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").respond(503)
    with pytest.raises(InternalServerError):
        make_client().request("GET", "/api/v1/x", retry=False)
    assert route.call_count == 1


@respx.mock
def test_429_honours_retry_after(sleeps: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/x").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "3"}),
            httpx.Response(200, json={}),
        ]
    )
    make_client().request("POST", "/api/v1/x", json={})
    assert route.call_count == 2
    assert sleeps == [3.0]


@respx.mock
def test_retry_after_is_capped(sleeps: list[float]) -> None:
    respx.get(f"{BASE_URL}/api/v1/x").mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "3600"}), httpx.Response(200)]
    )
    make_client().request("GET", "/api/v1/x")
    assert sleeps == [60.0]


@respx.mock
def test_rate_limit_error_exposes_retry_after(sleeps: list[float]) -> None:
    respx.get(f"{BASE_URL}/api/v1/x").respond(429, headers={"retry-after": "7"})
    with pytest.raises(RateLimitError) as info:
        make_client(max_retries=0).request("GET", "/api/v1/x")
    assert info.value.retry_after == 7.0


def test_connect_timeout_retries_writes_read_timeout_does_not() -> None:
    connect = httpx.ConnectTimeout("opening")
    read = httpx.ReadTimeout("reading")
    assert EfficientAI._should_retry_exception("POST", connect, None) is True
    assert EfficientAI._should_retry_exception("PATCH", connect, None) is True
    assert EfficientAI._should_retry_exception("POST", read, None) is False
    assert EfficientAI._should_retry_exception("GET", read, None) is True


def test_backoff_grows_and_stays_bounded() -> None:
    delays = [EfficientAI._retry_delay(attempt, None) for attempt in range(10)]
    assert 0.25 <= delays[0] <= 0.5
    assert all(d <= 8.0 for d in delays)


@respx.mock
def test_connect_error_retried_even_for_post(sleeps: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/x").mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json={})]
    )
    make_client().request("POST", "/api/v1/x", json={})
    assert route.call_count == 2


@respx.mock
def test_read_timeout_on_post_not_retried(sleeps: list[float]) -> None:
    route = respx.post(f"{BASE_URL}/api/v1/x").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(APITimeoutError):
        make_client().request("POST", "/api/v1/x", json={})
    assert route.call_count == 1


@respx.mock
def test_connection_error_after_retries(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(APIConnectionError):
        make_client(max_retries=1).request("GET", "/api/v1/x")
    assert route.call_count == 2


# ---- http client ownership --------------------------------------------


def test_injected_http_client_is_not_closed() -> None:
    http = httpx.Client()
    client = EfficientAI(api_key="k", base_url=BASE_URL, http_client=http)
    client.close()
    assert not http.is_closed
    http.close()


# ---- async -------------------------------------------------------------


@respx.mock
async def test_async_verify_and_headers() -> None:
    route = respx.post(VALIDATE).respond(200, json={"valid": True})
    async with AsyncEfficientAI(api_key="test-key", base_url=BASE_URL, workspace_id="ws") as client:
        assert await client.verify() is True
    assert route.calls.last.request.headers["X-Workspace-Id"] == "ws"


@respx.mock
async def test_async_retries_then_raises(sleeps: list[float]) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/x").respond(503)
    client = AsyncEfficientAI(api_key="k", base_url=BASE_URL, max_retries=1)
    with pytest.raises(InternalServerError):
        await client.request("GET", "/api/v1/x")
    assert route.call_count == 2
    assert len(sleeps) == 1
    await client.close()


@respx.mock
async def test_async_bad_key() -> None:
    respx.post(VALIDATE).respond(401, json={"detail": "Invalid API key"})
    client = AsyncEfficientAI(api_key="bad", base_url=BASE_URL)
    with pytest.raises(AuthenticationError):
        await client.verify()
    await client.close()
