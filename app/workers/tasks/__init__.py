"""Celery task modules - import to register tasks with the app."""

from app.workers.config import celery_app

# Import task modules to register tasks with Celery
from . import process_evaluation
from . import process_evaluator_result
from . import run_evaluator
from . import tts_comparison
from . import tts_report
from . import run_prompt_optimization
from . import process_call_import_row
from . import evaluate_call_import_row
from . import transcribe_call_import_row
from . import run_judge_alignment
from . import generate_evaluation_user_insights
from . import generate_evaluation_tldr_insights
from . import generate_evaluation_metric_clusters

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
    "evaluate_call_import_row_task",
    "transcribe_call_import_row_task",
    "run_judge_alignment_task",
    "generate_evaluation_user_insights_task",
    "generate_evaluation_tldr_insights_task",
    "generate_evaluation_metric_clusters_task",
]

process_evaluation_task = process_evaluation.process_evaluation_task
process_evaluator_result_task = process_evaluator_result.process_evaluator_result_task
run_evaluator_task = run_evaluator.run_evaluator_task
generate_tts_comparison_task = tts_comparison.generate_tts_comparison_task
evaluate_tts_comparison_task = tts_comparison.evaluate_tts_comparison_task
generate_tts_report_pdf_task = tts_report.generate_tts_report_pdf_task
run_prompt_optimization_task = run_prompt_optimization.run_prompt_optimization_task
process_call_import_row_task = process_call_import_row.process_call_import_row_task
evaluate_call_import_row_task = evaluate_call_import_row.evaluate_call_import_row_task
transcribe_call_import_row_task = (
    transcribe_call_import_row.transcribe_call_import_row_task
)
run_judge_alignment_task = run_judge_alignment.run_judge_alignment_task
generate_evaluation_user_insights_task = (
    generate_evaluation_user_insights.generate_evaluation_user_insights_task
)
generate_evaluation_tldr_insights_task = (
    generate_evaluation_tldr_insights.generate_evaluation_tldr_insights_task
)
generate_evaluation_metric_clusters_task = (
    generate_evaluation_metric_clusters.generate_evaluation_metric_clusters_task
)
