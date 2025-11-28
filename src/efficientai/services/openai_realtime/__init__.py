#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import warnings

from efficientai.services.azure.realtime.llm import AzureRealtimeLLMService
from efficientai.services.openai.realtime.events import (
    InputAudioNoiseReduction,
    InputAudioTranscription,
    SemanticTurnDetection,
    SessionProperties,
    TurnDetection,
)
from efficientai.services.openai.realtime.llm import OpenAIRealtimeLLMService

with warnings.catch_warnings():
    warnings.simplefilter("always")
    warnings.warn(
        "Types in efficientai.services.openai_realtime are deprecated. "
        "Please use the equivalent types from "
        "efficientai.services.openai.realtime instead.",
        DeprecationWarning,
        stacklevel=2,
    )
