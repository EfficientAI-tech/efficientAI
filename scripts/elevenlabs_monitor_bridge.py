#!/usr/bin/env python3
"""Forward ElevenLabs monitor websocket events to EfficientAI live ingest.

Usage:
  EFFICIENTAI_API_KEY=... \
  EFFICIENTAI_WORKSPACE_ID=... \
  ELEVENLABS_API_KEY=... \
  python scripts/elevenlabs_monitor_bridge.py --conversation-id conv_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import os

from app.services.observability.elevenlabs_monitor_bridge import ElevenLabsMonitorBridge


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge ElevenLabs live monitor events to EfficientAI.")
    parser.add_argument("--conversation-id", required=True, help="ElevenLabs conversation id")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EFFICIENTAI_BASE_URL", "http://localhost:8000"),
        help="EfficientAI API base URL",
    )
    parser.add_argument(
        "--platform",
        default=os.environ.get("EFFICIENTAI_PROVIDER_PLATFORM", "elevenlabs"),
        help="Platform label sent to live ingest",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _args()
    efficientai_api_key = os.environ.get("EFFICIENTAI_API_KEY")
    workspace_id = os.environ.get("EFFICIENTAI_WORKSPACE_ID")
    elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY")

    if not efficientai_api_key:
        raise RuntimeError("EFFICIENTAI_API_KEY is required")
    if not elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required")

    bridge = ElevenLabsMonitorBridge(
        conversation_id=args.conversation_id,
        elevenlabs_api_key=elevenlabs_api_key,
        efficientai_api_key=efficientai_api_key,
        workspace_id=workspace_id,
        efficientai_base_url=args.base_url,
        provider_platform=args.platform,
    )
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(_main())
