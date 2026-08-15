"""Tests for usage access policy clamping."""

from datetime import date, timedelta
from uuid import uuid4

from app.core import usage_entitlement as ue
from app.services.usage.access import UsageAccessPolicy, oss_usage_min_local_date


def test_oss_min_local_date_seven_inclusive(monkeypatch):
    monkeypatch.setattr(
        "app.services.usage.access.usage_local_today",
        lambda tz: date(2026, 8, 14),
    )
    assert oss_usage_min_local_date(None) == date(2026, 8, 8)


def test_resolve_clamps_old_start(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        "app.services.usage.access.has_enterprise_entitlement",
        lambda _oid=None: False,
    )
    monkeypatch.setattr(
        "app.services.usage.access.get_usage_policy",
        lambda _oid: ue.UsagePolicySnapshot(False, 7),
    )
    monkeypatch.setattr(
        "app.services.usage.access.usage_local_today",
        lambda tz: date(2026, 8, 14),
    )

    result = UsageAccessPolicy.resolve(
        org_id,
        date(2020, 1, 1),
        date(2026, 8, 14),
        None,
    )
    assert result.range_clamped is True
    assert result.display_start == date(2026, 8, 8)
    assert result.enforced_filter_floor is not None


def test_resolve_full_range_when_entitled(monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(
        "app.services.usage.access.has_enterprise_entitlement",
        lambda _oid=None: True,
    )
    monkeypatch.setattr(
        "app.services.usage.access.get_usage_policy",
        lambda _oid: ue.UsagePolicySnapshot(True, None),
    )
    monkeypatch.setattr(
        "app.services.usage.access.usage_local_today",
        lambda tz: date(2026, 8, 14),
    )

    result = UsageAccessPolicy.resolve(
        org_id,
        date(2020, 1, 1),
        date(2026, 8, 14),
        None,
    )
    assert result.range_clamped is False
    assert result.display_start == date(2020, 1, 1)
    assert result.enforced_filter_floor is None
