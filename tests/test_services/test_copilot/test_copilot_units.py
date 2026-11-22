"""Copilot pieces that need no database: periods, status buckets, tool registry."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.core.auth.capabilities import ALL_CAPABILITIES, EVALS_VIEW, SIM_MANAGE
from app.services.copilot import registry
from app.services.copilot.periods import resolve_period
from app.services.copilot.registry import (
    CopilotTool,
    LLMChoice,
    ToolContext,
    ToolError,
    available_tools,
    execute,
    mcp_definition,
    openai_definition,
)
from app.services.copilot.tools.activity import status_bucket

# Sunday 2026-11-22 20:00 UTC == Monday 2026-11-23 01:30 in Kolkata.
NOW = datetime(2026, 11, 22, 20, 0, tzinfo=timezone.utc)


def _ctx(capabilities=ALL_CAPABILITIES):
    return ToolContext(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        capabilities=frozenset(capabilities),
        timezone="UTC",
        session_id=uuid4(),
        llm=LLMChoice(provider="openai", model="gpt-4o-mini", credential_id=None),
    )


class TestPeriods:
    def test_this_week_starts_monday_in_users_zone(self):
        utc = resolve_period("this_week", "UTC", now=NOW)
        assert utc.start == datetime(2026, 11, 16, tzinfo=timezone.utc)
        assert utc.end == datetime(2026, 11, 23, tzinfo=timezone.utc)
        # Already Monday in Kolkata, so "this week" is just today there.
        ist = resolve_period("this_week", "Asia/Kolkata", now=NOW)
        assert ist.as_dict()["start_local"] == "2026-11-23 00:00"
        assert ist.start == datetime(2026, 11, 22, 18, 30, tzinfo=timezone.utc)

    def test_last_week_and_last_month(self):
        last_week = resolve_period("last_week", "UTC", now=NOW)
        assert last_week.start == datetime(2026, 11, 9, tzinfo=timezone.utc)
        assert last_week.end == datetime(2026, 11, 16, tzinfo=timezone.utc)
        last_month = resolve_period("last_month", "UTC", now=NOW)
        assert last_month.start == datetime(2026, 10, 1, tzinfo=timezone.utc)
        assert last_month.end == datetime(2026, 11, 1, tzinfo=timezone.utc)

    def test_custom_range_is_inclusive_and_validated(self):
        custom = resolve_period(
            "custom", "UTC", start_date=date(2026, 11, 1), end_date=date(2026, 11, 3), now=NOW
        )
        assert custom.end == datetime(2026, 11, 4, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            resolve_period("custom", "UTC", now=NOW)
        with pytest.raises(ValueError):
            resolve_period("custom", "UTC", start_date=date(2026, 11, 5), end_date=date(2026, 11, 1))

    def test_unknown_zone_falls_back_to_utc(self):
        assert resolve_period("today", "Not/AZone", now=NOW).timezone == "UTC"


@pytest.mark.parametrize(
    "raw,bucket",
    [
        ("pending", "queued"),
        ("queued", "queued"),
        ("running", "in_progress"),
        ("call_in_progress", "in_progress"),
        ("completed", "completed"),
        ("failed", "failed"),
        ("auto_aborted", "in_progress"),
        ("cancelled", "cancelled"),
        (None, "in_progress"),
    ],
)
def test_status_buckets(raw, bucket):
    assert status_bucket(raw) == bucket


class TestRegistry:
    def test_tools_hidden_without_capability(self):
        names = {t.name for t in available_tools(frozenset())}
        assert names == {"search_docs"}  # the only tool needing no workspace capability
        assert "get_evaluation_activity" not in names
        assert "generate_test_setup" not in names
        names = {t.name for t in available_tools(frozenset({EVALS_VIEW, SIM_MANAGE}))}
        assert {"get_evaluation_activity", "generate_test_setup"} <= names

    def test_definitions_render_for_openai_and_mcp(self):
        tool = registry.get_tool("get_evaluation_activity")
        fn = openai_definition(tool)["function"]
        assert fn["name"] == "get_evaluation_activity"
        assert "period" in fn["parameters"]["properties"]
        assert "title" not in fn["parameters"]
        assert mcp_definition(tool)["inputSchema"] == fn["parameters"]

    def test_execute_refuses_tool_without_capability(self):
        result = execute(_ctx(frozenset()), "get_evaluation_activity", "{}", session_factory=_NoDB)
        assert result.status == "error" and result.error == "unknown_tool"

    def test_execute_reports_bad_arguments_to_model(self):
        result = execute(_ctx(), "get_evaluation_activity", '{"limit": 500}', session_factory=_NoDB)
        assert result.status == "error" and "limit" in result.content
        result = execute(_ctx(), "get_evaluation_activity", "{not json", session_factory=_NoDB)
        assert result.error == "bad_arguments"

    def test_tool_errors_and_crashes(self, monkeypatch):
        class Args(BaseModel):
            pass

        def boom_tool_error(ctx, db, args):
            raise ToolError("No agent 'x' in this workspace.")

        def boom_crash(ctx, db, args):
            raise RuntimeError("secret internal detail")

        monkeypatch.setitem(registry._REGISTRY, "t_err", CopilotTool("t_err", "d", Args, boom_tool_error))
        monkeypatch.setitem(registry._REGISTRY, "t_crash", CopilotTool("t_crash", "d", Args, boom_crash))
        assert execute(_ctx(), "t_err", {}, session_factory=_NoDB).content == "No agent 'x' in this workspace."
        crashed = execute(_ctx(), "t_crash", {}, session_factory=_NoDB)
        assert crashed.status == "error" and "secret" not in crashed.content

    def test_large_results_are_truncated(self, monkeypatch):
        class Args(BaseModel):
            pass

        monkeypatch.setitem(
            registry._REGISTRY,
            "t_big",
            CopilotTool("t_big", "d", Args, lambda ctx, db, args: {"x": "y" * 50_000}),
        )
        result = execute(_ctx(), "t_big", {}, session_factory=_NoDB)
        assert len(result.content) < 13_000 and "truncated" in result.content


class _NoDB:
    """Stands in for a Session in tests that never query."""

    def get_bind(self):
        return None

    def close(self):
        pass
