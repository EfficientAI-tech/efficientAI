"""Tests for OTLP ingest workspace resolution."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.auth.principal import AuthMethod, Principal
from app.services.synthetic_traces.workspace_ingest import resolve_otlp_ingest_workspace_id


@pytest.fixture
def api_key_principal(org_id):
    return Principal(
        organization_id=org_id,
        user_id=None,
        auth_method=AuthMethod.API_KEY,
        api_key_id=uuid4(),
    )


def test_resolve_uses_trace_workspace_when_header_workspace_is_default(
    db_session,
    org_id,
    seed_org,
    default_workspace,
    api_key_principal,
):
    from app.models.database import SyntheticCallTrace, Workspace

    default_ws = default_workspace
    demo_ws = Workspace(
        id=uuid4(),
        organization_id=org_id,
        name="Demo",
        slug="demo-ingest-test",
        is_default=False,
        is_active=True,
    )
    db_session.add(demo_ws)
    db_session.flush()

    trace = SyntheticCallTrace(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=demo_ws.id,
        call_short_id="482931",
        transport="webrtc",
        tier="component",
        status="open",
        environment="pre_prod",
    )
    db_session.add(trace)
    db_session.commit()

    resolved = resolve_otlp_ingest_workspace_id(
        db_session,
        organization_id=org_id,
        request_workspace_id=default_ws.id,
        principal=api_key_principal,
        header_call_short_id="482931",
        body=None,
        content_type="",
    )
    assert resolved == demo_ws.id
