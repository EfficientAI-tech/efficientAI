"""Regression tests for eval diarisation pending/running status races."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


def _load_transcribe_module():
    module_name = "transcribe_call_import_row_race_tests"
    if module_name in sys.modules:
        return sys.modules[module_name]

    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "app" / "workers" / "tasks" / "transcribe_call_import_row.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def transcribe_module():
    return _load_transcribe_module()


@patch(
    "app.db_sharding.row_ops.locate_call_import_row",
)
def test_finalize_skips_completed_when_task_no_longer_owns_row(
    mock_locate, transcribe_module
):
    row_id = uuid4()
    row_db = MagicMock()
    row = MagicMock()
    mock_locate.return_value = (row_db, MagicMock(), row, None)

    pipeline_ctx = {
        "owner_task_id": "current-task",
        "normalised_mode": "stt_llm",
        "llm_provider_value": "openai",
        "llm_model_value": "gpt-4o",
        "effective_prompt": "prompt",
        "stt_provider": "google",
        "stt_model": "chirp",
        "emit_native_text": False,
    }

    with patch.object(
        transcribe_module,
        "_diarisation_update_if_owned",
        return_value=False,
    ) as mock_owned:
        result = transcribe_module._finalize_diarization_row(
            row_id,
            pipeline_ctx=pipeline_ctx,
            work_result={"reason": "no_speech_detected"},
        )

    assert result == {"status": "skipped", "reason": "superseded"}
    mock_owned.assert_called_once()
    assert mock_owned.call_args[0][2] == "current-task"


def test_claim_running_requires_pending_and_matching_task_id(transcribe_module):
    row_id = uuid4()
    row_db = MagicMock()
    execute_result = MagicMock()
    execute_result.rowcount = 0
    row_db.execute.return_value = execute_result

    claimed = transcribe_module._claim_diarisation_running(
        row_db,
        row_id,
        "stale-task",
        {"diarised_prompt": "x"},
    )
    assert claimed is False
    row_db.commit.assert_called_once()
