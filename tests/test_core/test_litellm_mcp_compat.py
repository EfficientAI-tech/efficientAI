"""Guard litellm vs mcp SDK version pairing (see pyproject.toml litellm upper bound)."""

import importlib.metadata as importlib_metadata

from packaging.version import Version


def test_litellm_and_mcp_versions_are_compatible():
    litellm_ver = Version(importlib_metadata.version("litellm"))
    mcp_ver = importlib_metadata.version("mcp")
    import mcp.types as mcp_types

    if litellm_ver >= Version("1.106.0"):
        assert hasattr(mcp_types, "CacheableResult"), (
            f"litellm {litellm_ver} needs mcp>=2.2 (CacheableResult); installed mcp {mcp_ver}"
        )
    import litellm  # noqa: F401 — must import cleanly in CI images
