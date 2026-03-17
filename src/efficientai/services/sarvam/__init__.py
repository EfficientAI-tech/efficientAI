#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Sarvam services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for sarvam submodules."""
    if name == "SarvamSTTService":
        from .stt import SarvamSTTService
        return SarvamSTTService
    elif name == "SarvamTTSService":
        from .tts import SarvamTTSService
        return SarvamTTSService
    elif name == "synthesize_sarvam_bytes":
        from .http_tts import synthesize_sarvam_bytes
        return synthesize_sarvam_bytes
    raise AttributeError(f"module 'efficientai.services.sarvam' has no attribute '{name}'")
