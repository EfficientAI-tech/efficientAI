"""Unit tests for enterprise license helpers."""

from uuid import uuid4

from app.core import license as license_module


def test_get_enabled_features_filters_unknown_features(monkeypatch):
    monkeypatch.setattr(
        license_module,
        "get_license_info",
        lambda: {"features": ["voice_playground", "unknown_feature", "gepa_optimization"]},
    )

    enabled = license_module.get_enabled_features()

    assert "voice_playground" in enabled
    assert "gepa_optimization" in enabled
    assert "unknown_feature" not in enabled


def test_is_feature_enabled_for_deployment_wide_license(monkeypatch):
    monkeypatch.setattr(
        license_module,
        "get_license_info",
        lambda: {"features": ["voice_playground"], "org_id": None},
    )

    assert license_module.is_feature_enabled("voice_playground") is True


def test_is_feature_enabled_for_org_scoped_license(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        license_module,
        "get_license_info",
        lambda: {"features": ["voice_playground"], "org_id": str(org_id)},
    )

    assert license_module.is_feature_enabled("voice_playground", org_id) is True
    assert license_module.is_feature_enabled("voice_playground", uuid4()) is False
    assert license_module.is_feature_enabled("voice_playground", None) is False


def test_get_feature_catalog_returns_copy_not_global_reference():
    catalog = license_module.get_feature_catalog()
    catalog["voice_playground"]["title"] = "Mutated"

    fresh_catalog = license_module.get_feature_catalog()
    assert fresh_catalog["voice_playground"]["title"] != "Mutated"
