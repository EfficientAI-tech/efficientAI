"""Testing service package exports.

Submodules are imported lazily so `from app.services.testing.foo import ...`
does not pull in storage (which mkdir's UPLOAD_DIR on import).
"""

from typing import Any

__all__ = [
    "TestAgentBridgeService",
    "test_agent_bridge_service",
    "TestAgentService",
    "test_agent_service",
]


def __getattr__(name: str) -> Any:
    if name in {"TestAgentBridgeService", "test_agent_bridge_service"}:
        from app.services.testing.test_agent_bridge_service import (
            TestAgentBridgeService,
            test_agent_bridge_service,
        )

        return {
            "TestAgentBridgeService": TestAgentBridgeService,
            "test_agent_bridge_service": test_agent_bridge_service,
        }[name]
    if name in {"TestAgentService", "test_agent_service"}:
        from app.services.testing.test_agent_service import (
            TestAgentService,
            test_agent_service,
        )

        return {
            "TestAgentService": TestAgentService,
            "test_agent_service": test_agent_service,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
