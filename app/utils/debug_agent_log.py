"""Session debug logging (agent instrumentation). Disabled unless app.debug is true."""

from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import settings

_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug-33d9d2.log"


def agent_debug_log(
    location: str,
    message: str,
    data: dict,
    hypothesis_id: str,
    run_id: str = "pre-fix",
) -> None:
    if not settings.DEBUG:
        return
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "33d9d2",
                        "runId": run_id,
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                    }
                )
                + "\n"
            )
    except Exception:
        pass
