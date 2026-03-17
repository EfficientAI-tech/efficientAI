#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Murf services - uses lazy imports to avoid loading heavy dependencies at package import."""


def __getattr__(name):
    """Lazy import handler for murf submodules."""
    if name in ("MurfTTSService", "synthesize_murf_stream_bytes"):
        from .tts import MurfTTSService, synthesize_murf_stream_bytes
        if name == "MurfTTSService":
            return MurfTTSService
        return synthesize_murf_stream_bytes
    raise AttributeError(f"module 'efficientai.services.murf' has no attribute '{name}'")
