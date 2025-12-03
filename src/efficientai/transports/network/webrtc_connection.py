#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Small WebRTC connection implementation for EfficientAI.

This module provides a WebRTC connection implementation using aiortc,
with support for audio/video tracks, data channels, and signaling
for real-time communication applications.
"""

import warnings

from efficientai.transports.smallwebrtc.connection import *

with warnings.catch_warnings():
    warnings.simplefilter("always")
    warnings.warn(
        "Module `efficientai.transports.network.webrtc_connection` is deprecated, "
        "use `efficientai.transports.smallwebrtc.connection` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
