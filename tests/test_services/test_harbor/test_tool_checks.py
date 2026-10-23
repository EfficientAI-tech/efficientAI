"""Deterministic tool-use checks and the judge's tool section."""

import pytest

from app.services.harbor.tool_checks import check_tool_calls, format_tool_calls_for_judge


def _call(tool, status="ok", side="production", turn=1, **arguments):
    return {
        "tool": tool,
        "status": status,
        "side": side,
        "turn_index": turn,
        "arguments": arguments,
        "result_preview": f"{tool} result",
        "hit_count": arguments.pop("hits", None),
    }


CALLS = [
    _call("search_knowledge_base", query="Refund policy for late orders", hits=3),
    _call("search_knowledge_base", query="shipping fees", hits=0),
    _call("postgres__query", status="error", sql="select 1"),
    _call("search_knowledge_base", side="test", query="ignored"),
]


def test_counts_only_production_calls():
    report = check_tool_calls(CALLS, None)
    assert report.total_calls == 3
    assert report.errored_calls == 1
    assert report.success_rate == pytest.approx(0.6667)
    assert report.kb_hit_rate == 0.5
    assert report.rewards() == {"tool_success_rate": 0.6667, "kb_retrieval_hit_rate": 0.5}
    assert report.as_dict()["all_expectations_met"] is None


@pytest.mark.parametrize(
    "expectation,satisfied",
    [
        ({"tool": "search_knowledge_base"}, True),
        ({"tool": "search_knowledge_base", "args_contains": {"query": "REFUND"}}, True),
        ({"tool": "search_knowledge_base", "args_contains": {"query": "warranty"}}, False),
        ({"tool": "search_knowledge_base", "min_calls": 3}, False),
        ({"tool": "search_knowledge_base", "max_calls": 1}, False),
        ({"tool": "postgres__query"}, True),
        ({"tool": "postgres__query", "must_succeed": True}, False),
        ({"tool": "slack__post_message", "forbidden": True}, True),
        ({"tool": "postgres__query", "forbidden": True}, False),
    ],
)
def test_expectations(expectation, satisfied):
    report = check_tool_calls(CALLS, [expectation])
    assert report.expectations[0]["satisfied"] is satisfied
    assert report.all_expectations_met is satisfied
    assert report.rewards()["tool_expectations_met"] == (1.0 if satisfied else 0.0)
    if not satisfied:
        assert report.expectations[0]["reason"]


def test_expectation_score_is_fraction_met():
    report = check_tool_calls(
        CALLS,
        [{"tool": "search_knowledge_base"}, {"tool": "postgres__query", "forbidden": True}],
    )
    assert report.expectation_score == 0.5
    assert report.forbidden_violations == 1


def test_judge_section():
    assert format_tool_calls_for_judge([]) == ""
    section = format_tool_calls_for_judge(CALLS[:1])
    assert section.startswith("## Tool Calls")
    assert "turn 1: search_knowledge_base" in section
    assert "→ ok: search_knowledge_base result" in section


def test_run_tool_summary():
    from types import SimpleNamespace

    from app.services.harbor.result_ingest import compute_tool_summary

    def _trial(calls, met=None):
        call_data = {"tool_calls": calls}
        if met is not None:
            call_data["tool_evaluation"] = {"all_expectations_met": met}
        return SimpleNamespace(id=object(), call_data=call_data)

    kb = {"tool": "search_knowledge_base", "provider": "knowledge_base", "latency_ms": 200}
    summary = compute_tool_summary(
        [
            _trial([{**kb, "status": "ok"}, {**kb, "status": "error"}], met=True),
            _trial([{**kb, "status": "ok", "latency_ms": 500}], met=False),
            _trial([]),
        ]
    )
    assert summary["total_calls"] == 3
    assert summary["success_rate"] == 0.6667
    assert summary["trials_with_calls"] == 2
    assert summary["expectations_met_rate"] == 0.5
    assert summary["tools"] == [
        {
            "tool": "search_knowledge_base",
            "provider": "knowledge_base",
            "calls": 3,
            "errors": 1,
            "mocked": 0,
            "error_rate": 0.3333,
            "avg_latency_ms": 300,
            "trials": 2,
        }
    ]
    assert compute_tool_summary([_trial([])]) is None
