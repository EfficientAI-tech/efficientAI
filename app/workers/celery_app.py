"""Celery application - compatibility entrypoint.

This module preserves backward compatibility for:
- Imports: from app.workers.celery_app import process_evaluator_result_task, etc.
- Worker command: celery -A app.workers.celery_app worker

Task implementations live in app/workers/tasks/*.py
Celery app creation lives in app/workers/config.py
"""

from app.workers.config import celery_app
from app.workers.tasks import (
    process_evaluation_task,
    process_evaluator_result_task,
    run_evaluator_task,
    generate_tts_comparison_task,
    evaluate_tts_comparison_task,
    generate_tts_report_pdf_task,
    run_prompt_optimization_task,
    process_call_import_row_task,
)

__all__ = [
    "celery_app",
    "process_evaluation_task",
    "process_evaluator_result_task",
    "run_evaluator_task",
    "generate_tts_comparison_task",
    "evaluate_tts_comparison_task",
    "generate_tts_report_pdf_task",
    "run_prompt_optimization_task",
    "process_call_import_row_task",
]
