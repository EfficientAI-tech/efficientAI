"""Celery task modules - import to register tasks with the app."""

from app.workers.config import celery_app

# Import task modules to register tasks with Celery
from . import process_evaluation
from . import process_evaluator_result
from . import run_evaluator
from . import tts_comparison
from . import tts_report
from . import run_prompt_optimization

__all__ = [
    "celery_app",
    "process_evaluation_task",
    "process_evaluator_result_task",
    "run_evaluator_task",
    "generate_tts_comparison_task",
    "evaluate_tts_comparison_task",
    "generate_tts_report_pdf_task",
    "run_prompt_optimization_task",
]

process_evaluation_task = process_evaluation.process_evaluation_task
process_evaluator_result_task = process_evaluator_result.process_evaluator_result_task
run_evaluator_task = run_evaluator.run_evaluator_task
generate_tts_comparison_task = tts_comparison.generate_tts_comparison_task
evaluate_tts_comparison_task = tts_comparison.evaluate_tts_comparison_task
generate_tts_report_pdf_task = tts_report.generate_tts_report_pdf_task
run_prompt_optimization_task = run_prompt_optimization.run_prompt_optimization_task
