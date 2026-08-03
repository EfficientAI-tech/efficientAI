"""Shared temp paths for telephony recordings (media → Celery worker handoff)."""

from __future__ import annotations

import os
import tempfile

from app.config import settings


def telephony_recording_temp_path(suffix: str = ".wav") -> str:
    """
    Create a temp WAV path on storage shared between media and worker processes.

    In split deploy, ``finalize_telephony_recording`` runs on Celery while capture
    runs on the telephony/media container. Container-local ``/tmp`` is not visible
    to the worker, so use ``UPLOAD_DIR/telephony_pending`` (bind-mounted in Compose).
    """
    base_dir = os.path.join(settings.UPLOAD_DIR or tempfile.gettempdir(), "telephony_pending")
    os.makedirs(base_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=suffix, dir=base_dir)
    os.close(fd)
    return path
