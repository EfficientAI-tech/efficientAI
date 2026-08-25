"""Ensure org usage API routes are mounted on the v1 router."""

from app.api.v1.api import api_router


def test_org_usage_routes_are_registered():
    paths = {route.path for route in api_router.routes if hasattr(route, "path")}
    assert "/organizations/usage/summary" in paths
    assert "/organizations/usage/breakdown" in paths
    assert "/organizations/usage/filters" in paths
    assert "/organizations/usage/fx-rate" in paths
    assert "/organizations/usage/pricing/overrides" in paths
