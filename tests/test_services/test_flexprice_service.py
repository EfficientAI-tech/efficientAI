"""Unit tests for Flexprice billing service (optional metering)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.config import settings
from app.services.billing import flexprice_service as svc


@pytest.fixture(autouse=True)
def reset_flexprice_settings(monkeypatch):
    monkeypatch.setenv("FLEXPRICE_TEST_ALLOW", "1")
    previous = (
        settings.FLEXPRICE_ENABLED,
        settings.FLEXPRICE_API_KEY,
        settings.FLEXPRICE_API_HOST,
        settings.FLEXPRICE_AUTO_SUBSCRIBE,
        settings.FLEXPRICE_DEFAULT_PLAN_ID,
        settings.FLEXPRICE_DEFAULT_CURRENCY,
        settings.FLEXPRICE_DEFAULT_BILLING_PERIOD,
        svc._disabled_skip_logged,
    )
    svc._disabled_skip_logged = False
    yield
    (
        settings.FLEXPRICE_ENABLED,
        settings.FLEXPRICE_API_KEY,
        settings.FLEXPRICE_API_HOST,
        settings.FLEXPRICE_AUTO_SUBSCRIBE,
        settings.FLEXPRICE_DEFAULT_PLAN_ID,
        settings.FLEXPRICE_DEFAULT_CURRENCY,
        settings.FLEXPRICE_DEFAULT_BILLING_PERIOD,
        svc._disabled_skip_logged,
    ) = previous


def test_is_enabled_false_when_disabled():
    settings.FLEXPRICE_ENABLED = False
    settings.FLEXPRICE_API_KEY = "test-key"
    assert svc.is_enabled() is False


def test_is_enabled_false_when_api_key_missing():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = None
    assert svc.is_enabled() is False


def test_is_enabled_true_when_configured():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    assert svc.is_enabled() is True


def test_disabled_reason_when_api_key_missing():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = None
    assert svc.disabled_reason() is not None
    assert "api_key" in svc.disabled_reason()


@patch("flexprice.Flexprice")
def test_ensure_customer_no_op_when_disabled(mock_flexprice):
    settings.FLEXPRICE_ENABLED = False
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.ensure_customer(uuid4(), name="Acme")

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_ensure_customer_calls_create_customer(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    settings.FLEXPRICE_API_HOST = "https://us.api.flexprice.io/v1"

    org_id = uuid4()
    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.ensure_customer(org_id, name="Acme Inc", email="admin@acme.com")

    mock_flexprice.assert_called_once_with(
        server_url="https://us.api.flexprice.io/v1",
        api_key_auth="test-key",
    )
    mock_client.customers.create_customer.assert_called_once_with(
        external_id=str(org_id),
        name="Acme Inc",
        email="admin@acme.com",
    )


@patch("flexprice.Flexprice")
def test_ensure_customer_swallows_already_exists(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    mock_client = MagicMock()
    mock_client.customers.create_customer.side_effect = Exception("Customer already exists")
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.ensure_customer(uuid4(), name="Acme Inc")


@patch("flexprice.Flexprice")
def test_ensure_subscription_no_op_when_auto_subscribe_disabled(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    settings.FLEXPRICE_AUTO_SUBSCRIBE = False
    settings.FLEXPRICE_DEFAULT_PLAN_ID = "plan_test"

    svc.ensure_subscription(uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_ensure_subscription_no_op_when_plan_id_missing(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    settings.FLEXPRICE_AUTO_SUBSCRIBE = True
    settings.FLEXPRICE_DEFAULT_PLAN_ID = None

    svc.ensure_subscription(uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_ensure_subscription_creates_when_none_exists(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    settings.FLEXPRICE_API_HOST = "https://api.cloud.flexprice.io/v1"
    settings.FLEXPRICE_AUTO_SUBSCRIBE = True
    settings.FLEXPRICE_DEFAULT_PLAN_ID = "plan_01KVT8BTT0HRB419QVCTNHS9RV"
    settings.FLEXPRICE_DEFAULT_CURRENCY = "usd"
    settings.FLEXPRICE_DEFAULT_BILLING_PERIOD = "MONTHLY"

    org_id = uuid4()
    mock_client = MagicMock()
    mock_client.subscriptions.query_subscription.return_value = MagicMock(items=[])
    mock_client.subscriptions.create_subscription.return_value = MagicMock(
        id="sub_test123"
    )
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.ensure_subscription(org_id)

    mock_client.subscriptions.query_subscription.assert_called_once_with(
        external_customer_id=str(org_id),
        plan_id="plan_01KVT8BTT0HRB419QVCTNHS9RV",
        limit=1,
    )
    mock_client.subscriptions.create_subscription.assert_called_once_with(
        billing_period="MONTHLY",
        currency="usd",
        plan_id="plan_01KVT8BTT0HRB419QVCTNHS9RV",
        external_customer_id=str(org_id),
        subscription_status="active",
    )


@patch("flexprice.Flexprice")
def test_ensure_subscription_skips_when_subscription_exists(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"
    settings.FLEXPRICE_AUTO_SUBSCRIBE = True
    settings.FLEXPRICE_DEFAULT_PLAN_ID = "plan_test"

    mock_client = MagicMock()
    mock_client.subscriptions.query_subscription.return_value = MagicMock(
        items=[MagicMock(id="sub_existing")]
    )
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.ensure_subscription(uuid4())

    mock_client.subscriptions.create_subscription.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_blind_test_share_created_no_op_when_disabled(mock_flexprice):
    settings.FLEXPRICE_ENABLED = False
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_blind_test_share_created(uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_blind_test_share_created_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_blind_test_share_created(uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_blind_test_share_created_logs_and_swallows_errors(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    mock_client = MagicMock()
    mock_client.events.ingest_event.side_effect = RuntimeError("network down")
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_blind_test_response_submitted(
        uuid4(), uuid4(), share_id=uuid4(), workspace_id=uuid4(), response_count=1
    )


@patch("flexprice.Flexprice")
def test_ingest_usage_event_falls_back_to_request_dict(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    mock_client = MagicMock()
    mock_client.events.ingest_event.side_effect = [
        TypeError("ingest_event() got an unexpected keyword argument 'event_name'"),
        None,
    ]
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_blind_test_response_submitted(
        uuid4(), uuid4(), share_id=uuid4(), workspace_id=uuid4(), response_count=1
    )

    assert mock_client.events.ingest_event.call_count == 2
    assert "request" in mock_client.events.ingest_event.call_args_list[1].kwargs


@patch("flexprice.Flexprice")
def test_record_call_import_batch_created_includes_volume_properties(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    call_import_id = uuid4()
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_call_import_batch_created(
        org_id,
        call_import_id,
        workspace_id=workspace_id,
        total_rows=42,
        source="csv",
        provider="exotel",
    )

    mock_client.events.ingest_event.assert_called_once()
    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "call_import.batch_created"
    assert payload["properties"]["quantity"] == "42"
    assert payload["properties"]["feature"] == "call_imports"
    assert payload["properties"]["source"] == "csv"
    assert payload["properties"]["provider"] == "exotel"


@patch("flexprice.Flexprice")
def test_record_call_import_evaluation_completed_meters_pass_delta(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    evaluation_id = uuid4()
    workspace_id = uuid4()
    call_import_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    accepted = svc.record_call_import_evaluation_completed(
        org_id,
        evaluation_id,
        workspace_id=workspace_id,
        call_import_id=call_import_id,
        rows_billed=50,
        completed_total=1950,
        total_rows=2000,
        metric_count=5,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="call_import.evaluation_completed",
        external_customer_id=str(org_id),
        event_id=f"{evaluation_id}:1950",
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "call_imports",
            "quantity": "50",
            "evaluation_id": str(evaluation_id),
            "call_import_id": str(call_import_id),
            "completed_total": "1950",
            "total_rows": "2000",
            "metric_count": "5",
            "rows_billed": "50",
        },
    )
    assert accepted is True


@patch("flexprice.Flexprice")
def test_record_call_import_evaluation_started(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_call_import_evaluation_started(
        uuid4(),
        uuid4(),
        workspace_id=uuid4(),
        call_import_id=uuid4(),
        total_rows=100,
        metric_count=3,
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_call_import_recording_minutes_billed(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    eval_row_id = uuid4()
    evaluation_id = uuid4()
    workspace_id = uuid4()
    call_import_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    accepted = svc.record_call_import_recording_minutes_billed(
        org_id,
        eval_row_id,
        workspace_id=workspace_id,
        evaluation_id=evaluation_id,
        call_import_id=call_import_id,
        audio_seconds=90,
        billable_minutes=2,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="call_import.recording_minutes_billed",
        external_customer_id=str(org_id),
        event_id=str(eval_row_id),
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "call_imports",
            "billable_minutes": "2",
            "quantity": "2",
            "evaluation_row_id": str(eval_row_id),
            "evaluation_id": str(evaluation_id),
            "call_import_id": str(call_import_id),
            "audio_seconds": "90",
        },
    )
    assert accepted is True


@patch("flexprice.Flexprice")
def test_record_call_import_pdf_report_generated(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    pdf_report_id = uuid4()
    evaluation_id = uuid4()
    workspace_id = uuid4()
    call_import_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_call_import_pdf_report_generated(
        org_id,
        pdf_report_id,
        workspace_id=workspace_id,
        evaluation_id=evaluation_id,
        call_import_id=call_import_id,
        report_type="external",
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="call_import.pdf_report_generated",
        external_customer_id=str(org_id),
        event_id=str(pdf_report_id),
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "call_imports",
            "quantity": "1",
            "pdf_report_id": str(pdf_report_id),
            "evaluation_id": str(evaluation_id),
            "call_import_id": str(call_import_id),
            "report_type": "external",
        },
    )


@patch("flexprice.Flexprice")
def test_record_event_returns_false_when_disabled(mock_flexprice):
    settings.FLEXPRICE_ENABLED = False
    settings.FLEXPRICE_API_KEY = "test-key"

    assert (
        svc.record_event(
            "chat.completion",
            uuid4(),
            uuid4(),
            properties={"quantity": 1},
        )
        is False
    )
    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_playground_call_evaluated_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_playground_call_evaluated(
        uuid4(),
        "attempt-1",
        evaluator_result_id=uuid4(),
        workspace_id=uuid4(),
        call_short_id="123456",
        metric_count=4,
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_playground_web_call_started_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_playground_web_call_started(
        uuid4(), "abc123", workspace_id=uuid4(), agent_id=uuid4()
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_playground_websocket_session_started_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_playground_websocket_session_started(uuid4(), "ws456", workspace_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_playground_evaluation_completed_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    evaluator_result_id = uuid4()
    evaluation_attempt_id = f"{evaluator_result_id}:task-1"
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_playground_evaluation_completed(
        org_id,
        evaluation_attempt_id,
        evaluator_result_id=evaluator_result_id,
        workspace_id=workspace_id,
        call_short_id="999",
        duration_seconds=12.5,
        metric_count=2,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "playground.evaluation_completed"
    assert payload["properties"]["feature"] == "agent_playground"
    assert payload["properties"]["quantity"] == "1"
    assert payload["properties"]["billable_minutes"] == "1"
    assert payload["properties"]["duration_seconds"] == "12.5"
    assert payload["properties"]["metric_count"] == "2"
    assert payload["properties"]["billable_minutes"] == "1"


@patch("flexprice.Flexprice")
def test_record_test_agent_conversation_started_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_test_agent_conversation_started(uuid4(), uuid4(), workspace_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_test_agent_conversation_ended_bills_one_conversation(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    conversation_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_test_agent_conversation_ended(
        org_id,
        conversation_id,
        workspace_id=workspace_id,
        duration_seconds=120.0,
        turn_count=8,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="test_agent.conversation_ended",
        external_customer_id=str(org_id),
        event_id=str(conversation_id),
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "agent_playground",
            "quantity": "2",
            "billable_minutes": "2",
            "conversation_id": str(conversation_id),
            "duration_seconds": "120.0",
            "turn_count": "8",
        },
    )


@patch("flexprice.Flexprice")
def test_record_test_agent_conversation_started_with_metadata_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_test_agent_conversation_started(
        uuid4(),
        uuid4(),
        workspace_id=uuid4(),
        result_id="123456",
        agent_id=uuid4(),
        call_short_id="654321",
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_evaluator_run_requested_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_evaluator_run_requested(
        uuid4(), uuid4(), workspace_id=uuid4(), quantity=3
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_evaluator_run_completed_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    evaluator_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_evaluator_run_completed(
        org_id,
        "res-001",
        workspace_id=workspace_id,
        evaluator_id=evaluator_id,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "evaluator.run_completed"
    assert payload["properties"]["feature"] == "evaluators"
    assert payload["properties"]["quantity"] == "1"


@patch("flexprice.Flexprice")
def test_record_judge_alignment_run_completed_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    run_id = uuid4()
    dataset_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_judge_alignment_run_completed(
        org_id,
        run_id,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        samples_scored=12,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "judge_alignment.run_completed"
    assert payload["properties"]["feature"] == "judge_alignment"
    assert payload["properties"]["quantity"] == "12"


@patch("flexprice.Flexprice")
def test_record_judge_alignment_run_completed_skips_when_no_samples(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_judge_alignment_run_completed(
        uuid4(), uuid4(), workspace_id=uuid4(), dataset_id=uuid4(), samples_scored=0
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_prompt_optimization_run_completed_bills_candidates(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    run_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_prompt_optimization_run_completed(
        org_id,
        run_id,
        workspace_id=workspace_id,
        agent_id=uuid4(),
        candidates_count=5,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "prompt_optimization.run_completed"
    assert payload["properties"]["feature"] == "gepa_optimization"
    assert payload["properties"]["quantity"] == "5"


@patch("flexprice.Flexprice")
def test_record_evaluator_recording_minutes_billed(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    result_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    accepted = svc.record_evaluator_recording_minutes_billed(
        org_id,
        result_id,
        workspace_id=workspace_id,
        duration_seconds=125.0,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="evaluator.recording_minutes_billed",
        external_customer_id=str(org_id),
        event_id=str(result_id),
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "evaluators",
            "quantity": "3",
            "billable_minutes": "3",
            "evaluator_result_id": str(result_id),
            "duration_seconds": "125.0",
            "audio_seconds": "125",
        },
    )
    assert accepted is True


@patch("flexprice.Flexprice")
def test_record_observability_call_evaluated_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_observability_call_evaluated(uuid4(), "call-1", workspace_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_metrics_ai_assist_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    request_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_metrics_ai_assist(
        org_id,
        request_id,
        workspace_id=workspace_id,
        mode="generate",
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "metrics.ai_assist"
    assert payload["properties"]["feature"] == "metrics_ai_assist"
    assert payload["properties"]["quantity"] == "1"


@patch("flexprice.Flexprice")
def test_record_metric_studio_run_completed_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    run_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_metric_studio_run_completed(
        org_id,
        run_id,
        workspace_id=workspace_id,
        run_status="completed",
        total_items=3,
        completed_items=3,
        failed_items=0,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "metric_studio.run_completed"
    assert payload["properties"]["feature"] == "metric_studio"
    assert payload["properties"]["quantity"] == "3"


@patch("flexprice.Flexprice")
def test_record_scenario_ai_text_generated_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    request_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_scenario_ai_text_generated(
        org_id,
        request_id,
        workspace_id=workspace_id,
        model="gpt-4o",
        purpose="scenario_description",
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "scenario.ai_text_generated"
    assert payload["properties"]["feature"] == "scenario_ai"
    assert payload["properties"]["quantity"] == "1"


@patch("flexprice.Flexprice")
def test_record_prompt_partial_ai_assisted_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    request_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_prompt_partial_ai_assisted(
        org_id,
        request_id,
        workspace_id=workspace_id,
        mode="generate",
        model="gpt-4o",
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "prompt_partial.ai_assisted"
    assert payload["properties"]["feature"] == "prompt_partials"
    assert payload["properties"]["mode"] == "generate"


@patch("flexprice.Flexprice")
def test_record_call_import_user_insights_generated_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()
    evaluation_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_call_import_user_insights_generated(
        org_id,
        uuid4(),
        workspace_id=workspace_id,
        evaluation_id=evaluation_id,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "call_import.user_insights_generated"
    assert payload["properties"]["feature"] == "call_imports"


@patch("flexprice.Flexprice")
def test_record_agent_test_setup_generated_includes_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_agent_test_setup_generated(
        org_id,
        uuid4(),
        workspace_id=workspace_id,
        purpose="full_setup",
        scenario_count=3,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "agent.test_setup_generated"
    assert payload["properties"]["feature"] == "agent_playground"
    assert payload["properties"]["purpose"] == "full_setup"


@patch("flexprice.Flexprice")
def test_record_tts_generation_started_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_tts_generation_started(
        uuid4(), uuid4(), workspace_id=uuid4(), sample_count=4
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_tts_sample_synthesized_includes_voice_playground_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    sample_id = uuid4()
    comparison_id = uuid4()
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_tts_sample_synthesized(
        org_id,
        sample_id,
        workspace_id=workspace_id,
        comparison_id=comparison_id,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "tts.sample_synthesized"
    assert payload["properties"]["feature"] == "voice_playground"
    assert payload["properties"]["quantity"] == "1"


@patch("flexprice.Flexprice")
def test_record_tts_report_requested_does_not_ingest(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_tts_report_requested(
        uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4()
    )

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_tts_report_completed_includes_voice_playground_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    report_job_id = uuid4()
    comparison_id = uuid4()
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_tts_report_completed(
        org_id,
        report_job_id,
        workspace_id=workspace_id,
        comparison_id=comparison_id,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "tts.report_completed"
    assert payload["properties"]["feature"] == "voice_playground"
    assert payload["properties"]["quantity"] == "1"


@patch("flexprice.Flexprice")
def test_record_blind_test_response_submitted_includes_voice_playground_feature(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    response_id = uuid4()
    share_id = uuid4()
    workspace_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_blind_test_response_submitted(
        org_id,
        response_id,
        share_id=share_id,
        workspace_id=workspace_id,
        response_count=3,
    )

    payload = mock_client.events.ingest_event.call_args.kwargs
    assert payload["event_name"] == "blind_test.response_submitted"
    assert payload["properties"]["feature"] == "voice_playground"
    assert payload["properties"]["quantity"] == "3"
