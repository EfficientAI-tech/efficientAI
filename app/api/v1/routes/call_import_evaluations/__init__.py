"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

from app.api.v1.routes.call_import_evaluations import (  # noqa: F401
    aggregate,
    clusters,
    discovered,
    evaluation_cancel,
    evaluation_create,
    evaluation_read,
    evaluation_retry,
    exports,
    flow,
    insights,
    prompts,
    rows,
)
from app.api.v1.routes.call_import_evaluations._router import router
from app.core.auth.capabilities import EVALS_RUN, EVALS_VIEW, REPORTS_GENERATE
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=EVALS_VIEW,
    manage_capability=EVALS_RUN,
    run_capability=EVALS_RUN,
    report_capability=REPORTS_GENERATE,
)

from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _aggregate_primary_percent,
    _aggregate_to_dict,
    _child_names_by_parent,
    _compute_metric_aggregates,
    _explain_period_deltas,
    _period_delta_explanation_cache_key,
    _reconcile_cluster_periods,
)
from app.api.v1.routes.call_import_evaluations.discovered import (  # noqa: E402
    DISCOVERED_METRICS_KEY,
    _alias_map_for_parent,
    _get_running_discovered_labels,
    _get_running_discovered_metrics,
    _is_metric_scores_meta_key,
    _resolve_alias,
    _slug_label,
    normalize_scores_with_aliases,
)
from app.api.v1.routes.call_import_evaluations.exports import (  # noqa: E402
    _fail_stale_export_job,
)
from app.api.v1.routes.call_import_evaluations.flow import (  # noqa: E402
    _FLOW_START_NODE_ID,
    _build_flow_graph,
)
from app.api.v1.routes.call_import_evaluations.insights import (  # noqa: E402
    _generate_and_persist_tldr_summary,
    _tldr_summary_payload,
)
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _count_completed_eval_rows,
    _expand_metric_selection,
    _metrics_for_ids,
    _rollup_evaluation_status,
    _serialize_eval,
    _serialize_selected_metric_ids,
    require_call_import_capability,
)
from app.api.v1.routes.call_import_evaluations.evaluation_cancel import (  # noqa: E402
    EVAL_CANCELLED_BY_USER_ERROR,
)
from app.api.v1.routes.call_import_evaluations.evaluation_retry import (  # noqa: E402
    _enqueue_eval_rows_with_optional_transcribe,
    _metric_scores_for_retry,
    _prepare_source_row_for_retry,
    _reset_eval_row_for_retry,
    source_retry_assignments,
)
