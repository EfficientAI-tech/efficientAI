#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import sys

from efficientai.services import DeprecatedModuleProxy

from .video import *

sys.modules[__name__] = DeprecatedModuleProxy(globals(), "tavus", "tavus.video")
