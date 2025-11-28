#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Deprecated AI services module.

This module is deprecated. Import services directly from their respective modules:
- efficientai.services.ai_service
- efficientai.services.image_service
- efficientai.services.llm_service
- efficientai.services.stt_service
- efficientai.services.tts_service
- efficientai.services.vision_service
"""

import sys

from efficientai.services import DeprecatedModuleProxy

from .ai_service import *
from .image_service import *
from .llm_service import *
from .stt_service import *
from .tts_service import *
from .vision_service import *

sys.modules[__name__] = DeprecatedModuleProxy(
    globals(),
    "ai_services",
    "[ai_service,image_service,llm_service,stt_service,tts_service,vision_service]",
)
