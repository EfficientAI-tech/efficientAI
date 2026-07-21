"""Tests for org-scoped judge model catalog including gateway models."""

from app.config import settings
from app.models.database import AIProvider, Organization
from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL
from app.services.judge_alignment.model_catalog import list_judge_capable_models


def test_list_judge_capable_models_includes_gateway_model(db_session, org_id):
    settings.LLM_GATEWAY_ENABLED = True
    settings.LLM_GATEWAY_BASE_URL = "http://localhost:8080/litellm"

    db_session.add(Organization(id=org_id, name="Test Org"))
    db_session.flush()
    db_session.add(
        AIProvider(
            organization_id=org_id,
            provider="custom",
            name="Inhouse Gemma",
            api_key=GATEWAY_MANAGED_KEY_SENTINEL,
            is_active=True,
            is_default=True,
            routing_mode="gateway",
            gateway_model="inhouse-llm-server-v2//models/gemma",
        )
    )
    db_session.commit()

    catalog = list_judge_capable_models(org_id, db_session)
    gateway_entries = [
        entry
        for entry in catalog
        if entry["provider"] == "custom"
        and entry["model"] == "inhouse-llm-server-v2//models/gemma"
    ]

    assert len(gateway_entries) == 1
    assert "Inhouse Gemma" in gateway_entries[0]["label"]
    assert gateway_entries[0]["credential_id"]
