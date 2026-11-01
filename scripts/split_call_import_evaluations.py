#!/usr/bin/env python3
"""One-off splitter for call_import_evaluations route package."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app/api/v1/routes/call_import_evaluations.py"
PKG = ROOT / "app/api/v1/routes/call_import_evaluations"

IMPORT_LINES = (1, 150)

RANGES: dict[str, list[tuple[int, int]]] = {
    "_shared": [
        (232, 689),
        (6292, 6317),
    ],
    "lifecycle": [
        (691, 1379),
        (4262, 4889),
        (9021, 9964),
    ],
    "rows": [
        (1380, 2072),
        (4695, 4803),
        (8924, 9004),
    ],
    "exports": [
        (159, 229),
        (2073, 2539),
        (3534, 4261),
    ],
    "aggregate": [
        (2590, 2612),
        (2626, 3533),
        (4890, 5397),
    ],
    "insights": [
        (5400, 6172),
    ],
    "clusters": [
        (2540, 2587),
        (6174, 6203),
        (6320, 6970),
    ],
    "prompts": [
        (6206, 6291),
        (6973, 7237),
    ],
    "flow": [
        (7248, 7250),
        (7820, 8182),
    ],
    "discovered": [
        (7253, 7819),
        (8185, 8922),
    ],
}

BRIDGE: dict[str, str] = {
    "_shared": "",
    "lifecycle": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _evaluation_bulk_operation_for_response,
    _expand_metric_selection,
    _metrics_for_ids,
    _normalize_name,
    _pick_evaluation_row_transcript,
    _require_import,
    _rollup_evaluation_status,
    _serialize_eval,
    _serialize_selected_metric_ids,
    _to_evaluation_row_response,
    require_call_import_capability,
)
""",
    "rows": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _pick_evaluation_row_transcript,
    _require_import,
    _rollup_evaluation_status,
    _to_evaluation_row_response,
)
from app.api.v1.routes.call_import_evaluations.lifecycle import (  # noqa: E402
    _apply_evaluation_cancel,
    _cancel_eval_row_with_source_diarisation,
    _revoke_eval_task,
)
""",
    "exports": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _metrics_for_ids,
    _require_import,
    _serialize_selected_metric_ids,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _aggregate_to_dict,
    _aggregate_primary_percent,
    _benchmark_context_for_evaluation,
    _benchmark_context_for_snapshot,
    _child_names_by_parent,
    _compute_metric_aggregates,
    _metric_is_user_insight,
    _period_deltas_from_aggregates,
    _period_deltas_from_evaluation,
    _period_deltas_from_snapshot,
    _period_deltas_with_explanations,
    _report_period_from_rows,
    _resolve_baseline_evaluation,
)
from app.api.v1.routes.call_import_evaluations.clusters import (  # noqa: E402
    _metrics_for_clustering,
    _selected_metric_clusters_for_pdf,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _audit_summary_text_from_tldr,
    _clamp_prose_to_sentences,
    _metric_insights_from_tldr,
)
from app.api.v1.routes.call_import_evaluations.insights import (  # noqa: E402
    _selected_generated_user_insights,
    _tldr_summary_payload,
)
from app.api.v1.routes.call_import_evaluations.prompts import (  # noqa: E402
    _selected_prompt_improvements_for_pdf,
)
from app.api.v1.routes.call_import_evaluations.lifecycle import (  # noqa: E402
    require_call_import_capability,
)
""",
    "aggregate": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _metrics_for_ids,
    _require_import,
    _serialize_selected_metric_ids,
)
""",
    "insights": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
    _serialize_selected_metric_ids,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _clamp_prose_to_sentences,
    _compute_metric_aggregates,
)
""",
    "clusters": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _completed_row_pairs_for_evaluation,
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.aggregate import (  # noqa: E402
    _child_names_by_parent,
    _clustering_context,
    _compute_metric_aggregates,
    _metric_is_user_insight,
)
""",
    "prompts": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.clusters import (  # noqa: E402
    _metric_clusters_payload,
)
from app.api.v1.routes.call_import_evaluations.lifecycle import (  # noqa: E402
    require_call_import_capability,
)
""",
    "flow": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _load_eval_rows,
    _metrics_for_ids,
    _require_import,
)
from app.api.v1.routes.call_import_evaluations.discovered import (  # noqa: E402
    _alias_map_for_parent,
    _promoted_child_slugs,
    _resolve_alias,
    _slug_label,
)
""",
    "discovered": """
