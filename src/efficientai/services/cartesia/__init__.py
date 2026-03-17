#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Cartesia services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for cartesia submodules."""
    if name in ("CartesiaSTTService",):
        from .stt import CartesiaSTTService
        return CartesiaSTTService
    elif name in ("CartesiaTTSService", "CartesiaHttpTTSService"):
        from .tts import CartesiaTTSService, CartesiaHttpTTSService
        if name == "CartesiaTTSService":
            return CartesiaTTSService
        return CartesiaHttpTTSService
    elif name == "synthesize_cartesia_bytes":
        from .http_tts import synthesize_cartesia_bytes
        return synthesize_cartesia_bytes
    raise AttributeError(f"module 'efficientai.services.cartesia' has no attribute '{name}'")
