"""HTTP, MCP and Postgres tool providers, and the read/write classifier."""

import json
import sys
from pathlib import Path

import httpx
import pytest

import app.services.tools.providers.http as http_mod
from app.services.tools.base import classify_side_effect
from app.services.tools.toolset import Toolset

MCP_SERVER = Path(__file__).parent / "fixtures" / "order_mcp_server.py"


@pytest.mark.parametrize(
    "name,hints,expected",
    [
        ("search_messages", {}, "read"),
        ("list_channels", {}, "read"),
        ("get_settings", {}, "read"),
        ("post_message", {}, "write"),
        ("postMessage", {}, "write"),
        ("send-email", {}, "write"),
        ("notion_update_page", {}, "write"),
        ("post_message", {"read_only_hint": True}, "read"),
        ("fetch_page", {"destructive_hint": True}, "write"),
        ("fetch_page", {"read_only_hint": False}, "write"),
    ],
)
def test_classify_side_effect(name, hints, expected):
    assert classify_side_effect(name, **hints) == expected


@pytest.fixture
def http_calls(monkeypatch):
    """Route the provider's httpx.Client through a MockTransport; returns the seen requests."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/orders/404":
            return httpx.Response(404, text="no such order")
        return httpx.Response(
            200, json={"path": request.url.path, "query": dict(request.url.params)}
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        http_mod.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        "app.services.telephony.recording_download.assert_outbound_http_url_safe",
        lambda url, **_: None,
    )
    return seen


def _http_provider(**kw):
    config = {
        "base_url": "https://api.example.com",
        "tools": [
            {
                "name": "get_order",
                "method": "GET",
                "path": "/orders/{order_id}",
                "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},
            },
            {"name": "refund", "method": "POST", "path": "/refunds"},
        ],
    }
    return http_mod.HttpToolProvider(
        name="Orders API",
        prefix="orders",
        config=config,
        secrets={"headers": {"Authorization": "Bearer s3cret"}},
        **kw,
    )


def test_http_provider_fills_path_and_query(http_calls):
    provider = _http_provider()
    assert [s.name for s in provider.list_tools()] == ["orders__get_order", "orders__refund"]
    assert [s.side_effect for s in provider.list_tools()] == ["read", "write"]

    result = provider.call("orders__get_order", {"order_id": "A 1", "verbose": True})
    assert not result.is_error
    assert json.loads(result.content) == {"path": "/orders/A 1", "query": {"verbose": "true"}}
    assert http_calls[0].headers["Authorization"] == "Bearer s3cret"

    missing = provider.call("orders__get_order", {"order_id": "404"})
    assert missing.is_error and "HTTP 404" in missing.content
    assert provider.call("orders__get_order", {}).is_error  # missing path argument


def test_http_write_tool_mocked_in_simulation(http_calls):
    toolset = Toolset([_http_provider()])
    _, record = toolset.execute("orders__refund", {"amount": 10})
    assert record.status == "mocked"
    assert http_calls == []


def test_http_provider_blocks_private_networks(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DEBUG", False)
    provider = http_mod.HttpToolProvider(
        name="internal",
        prefix="internal",
        config={"tools": [{"name": "meta", "url": "http://169.254.169.254/latest"}]},
        secrets={},
    )
    result = provider.call("internal__meta", {})
    assert result.is_error and "not sent" in result.content


def test_invalid_http_tools_rejected():
    with pytest.raises(ValueError, match="at least one"):
        http_mod.validate_http_tools({"tools": []})
    with pytest.raises(ValueError, match="Invalid tool name"):
        http_mod.validate_http_tools({"tools": [{"name": "bad name", "url": "https://x"}]})


@pytest.fixture
def stdio_allowed(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TOOL_CONNECTIONS_ALLOW_STDIO", True)


def _mcp_config():
    return {"transport": "stdio", "command": sys.executable, "args": [str(MCP_SERVER)]}


def test_mcp_discovery_and_calls_over_stdio(stdio_allowed):
    from app.services.tools.providers.mcp import McpToolProvider, discover_mcp_tools

    tools = discover_mcp_tools(_mcp_config(), {}, timeout=30)
    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == {"lookup_order", "send_message"}
    assert by_name["lookup_order"]["read_only_hint"] is True
    assert by_name["lookup_order"]["input_schema"]["required"] == ["order_id"]

    provider = McpToolProvider(
        name="Orders MCP", prefix="orders", config=_mcp_config(), secrets={}, cached_tools=tools
    )
    toolset = Toolset([provider])
    try:
        # One session serves several calls; a tool error comes back as an error result.
        ok, ok_record = toolset.execute("orders__lookup_order", {"order_id": "4411"})
        missing, missing_record = toolset.execute("orders__lookup_order", {"order_id": "missing"})
        _, write_record = toolset.execute("orders__send_message", {"channel": "#ops", "text": "hi"})
    finally:
        toolset.close()

    assert ok_record.status == "ok" and "shipped" in ok.content
    assert missing_record.status == "error" and "order not found" in missing.content
    assert write_record.status == "mocked"


def test_mcp_enabled_tools_filter(stdio_allowed):
    from app.services.tools.providers.mcp import McpToolProvider

    cached = [
        {"name": "lookup_order", "input_schema": {"type": "object"}, "read_only_hint": True},
        {"name": "send_message", "input_schema": {"type": "object"}},
    ]
    provider = McpToolProvider(
        name="x",
        prefix="x",
        config=_mcp_config(),
        secrets={},
        cached_tools=cached,
        enabled_tools=["lookup_order"],
    )
    assert [s.name for s in provider.list_tools()] == ["x__lookup_order"]


def test_mcp_stdio_disabled_by_default():
    from app.services.tools.providers.mcp import McpConnectionError, assert_transport_allowed

    with pytest.raises(McpConnectionError, match="disabled"):
        assert_transport_allowed(_mcp_config())


def test_postgres_guards(monkeypatch):
    from app.config import settings
    from app.services.tools.providers.postgres import (
        _single_statement,
        assert_dsn_host_allowed,
        normalize_dsn,
    )

    assert _single_statement(" select 1; ") == "select 1"
    with pytest.raises(ValueError, match="one statement"):
        _single_statement("select 1; drop table users")
    assert normalize_dsn("postgres://u:p@db.example.com/app").startswith(
        "postgresql+psycopg2://u:p@"
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_dsn("mysql://u:p@db.example.com/app")
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(Exception, match="blocked"):
        assert_dsn_host_allowed("postgresql://u:p@10.0.0.5/app")
    with pytest.raises(ValueError, match="hostaddr"):
        assert_dsn_host_allowed(
            "postgresql://u:p@8.8.8.8/app?hostaddr=10.0.0.5"
        )
