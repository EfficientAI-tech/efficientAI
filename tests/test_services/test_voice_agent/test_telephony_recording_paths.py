"""Tests for shared telephony recording temp paths."""

import os
from unittest.mock import patch

from app.services.voice_agent.telephony_recording_paths import telephony_recording_temp_path


def test_telephony_recording_temp_path_uses_upload_dir(tmp_path):
    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    with patch("app.services.voice_agent.telephony_recording_paths.settings") as mock_settings:
        mock_settings.UPLOAD_DIR = upload_dir
        path = telephony_recording_temp_path()

    assert path.startswith(os.path.join(upload_dir, "telephony_pending"))
    assert os.path.isdir(os.path.dirname(path))
