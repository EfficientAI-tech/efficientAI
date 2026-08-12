"""Tests for usage date timezone mapping."""

from datetime import date

from app.services.usage.dates import usage_date_filter_bounds, usage_local_today


def test_usage_date_filter_bounds_india_late_night():
  # 1:26 AM IST on Aug 13 is still Aug 12 in UTC usage_date bucket.
  start = date(2026, 8, 13)
  end = date(2026, 8, 13)
  filter_start, filter_end = usage_date_filter_bounds(start, end, "Asia/Kolkata")
  assert filter_start == date(2026, 8, 12)
  assert filter_end == date(2026, 8, 13)


def test_usage_date_filter_bounds_without_tz_uses_exact_dates():
  start = date(2026, 8, 13)
  end = date(2026, 8, 13)
  assert usage_date_filter_bounds(start, end, None) == (start, end)


def test_usage_date_filter_bounds_utc_matches_calendar_days():
  start = date(2026, 8, 13)
  end = date(2026, 8, 13)
  assert usage_date_filter_bounds(start, end, "UTC") == (start, end)


def test_usage_local_today_respects_timezone():
  today_utc = usage_local_today("UTC")
  today_india = usage_local_today("Asia/Kolkata")
  assert today_utc <= today_india or today_india <= today_utc
