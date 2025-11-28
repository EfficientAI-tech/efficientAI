#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Daily REST Helpers.

Methods that wrap the Daily API to create rooms, check room URLs, and get meeting tokens.
"""

import warnings

from efficientai.transports.daily.utils import *

with warnings.catch_warnings():
    warnings.simplefilter("always")
    warnings.warn(
        "Module `efficientai.transports.services.helpers.daily_rest` is deprecated, "
        "use `efficientai.transports.daily.utils` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
