"""Tests for VapiWebRTCBridge inbound audio forwarding."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webrtc_bridge.vapi_webrtc_bridge import VapiWebRTCBridge


def test_forward_incoming_audio_schedules_callback_on_event_loop():
    bridge = VapiWebRTCBridge.__new__(VapiWebRTCBridge)
    bridge.on_audio_received = AsyncMock()
    loop = MagicMock()
    loop.is_running.return_value = True
    bridge._event_loop = loop

    with patch("asyncio.run_coroutine_threadsafe") as run_threadsafe:
        bridge._forward_incoming_audio(b"\x00\x01")

    run_threadsafe.assert_called_once()
    coro, target_loop = run_threadsafe.call_args[0]
    assert target_loop is loop
    assert asyncio.iscoroutine(coro)


def test_forward_incoming_audio_noop_without_callback():
    bridge = VapiWebRTCBridge.__new__(VapiWebRTCBridge)
    bridge.on_audio_received = None
    bridge._event_loop = MagicMock()
    bridge._forward_incoming_audio(b"\x00\x01")  # should not raise
