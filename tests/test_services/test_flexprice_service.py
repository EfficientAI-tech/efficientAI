"""Unit tests for Flexprice billing service (optional metering)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.config import settings
from app.services.billing import flexprice_service as svc


@pytest.fixture(autouse=True)
def reset_flexprice_settings():
    previous = (
        settings.FLEXPRICE_ENABLED,
        settings.FLEXPRICE_API_KEY,
        settings.FLEXPRICE_API_HOST,
    )
    yield
    (
        settings.FLEXPRICE_ENABLED,
        settings.FLEXPRICE_API_KEY,
        settings.FLEXPRICE_API_HOST,
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
def test_record_blind_test_share_created_no_op_when_disabled(mock_flexprice):
    settings.FLEXPRICE_ENABLED = False
    settings.FLEXPRICE_API_KEY = "test-key"

    svc.record_blind_test_share_created(uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4())

    mock_flexprice.assert_not_called()


@patch("flexprice.Flexprice")
def test_record_blind_test_share_created_ingests_event(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    share_id = uuid4()
    workspace_id = uuid4()
    comparison_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_blind_test_share_created(
        org_id,
        share_id,
        workspace_id=workspace_id,
        comparison_id=comparison_id,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="blind_test.share_created",
        external_customer_id=str(org_id),
        event_id=str(share_id),
        source="efficientai",
        properties={
            "share_id": str(share_id),
            "workspace_id": str(workspace_id),
            "comparison_id": str(comparison_id),
            "feature": "voice_playground",
        },
    )


@patch("flexprice.Flexprice")
def test_record_blind_test_share_created_logs_and_swallows_errors(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    mock_client = MagicMock()
    mock_client.events.ingest_event.side_effect = RuntimeError("network down")
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_blind_test_share_created(uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4())


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

    svc.record_blind_test_share_created(uuid4(), uuid4(), workspace_id=uuid4(), comparison_id=uuid4())

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
    assert payload["properties"]["total_rows"] == 42
    assert payload["properties"]["feature"] == "call_imports"


@patch("flexprice.Flexprice")
def test_record_call_import_evaluation_row_completed_uses_composite_event_id(mock_flexprice):
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "test-key"

    org_id = uuid4()
    evaluation_id = uuid4()
    row_id = uuid4()
    workspace_id = uuid4()
    call_import_id = uuid4()

    mock_client = MagicMock()
    mock_flexprice.return_value.__enter__.return_value = mock_client

    svc.record_call_import_evaluation_row_completed(
        org_id,
        evaluation_id,
        row_id,
        workspace_id=workspace_id,
        call_import_id=call_import_id,
        metrics_scored=3,
    )

    mock_client.events.ingest_event.assert_called_once_with(
        event_name="call_import.evaluation_row_completed",
        external_customer_id=str(org_id),
        event_id=f"{evaluation_id}:{row_id}",
        source="efficientai",
        properties={
            "workspace_id": str(workspace_id),
            "feature": "call_imports",
            "call_import_id": str(call_import_id),
            "evaluation_id": str(evaluation_id),
            "row_id": str(row_id),
            "metrics_scored": 3,
            "quantity": 1,
        },
    )