from app.api.v1.routes.call_import_evaluations._shared import (  # noqa: E402
    _require_import,
)
""",
}


def slice_lines(all_lines: list[str], start: int, end: int) -> list[str]:
    return all_lines[start - 1 : end]


def build_module_body(all_lines: list[str], ranges: list[tuple[int, int]]) -> str:
    chunks: list[str] = []
    for start, end in ranges:
        chunks.extend(slice_lines(all_lines, start, end))
    return "".join(chunks)


def import_header(all_lines: list[str]) -> str:
    return "".join(slice_lines(all_lines, *IMPORT_LINES))


def validate_syntax(path: Path) -> None:
    ast.parse(path.read_text(), filename=str(path))


def write_module(name: str, body: str, *, is_shared: bool = False) -> None:
    header = import_header(all_lines)
    bridge = BRIDGE.get(name, "")
    if is_shared:
        content = f"{header}\n{body}"
    else:
        content = (
            f"{header}\n"
            "from app.api.v1.routes.call_import_evaluations._router import (  # noqa: E402\n"
            "    sub_router as router,\n"
            ")\n"
            f"{bridge}\n{body}"
        )
    if not content.endswith("\n"):
        content += "\n"
    path = PKG / f"{name}.py"
    path.write_text(content)
    validate_syntax(path)


all_lines = SRC.read_text().splitlines(keepends=True)
if not all_lines:
    sys.exit(f"Missing source: {SRC}")

PKG.mkdir(parents=True, exist_ok=True)

(PKG / "_router.py").write_text(
    '"""Shared route collector for call import evaluation endpoints."""\n\n'
    "from fastapi import APIRouter\n\n"
    "sub_router = APIRouter()\n"
)

for mod, ranges in RANGES.items():
    write_module(mod, build_module_body(all_lines, ranges), is_shared=(mod == "_shared"))

init = '''"""Evaluation routes scoped to a Call Import batch."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import require_enterprise_feature

from app.api.v1.routes.call_import_evaluations import (  # noqa: F401
    aggregate,
    clusters,
    discovered,
    exports,
    flow,
    insights,
    lifecycle,
    prompts,
    rows,
)
from app.api.v1.routes.call_import_evaluations._router import sub_router
from app.core.auth.capabilities import EVALS_RUN, EVALS_VIEW, REPORTS_GENERATE
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

router = APIRouter(
    prefix="/call-imports/{call_import_id}/evaluations",
    tags=["Call Import Evaluations"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)

router.include_router(sub_router)

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
    _metrics_for_ids,
    _serialize_selected_metric_ids,
)
from app.api.v1.routes.call_import_evaluations.discovered import (  # noqa: E402
    DISCOVERED_METRICS_KEY,
    _get_running_discovered_labels,
    _get_running_discovered_metrics,
    _is_metric_scores_meta_key,
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
)
from app.api.v1.routes.call_import_evaluations.lifecycle import (  # noqa: E402
    EVAL_CANCELLED_BY_USER_ERROR,
    _enqueue_eval_rows_with_optional_transcribe,
    _expand_metric_selection,
    _metric_scores_for_retry,
    _reset_eval_row_for_retry,
    _rollup_evaluation_status,
    _serialize_eval,
    require_call_import_capability,
    source_retry_assignments,
)

'''
(PKG / "__init__.py").write_text(init)
print("Wrote package modules under", PKG)
