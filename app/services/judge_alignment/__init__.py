"""
Judge Alignment service package.

Borrows AlignEval's labeling + LLM-judge calibration workflow and wires it
into EfficientAI's existing Evaluator / Metric / AIProvider / GEPA stack.

Public surface:
    - dataset_adapters.materialize_samples(...)
    - metrics.compute_alignment_metrics(...)
    - judge_runner.run_judge(...)
    - gepa_bridge.start_gepa_for_dataset(...)
    - model_catalog.list_judge_capable_models(...)
    - settings.get_org_settings / set_org_settings / DEFAULTS
"""
