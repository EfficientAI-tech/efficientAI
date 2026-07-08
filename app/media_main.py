"""Media service entry point (live voice WebSockets only)."""

import logging
import os
from pathlib import Path

os.environ.setdefault("SERVICE_MODE", "media")

from app.config import load_config_from_file
from app.app_factory import create_app

logger = logging.getLogger(__name__)

config_path = Path("config.yml")
if config_path.exists():
    try:
        load_config_from_file(str(config_path))
    except Exception as e:
        logger.warning("Could not load config.yml: %s", e)

app = create_app()
