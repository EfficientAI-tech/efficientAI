"""Read-only Postgres access for agents that look up data (orders, accounts, ...).

Every statement runs inside ``SET TRANSACTION READ ONLY`` with a statement timeout,
so a write attempted by the model fails in the database, not just in our checks.
Secrets: ``{"dsn": "postgresql://user:pass@host:5432/db"}``. Config: optional
``schemas`` allow-list (default ``["public"]``) and ``max_rows`` (default 50).
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from app.services.tools.base import SIDE_EFFECT_READ, SIM_MODE_LIVE, ToolResult, ToolSpec

DEFAULT_MAX_ROWS = 50
STATEMENT_TIMEOUT_MS = 10000
MAX_RESULT_CHARS = 12000

POSTGRES_TOOLS = [
    {
        "name": "list_tables",
        "description": "List the tables you can query, with their schema.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_table",
        "description": "Columns and types of one table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name, optionally schema.table"}
            },
            "required": ["table"],
        },
    },
    {
        "name": "query",
        "description": (
            "Run one read-only SQL SELECT and get the rows back as JSON. "
            "Always add a WHERE clause or LIMIT."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["sql"],
        },
    },
]


def tool_entries_for_postgres() -> list[dict[str, Any]]:
    return [{**tool, "read_only_hint": True, "destructive_hint": None} for tool in POSTGRES_TOOLS]


def normalize_dsn(dsn: str) -> str:
    """psycopg2 SQLAlchemy URL from a ``postgres://`` / ``postgresql://`` DSN."""
    raw = dsn.strip()
    if raw.startswith("postgres://"):  # Heroku / Supabase / Neon style
        raw = "postgresql://" + raw[len("postgres://") :]
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Only PostgreSQL connection strings are supported")
    return url.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


def assert_dsn_host_allowed(dsn: str) -> None:
    from app.config import settings
    from app.services.telephony.recording_download import assert_outbound_http_url_safe

    url = make_url(dsn.strip())
    if not url.host:
        raise ValueError("Connection string needs a host")
    # Same private-network / metadata blocklist as other user-configured endpoints.
    assert_outbound_http_url_safe(f"http://{url.host}", allow_loopback=bool(settings.DEBUG))


def _single_statement(sql: str) -> str:
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("SQL is empty")
    if ";" in stripped:
        raise ValueError("Send one statement at a time")
    return stripped


class PostgresToolProvider:
    def __init__(
        self,
        *,
        name: str,
        prefix: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
        enabled_tools: Optional[list[str]] = None,
        simulation_mode: str = SIM_MODE_LIVE,
        timeout: float = 30.0,
    ):
        self.name = name
        self.simulation_mode = simulation_mode
        self.prefix = prefix
        self.dsn = secrets.get("dsn") or ""
        self.schemas = list(config.get("schemas") or ["public"])
        self.max_rows = int(config.get("max_rows") or DEFAULT_MAX_ROWS)
        self.timeout = timeout
        enabled = set(enabled_tools) if enabled_tools is not None else None
        self._tools = {
            f"{prefix}__{tool['name']}": tool
            for tool in POSTGRES_TOOLS
            if enabled is None or tool["name"] in enabled
        }
        self._engine: Optional[Engine] = None
        self._lock = threading.Lock()

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=exposed,
                description=tool["description"],
                parameters=tool["input_schema"],
                provider=self.name,
                side_effect=SIDE_EFFECT_READ,
            )
            for exposed, tool in self._tools.items()
        ]

    def _get_engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                assert_dsn_host_allowed(self.dsn)
                self._engine = create_engine(
                    normalize_dsn(self.dsn),
                    poolclass=NullPool,
                    connect_args={"connect_timeout": int(min(self.timeout, 30))},
                )
            return self._engine

    def _read_only(self, sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        with self._get_engine().connect() as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
                result = conn.execute(text(sql), params or {})
                rows = result.mappings().fetchmany(self.max_rows + 1)
        return [dict(row) for row in rows]

    def _format(self, rows: list[dict[str, Any]]) -> str:
        truncated = len(rows) > self.max_rows
        body = json.dumps(rows[: self.max_rows], default=str)
        if truncated:
            body += f"\n(only the first {self.max_rows} rows are shown)"
        return body if len(body) <= MAX_RESULT_CHARS else body[:MAX_RESULT_CHARS] + "…"

    def call(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(f"Unknown tool: {tool_name}", is_error=True)
        try:
            if tool["name"] == "list_tables":
                rows = self._read_only(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ANY(:schemas) ORDER BY 1, 2",
                    {"schemas": self.schemas},
                )
            elif tool["name"] == "describe_table":
                raw = str(arguments.get("table") or "").strip()
                schema, _, table = raw.rpartition(".")
                if schema and schema not in self.schemas:
                    return ToolResult(f"Schema {schema} is not allowed", is_error=True)
                rows = self._read_only(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = :table AND table_schema = ANY(:schemas) "
                    "ORDER BY ordinal_position",
                    {"table": table, "schemas": [schema] if schema else self.schemas},
                )
                if not rows:
                    return ToolResult(f"Table {raw} not found", is_error=True)
            else:
                rows = self._read_only(_single_statement(str(arguments.get("sql") or "")))
        except Exception as exc:
            message = str(getattr(exc, "orig", None) or exc).strip().splitlines()[0]
            return ToolResult(f"Query failed: {message}", is_error=True)
        return ToolResult(self._format(rows), extra={"row_count": min(len(rows), self.max_rows)})

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is not None:
            engine.dispose()
