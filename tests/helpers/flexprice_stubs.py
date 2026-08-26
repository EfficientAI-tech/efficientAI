"""Local Flexprice stubs for pytest — no real API or dashboard I/O."""

from __future__ import annotations

_FLEXPRICE_FORBIDDEN = "Real Flexprice SDK invoked during pytest — use a mock"


def _noop_record_event(*_args, **_kwargs) -> bool:
    return False


def _noop_ensure_customer(*_args, **_kwargs) -> None:
    return None


def _noop_provision_billing_customer(*_args, **_kwargs) -> None:
    return None


class _ForbiddenFlexprice:
    def __init__(self, *_args, **_kwargs):
        raise RuntimeError(_FLEXPRICE_FORBIDDEN)

    def __enter__(self):
        raise RuntimeError(_FLEXPRICE_FORBIDDEN)

    def __exit__(self, *_args):
        return False


def _is_flexprice_url(url) -> bool:
    return "flexprice.io" in str(url).lower()


def install_flexprice_test_isolation(monkeypatch) -> None:
    """Replace all Flexprice external I/O with local no-ops (suite-wide default)."""
    from app.services.billing import flexprice_service as fp
    from app.services import organization_provisioning as org_prov

    monkeypatch.setattr(fp, "record_event", _noop_record_event)
    monkeypatch.setattr(fp, "ensure_customer", _noop_ensure_customer)
    monkeypatch.setattr(org_prov, "provision_billing_customer", _noop_provision_billing_customer)
    monkeypatch.setattr("flexprice.Flexprice", _ForbiddenFlexprice)

    try:
        import httpx
    except ImportError:
        return

    original_get = httpx.get
    original_request = httpx.request

    def guarded_get(url, *args, **kwargs):
        if _is_flexprice_url(url):
            raise RuntimeError(f"Blocked Flexprice HTTP during pytest: {url}")
        return original_get(url, *args, **kwargs)

    def guarded_request(method, url, *args, **kwargs):
        if _is_flexprice_url(url):
            raise RuntimeError(f"Blocked Flexprice HTTP during pytest: {url}")
        return original_request(method, url, *args, **kwargs)

    monkeypatch.setattr(httpx, "get", guarded_get)
    monkeypatch.setattr(httpx, "request", guarded_request)


def is_flexprice_unit_test_path(path) -> bool:
    return path is not None and "test_flexprice_service.py" in str(path)
