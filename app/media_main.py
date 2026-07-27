"""Media service entry point (live voice WebSockets only)."""

import logging
import os
from pathlib import Path

# Must be set before importing settings so the singleton picks up media mode.
os.environ["SERVICE_MODE"] = "media"

from app.config import apply_service_mode, load_config_from_file
from app.app_factory import create_app

logger = logging.getLogger(__name__)

config_path = Path("config.yml")
if config_path.exists():
    try:
        load_config_from_file(str(config_path))
    except Exception as e:
        logger.warning("Could not load config.yml: %s", e)

# Subprocesses spawned by ``eai start-all`` inherit SERVICE_MODE=api; re-sync
# after YAML load so WebSocket routes mount on this process.
apply_service_mode("media")

app = create_app()
