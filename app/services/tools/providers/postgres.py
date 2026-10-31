"""Read-only Postgres access for agents that look up data (orders, accounts, ...).

Every statement runs inside ``SET TRANSACTION READ ONLY`` with a statement timeout,
so a write attempted by the model fails in the database, not just in our checks.
Secrets: ``{"dsn": "postgresql://user:pass@host:5432/db"}``. Config: optional
``schemas`` allow-list (default ``["public"]``) and ``max_rows`` (default 50).
"""

from __future__ import annotations

import json
import re
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
        "description": (
            "List the tables you can query. Call this at most once per conversation, "
            "then query. Do not call it again if you already know the table names."
        ),
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
            "Always add a WHERE clause or LIMIT. After the rows come back, "
            "answer the customer instead of calling more tools."
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

    raw = dsn.strip()
    url = make_url(raw)
    if not url.host:
        raise ValueError("Connection string needs a host")
    assert_outbound_http_url_safe(f"http://{url.host}", allow_loopback=bool(settings.DEBUG))

    query = url.query if isinstance(url.query, dict) else {}
    if not query and url.query:
        for part in str(url.query).split("&"):
            if "=" in part:
                key, _value = part.split("=", 1)
                query[key.lower()] = _value
    for override in ("hostaddr", "host"):
        if override in {k.lower() for k in query}:
            raise ValueError(
                f"Connection string must not override the host via {override}"
            )


def _single_statement(sql: str) -> str:
    stripped = (sql or "").strip().rstrip(";").strip()
    if not stripped:
        raise ValueError("SQL is empty")
    if ";" in stripped:
        raise ValueError("Send one statement at a time")
    return stripped


_FORBIDDEN_SQL_SCHEMAS = frozenset({"pg_catalog", "information_schema"})
_FROM_OR_JOIN = re.compile(r"\b(?:from|join)\b", re.IGNORECASE)
_TABLE_PREFIX_WORDS = frozenset({"only", "lateral"})
_FROM_STOP_WORDS = frozenset({
    "where",
    "group",
    "order",
    "limit",
    "union",
    "except",
    "intersect",
    "window",
    "having",
    "offset",
    "fetch",
    "for",
    "join",
    "inner",
    "left",
    "right",
    "full",
    "cross",
    "natural",
    "on",
    "using",
})
_IDENT = re.compile(r'"([^"]+)"|([A-Za-z_][\w$]*)')


def _mask_sql_strings_and_comments(sql: str) -> str:
    """Blank string literals and comments so schema checks ignore them."""
    out: list[str] = []
    i = 0
    length = len(sql)
    while i < length:
        if sql.startswith("--", i):
            while i < length and sql[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = length if end < 0 else end + 2
            out.extend(" " * (end - i))
            i = end
            continue
        if sql[i] == "'":
            out.append(" ")
            i += 1
            while i < length:
                if sql[i] == "'" and i + 1 < length and sql[i + 1] == "'":
                    out.extend("  ")
                    i += 2
                    continue
                ch = sql[i]
                out.append(" ")
                i += 1
                if ch == "'":
                    break
            continue
        out.append(sql[i])
        i += 1
    return "".join(out)


def _skip_ws(sql: str, index: int) -> int:
    while index < len(sql) and sql[index].isspace():
        index += 1
    return index


def _read_ident(sql: str, index: int) -> tuple[str, int] | None:
    match = _IDENT.match(sql, index)
    if match is None:
        return None
    return (match.group(1) or match.group(2)), match.end()


def _skip_table_alias(sql: str, index: int) -> int:
    index = _skip_ws(sql, index)
    ident = _read_ident(sql, index)
    if ident is None:
        return index
    name, end = ident
    lowered = name.lower()
    if lowered in _FROM_STOP_WORDS:
        return index
    if lowered == "as":
        index = _skip_ws(sql, end)
        alias = _read_ident(sql, index)
        return alias[1] if alias is not None else index
    return end


def _schemas_named_in_query(sql: str) -> list[str]:
    """Schema qualifiers on table refs and ``schema.func(`` calls."""
    masked = _mask_sql_strings_and_comments(sql)
    found: list[str] = []
    for match in re.finditer(
        r'(?:"([^"]+)"|([A-Za-z_][\w$]*))\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*)\s*\(',
        masked,
    ):
        found.append((match.group(1) or match.group(2)).lower())

    for match in _FROM_OR_JOIN.finditer(masked):
        index = match.end()
        while index < len(masked):
            index = _skip_ws(masked, index)
            if index >= len(masked) or masked[index] == "(":
                break
            ident = _read_ident(masked, index)
            if ident is None:
                break
            name, index = ident
            if name.lower() in _TABLE_PREFIX_WORDS:
                continue
            index = _skip_ws(masked, index)
            if index < len(masked) and masked[index] == ".":
                found.append(name.lower())
                index += 1
                index = _skip_ws(masked, index)
                second = _read_ident(masked, index)
                if second is not None:
                    index = second[1]
            index = _skip_table_alias(masked, index)
            index = _skip_ws(masked, index)
            if index < len(masked) and masked[index] == ",":
                index += 1
                continue
            break
    return found


def _assert_query_uses_allowed_schemas(sql: str, allowed_schemas: list[str]) -> None:
    masked = _mask_sql_strings_and_comments(sql)
    lowered = masked.lower()
    for blocked in _FORBIDDEN_SQL_SCHEMAS:
        if re.search(rf"\b{blocked}\b", lowered):
            raise ValueError(f"Schema {blocked} is not allowed")
    allowed = {schema.lower() for schema in allowed_schemas}
    for schema in _schemas_named_in_query(sql):
        if schema not in allowed:
            raise ValueError(f"Schema {schema} is not allowed")


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
                schemas_sql = ", ".join(
                    f'"{schema.replace(chr(34), "")}"' for schema in self.schemas
                )
                conn.execute(text(f"SET LOCAL search_path TO {schemas_sql}"))
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
                sql = _single_statement(str(arguments.get("sql") or ""))
                if not sql.lstrip().lower().startswith("select"):
                    return ToolResult("Only SELECT queries are allowed", is_error=True)
                _assert_query_uses_allowed_schemas(sql, self.schemas)
                rows = self._read_only(sql)
        except Exception as exc:
            message = str(getattr(exc, "orig", None) or exc).strip().splitlines()[0]
            return ToolResult(f"Query failed: {message}", is_error=True)
        return ToolResult(self._format(rows), extra={"row_count": min(len(rows), self.max_rows)})

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is not None:
            engine.dispose()
