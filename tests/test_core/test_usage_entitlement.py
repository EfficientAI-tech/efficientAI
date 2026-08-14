"""Tests for usage enterprise entitlement."""

from uuid import uuid4

from app.core import usage_entitlement as ue


def test_has_enterprise_entitlement_deployment_wide(monkeypatch):
    monkeypatch.setattr(
        ue,
        "get_license_info",
        lambda: {"features": ["voice_playground"], "org_id": None},
    )
    monkeypatch.setattr(
        ue,
        "get_enabled_features",
        lambda: ["voice_playground"],
    )
    assert ue.has_enterprise_entitlement() is True
    assert ue.has_enterprise_entitlement(uuid4()) is True


def test_has_enterprise_entitlement_org_scoped(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        ue,
        "get_license_info",
        lambda: {"features": ["call_imports"], "org_id": str(org_id)},
    )
    monkeypatch.setattr(
        ue,
        "get_enabled_features",
        lambda: ["call_imports"],
    )
    assert ue.has_enterprise_entitlement(org_id) is True
    assert ue.has_enterprise_entitlement(uuid4()) is False


def test_has_enterprise_entitlement_no_license(monkeypatch):
    monkeypatch.setattr(ue, "get_license_info", lambda: {})
    monkeypatch.setattr(ue, "get_enabled_features", lambda: [])
    assert ue.has_enterprise_entitlement(uuid4()) is False


def test_get_usage_policy_oss(monkeypatch):
    monkeypatch.setattr(ue, "has_enterprise_entitlement", lambda _oid=None: False)
    policy = ue.get_usage_policy(uuid4())
    assert policy.extended_history is False
    assert policy.max_history_days == ue.OSS_USAGE_HISTORY_DAYS
