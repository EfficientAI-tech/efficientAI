"""Regression tests: pytest must never reach real Flexprice APIs."""

from uuid import uuid4

import httpx
import pytest

from app.config import settings
from app.services.billing import flexprice_service as fp


def test_record_event_is_stubbed_even_when_settings_enabled():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "dummy-key-for-test"

    assert (
        fp.record_event("metrics.ai_assist", uuid4(), uuid4(), properties={"mode": "x"})
        is False
    )


def test_ensure_customer_is_stubbed_even_when_settings_enabled():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "dummy-key-for-test"

    fp.ensure_customer(uuid4(), name="Test Org", email="test@example.com")


def test_record_wrappers_do_not_invoke_flexprice_sdk():
    settings.FLEXPRICE_ENABLED = True
    settings.FLEXPRICE_API_KEY = "dummy-key-for-test"
    org_id = uuid4()
    ws_id = uuid4()

    fp.record_metrics_llm_assist(org_id, uuid4(), workspace_id=ws_id, mode="description")
    fp.record_call_import_batch_created(
        org_id,
        uuid4(),
        workspace_id=ws_id,
        total_rows=1,
        source="csv",
    )
    fp.record_test_agent_conversation_started(org_id, uuid4(), workspace_id=ws_id)


def test_flexprice_sdk_construction_is_forbidden():
    with pytest.raises(RuntimeError, match="Real Flexprice SDK invoked during pytest"):
        from flexprice import Flexprice

        Flexprice(server_url="https://us.api.flexprice.io/v1", api_key_auth="x")


def test_httpx_to_flexprice_host_is_blocked():
    with pytest.raises(RuntimeError, match="Blocked Flexprice HTTP during pytest"):
        httpx.get("https://us.api.flexprice.io/v1/customers")
