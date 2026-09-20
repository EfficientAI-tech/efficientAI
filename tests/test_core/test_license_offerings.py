"""Unit tests for default enterprise offerings and org-scoped feature resolution."""

from uuid import uuid4

from app.core import license as license_module


def test_default_offerings_enabled_with_any_entitlement(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        license_module,
        "get_license_info",
        lambda: {"features": ["call_imports"], "org_id": None},
    )
    monkeypatch.setattr(
        license_module,
        "get_enabled_features",
        lambda: ["call_imports"],
    )

    assert license_module.is_feature_enabled("alerts", org_id) is True
    assert license_module.is_feature_enabled("metric_studio", org_id) is True
    assert license_module.is_feature_enabled("db_sharding", org_id) is True
    assert license_module.is_feature_enabled("llm_gateway", org_id) is True


def test_default_offerings_absent_without_license(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(license_module, "get_license_info", lambda: {})
    monkeypatch.setattr(license_module, "get_enabled_features", lambda: [])

    assert license_module.is_feature_enabled("alerts", org_id) is False
    assert license_module.is_feature_enabled("call_imports", org_id) is False


def test_get_features_enabled_for_org_includes_defaults(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        license_module,
        "get_license_info",
        lambda: {"features": ["enterprise_platform"], "org_id": str(org_id)},
    )
    monkeypatch.setattr(
        license_module,
        "get_enabled_features",
        lambda: ["enterprise_platform"],
    )

    enabled = license_module.get_features_enabled_for_org(org_id)

    assert "enterprise_platform" in enabled
    assert "alerts" in enabled
    assert "metric_studio" in enabled
