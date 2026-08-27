"""Tests for VapiWebRTCBridge buffered turn events."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.webrtc_bridge.vapi_webrtc_bridge import VapiWebRTCBridge


@pytest.mark.asyncio
async def test_replay_buffered_transcript_and_stop():
    bridge = VapiWebRTCBridge.__new__(VapiWebRTCBridge)
    bridge._buffered_transcript = "Hello from Riley"
    bridge._buffered_provider_stop = True
    bridge.on_transcript_received = AsyncMock()
    bridge.on_agent_stop_talking = AsyncMock()

    await bridge.replay_buffered_turn_events()

    bridge.on_transcript_received.assert_awaited_once_with("Hello from Riley")
    bridge.on_agent_stop_talking.assert_awaited_once()
    assert bridge._buffered_transcript == ""
    assert bridge._buffered_provider_stop is False
