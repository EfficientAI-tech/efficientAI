#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""FastAPI WebSocket transport implementation for EfficientAI.

This module provides WebSocket-based transport for real-time audio/video streaming
using FastAPI and WebSocket connections. Supports binary and text serialization
with configurable session timeouts and WAV header generation.
"""

import warnings

from efficientai.transports.websocket.fastapi import *

with warnings.catch_warnings():
    warnings.simplefilter("always")
    warnings.warn(
        "Module `efficientai.transports.network.fastapi_websocket` is deprecated, "
        "use `efficientai.transports.websocket.fastapi` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
