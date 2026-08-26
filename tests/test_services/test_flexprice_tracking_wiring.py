"""Catalog tests: Flexprice event wiring expectations by product area."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

VOICE_PLAYGROUND_WIRED = {
    "blind_test.share_created": "app/api/v1/routes/voice_playground.py",
    "blind_test.response_submitted": "app/api/v1/routes/public_blind_test.py",
    "tts.generation_started": "app/api/v1/routes/voice_playground.py",
    "tts.sample_synthesized": "app/workers/tasks/tts_comparison.py",
    "tts.report_requested": "app/api/v1/routes/voice_playground.py",
    "tts.report_completed": "app/workers/tasks/tts_report.py",
}

AGENT_PLAYGROUND_WIRED = {
    "playground.web_call_started": "app/api/v1/routes/playground.py",
    "playground.websocket_session_started": "app/api/v1/routes/playground.py",
    "playground.evaluation_completed": "app/workers/tasks/process_evaluator_result.py",
    "test_agent.conversation_ended": "app/api/v1/routes/test_agents.py",
}

EVALUATORS_WIRED = {
    "evaluator.run_requested": "app/api/v1/routes/evaluators.py",
    "evaluator.run_completed": "app/workers/tasks/process_evaluator_result.py",
}

JUDGE_ALIGNMENT_WIRED = {
    "judge_alignment.run_started": "app/api/v1/routes/judge_alignment.py",
    "judge_alignment.run_completed": "app/workers/tasks/run_judge_alignment.py",
}

METRICS_AI_ASSIST_WIRED = {
    "metrics.ai_assist": "app/api/v1/routes/metrics.py",
}

METRIC_STUDIO_WIRED = {
    "metric_studio.item_evaluated": "app/workers/tasks/evaluate_studio_run_item.py",
    "metric_studio.run_completed": "app/services/metric_studio/run_rollup.py",
}

SCENARIO_AI_WIRED = {
    "scenario.ai_text_generated": [
        "app/api/v1/routes/chat.py",
        "app/api/v1/routes/agents.py",
    ],
}


def _file_contains(path: str, needle: str) -> bool:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    return needle in text


def test_voice_playground_events_are_wired():
    for event_name, path in VOICE_PLAYGROUND_WIRED.items():
        record_fn = {
            "blind_test.share_created": "record_blind_test_share_created",
            "blind_test.response_submitted": "record_blind_test_response_submitted",
            "tts.generation_started": "record_tts_generation_started",
            "tts.sample_synthesized": "record_tts_sample_synthesized",
            "tts.report_requested": "record_tts_report_requested",
            "tts.report_completed": "record_tts_report_completed",
        }[event_name]
        assert _file_contains(path, record_fn), f"{event_name} missing {record_fn} in {path}"


def test_agent_playground_events_are_wired():
    for event_name, path in AGENT_PLAYGROUND_WIRED.items():
        record_fn = {
            "playground.web_call_started": "record_playground_web_call_started",
            "playground.websocket_session_started": "record_playground_websocket_session_started",
            "playground.evaluation_completed": "record_playground_evaluation_completed",
            "test_agent.conversation_ended": "record_test_agent_conversation_ended",
        }[event_name]
        assert _file_contains(path, record_fn), f"{event_name} missing {record_fn} in {path}"


def test_evaluator_events_are_wired():
    for event_name, path in EVALUATORS_WIRED.items():
        record_fn = {
            "evaluator.run_requested": "record_evaluator_run_requested",
            "evaluator.run_completed": "record_evaluator_run_completed",
        }[event_name]
        assert _file_contains(path, record_fn), f"{event_name} missing {record_fn} in {path}"


def test_judge_alignment_events_are_wired():
    for event_name, path in JUDGE_ALIGNMENT_WIRED.items():
        record_fn = {
            "judge_alignment.run_started": "record_judge_alignment_run_started",
            "judge_alignment.run_completed": "record_judge_alignment_run_completed",
        }[event_name]
        assert _file_contains(path, record_fn), f"{event_name} missing {record_fn} in {path}"


def test_metrics_ai_assist_events_are_wired():
    for event_name, path in METRICS_AI_ASSIST_WIRED.items():
        assert _file_contains(path, "record_metrics_llm_assist"), (
            f"{event_name} missing record_metrics_llm_assist in {path}"
        )


def test_metric_studio_events_are_wired():
    for event_name, path in METRIC_STUDIO_WIRED.items():
        record_fn = {
            "metric_studio.item_evaluated": "record_metric_studio_item_evaluated",
            "metric_studio.run_completed": "record_metric_studio_run_completed",
        }[event_name]
        assert _file_contains(path, record_fn), f"{event_name} missing {record_fn} in {path}"


def test_scenario_ai_text_events_are_wired():
    for event_name, paths in SCENARIO_AI_WIRED.items():
        for path in paths:
            assert _file_contains(path, "record_scenario_ai_text_generated") or _file_contains(
                path, "record_chat_completion"
            ), f"{event_name} missing scenario flexprice hook in {path}"
