"""Unit tests for the discovered-label helpers in
``app.api.v1.routes.call_import_evaluations``.

These exercise the in-memory transformations only — we don't spin up a
DB or FastAPI app. Functions under test:

  * ``_resolve_alias`` — transitive alias chain resolution + cycle guard.
  * ``_build_flow_graph`` — alias-aware sequence resolution and
    promoted-child takeover (slug previously rendered as discovered
    becomes a real child node once a matching ``Metric`` is present).
  * ``normalize_scores_with_aliases`` — rewriting per-row metric_scores
    so already-applied merges + promotions stick on rows that finish
    after the user's action.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.api.v1.routes.call_import_evaluations import (
    _build_flow_graph,
    _resolve_alias,
    _slug_label,
    normalize_scores_with_aliases,
)


# ---------------------------------------------------------------------------
# Tiny stand-ins for SQLAlchemy model rows. We only need the attributes
# the helpers actually read; nothing here touches the ORM session.
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, metric_scores: Dict[str, Any]):
        self.metric_scores = metric_scores


def _metric(
    *,
    name: str,
    selection_mode: Optional[str] = None,
    parent_id: Optional[UUID] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        selection_mode=selection_mode,
        parent_metric_id=parent_id,
    )


# ---------------------------------------------------------------------------
# _resolve_alias
# ---------------------------------------------------------------------------


def test_resolve_alias_returns_input_when_no_map():
    assert _resolve_alias({}, "anything") == "anything"


def test_resolve_alias_walks_chain():
    aliases = {"a": "b", "b": "c"}
    assert _resolve_alias(aliases, "a") == "c"


def test_resolve_alias_terminates_on_self_reference():
    aliases = {"a": "a"}
    assert _resolve_alias(aliases, "a") == "a"


def test_resolve_alias_breaks_cycles():
    aliases = {"a": "b", "b": "a"}
    # Either endpoint of the cycle is acceptable; the important thing
    # is that we don't loop forever.
    out = _resolve_alias(aliases, "a")
    assert out in {"a", "b"}


# ---------------------------------------------------------------------------
# _build_flow_graph
# ---------------------------------------------------------------------------


def _flow_payload(
    parent_id: UUID, sequence: List[str], discovered: List[Dict[str, Any]]
) -> Dict[str, Any]:
    return {
        str(parent_id): {
            "type": "category",
            "selection_mode": "multi_label",
            "sequence": sequence,
            "discovered_labels": discovered,
        }
    }


def test_flow_graph_treats_promoted_slug_as_real_child():
    parent = _metric(name="Wrapup Path", selection_mode="multi_label")
    welcome = _metric(name="Welcome", parent_id=parent.id)
    # The slug ``customer_on_hold`` was originally an LLM-discovered
    # candidate; the user has since promoted it into a real child.
    on_hold = _metric(name="Customer On Hold", parent_id=parent.id)

    rows = [
        _FakeRow(
            _flow_payload(
                parent.id,
                sequence=["welcome", "customer_on_hold"],
                discovered=[
                    {"key": "customer_on_hold", "name": "Customer on hold"},
                ],
            )
        ),
    ]
    graph = _build_flow_graph(rows, parent, [welcome, on_hold])

    real_child_ids = {str(welcome.id), str(on_hold.id)}
    assert real_child_ids.issubset({n.id for n in graph.nodes})
    # No "discovered" node should be emitted for the promoted slug —
    # the sequence step now resolves to the real child.
    assert not any(n.id.startswith("disc:") for n in graph.nodes)
    assert graph.rows_with_sequence == 1


def test_flow_graph_aliases_fold_into_canonical_target():
    parent = _metric(name="Outcome", selection_mode="multi_label")
    rows = [
        _FakeRow(
            _flow_payload(
                parent.id,
                sequence=["short_pause", "deescalation"],
                discovered=[
                    {"key": "short_pause", "name": "Short pause"},
                    {"key": "deescalation", "name": "Deescalation"},
                ],
            )
        ),
        _FakeRow(
            _flow_payload(
                parent.id,
                sequence=["pause", "deescalation"],
                discovered=[
                    {"key": "pause", "name": "Pause"},
                    {"key": "deescalation", "name": "Deescalation"},
                ],
            )
        ),
    ]
    # The user merged ``short_pause`` -> ``pause``. After the rewrite,
    # both rows should land on the same ``disc:pause`` node and the
    # transition counts should aggregate.
    graph = _build_flow_graph(
        rows, parent, [], alias_map={"short_pause": "pause"}
    )

    disc_ids = sorted(n.id for n in graph.nodes if n.id.startswith("disc:"))
    assert disc_ids == ["disc:deescalation", "disc:pause"]

    pause_to_deesc = next(
        (
            e
            for e in graph.edges
            if e.source == "disc:pause" and e.target == "disc:deescalation"
        ),
        None,
    )
    assert pause_to_deesc is not None
    assert pause_to_deesc.count == 2


def test_flow_graph_uses_extra_children_for_resolution_only():
    parent = _metric(name="Outcome", selection_mode="multi_label")
    legend_child = _metric(name="Welcome", parent_id=parent.id)
    # Promoted AFTER the eval was created — present as ``extra_children``.
    # Since it actually shows up in the sequence we expect a real node
    # for it (rather than a ``disc:`` placeholder).
    promoted = _metric(name="On Hold", parent_id=parent.id)
    # An unrelated promoted child that doesn't appear in any sequence —
    # we should NOT pollute the legend with this one.
    unused_promoted = _metric(name="Never Used", parent_id=parent.id)

    rows = [
        _FakeRow(
            _flow_payload(
                parent.id,
                sequence=["welcome", "on_hold"],
                discovered=[],
            )
        )
    ]
    graph = _build_flow_graph(
        rows,
        parent,
        [legend_child],
        extra_children=[promoted, unused_promoted],
    )

    node_ids = {n.id for n in graph.nodes}
    # The promoted slug resolves to its real child node; no
    # ``disc:`` redraw, no orphan edges.
    assert "disc:on_hold" not in node_ids
    assert str(promoted.id) in node_ids
    assert str(legend_child.id) in node_ids
    # An extra_child that never showed up in any sequence stays out of
    # the legend so unrelated promotions don't clutter the diagram.
    assert str(unused_promoted.id) not in node_ids


# ---------------------------------------------------------------------------
# normalize_scores_with_aliases
# ---------------------------------------------------------------------------


def _fake_evaluation(aliases_for_parent: Dict[str, str], parent_id: UUID):
    return SimpleNamespace(
        discovered_label_aliases={str(parent_id): aliases_for_parent}
    )


def _db_returning_child_names(names: List[str]) -> MagicMock:
    """Stub a SQLAlchemy session that returns the given child names.

    ``_promoted_child_slugs`` does ``db.query(Metric.name).filter(...).all()``
    — we just have to satisfy that fluent chain and return rows shaped
    like ``[(name,), ...]``.
    """
    db = MagicMock()
    chain = db.query.return_value.filter.return_value
    chain.all.return_value = [(n,) for n in names]
    return db


def test_normalize_scores_drops_promoted_discovered_entries():
    parent_id = uuid4()
    org_id = uuid4()
    db = _db_returning_child_names(["Customer On Hold"])

    scores = {
        str(parent_id): {
            "type": "category",
            "selection_mode": "multi_label",
            "sequence": ["welcome", "customer_on_hold"],
            "discovered_labels": [
                {"key": "customer_on_hold", "name": "Customer on hold"},
                {"key": "short_pause", "name": "Short pause"},
            ],
        }
    }
    evaluation = _fake_evaluation({}, parent_id)
    out = normalize_scores_with_aliases(scores, evaluation, db, org_id)

    discovered = out[str(parent_id)]["discovered_labels"]
    keys = [d["key"] for d in discovered]
    assert "customer_on_hold" not in keys
    assert "short_pause" in keys
    # Sequence is left intact (the promoted slug is still a valid
    # sequence step — it now resolves to the real child).
    assert out[str(parent_id)]["sequence"] == [
        "welcome",
        "customer_on_hold",
    ]


def test_normalize_scores_applies_alias_to_sequence_and_discovered():
    parent_id = uuid4()
    org_id = uuid4()
    db = _db_returning_child_names([])  # no promotions

    scores = {
        str(parent_id): {
            "type": "category",
            "selection_mode": "multi_label",
            "sequence": ["short_pause", "short_pause", "deescalation"],
            "discovered_labels": [
                {"key": "short_pause", "name": "Short pause"},
                {"key": "deescalation", "name": "Deescalation"},
            ],
        }
    }
    evaluation = _fake_evaluation({"short_pause": "pause"}, parent_id)
    out = normalize_scores_with_aliases(scores, evaluation, db, org_id)

    entry = out[str(parent_id)]
    # Adjacent dupes collapse after alias resolution.
    assert entry["sequence"] == ["pause", "deescalation"]
    keys = sorted(d["key"] for d in entry["discovered_labels"])
    assert keys == ["deescalation", "pause"]


def test_normalize_scores_ignores_non_parent_entries():
    parent_id = uuid4()
    org_id = uuid4()
    db = _db_returning_child_names([])
    boolean_metric_id = uuid4()

    scores = {
        # Plain boolean child — must be left untouched.
        str(boolean_metric_id): {
            "type": "boolean",
            "value": True,
            "metric_name": "Some Boolean",
        },
        str(parent_id): {
            "type": "category",
            "selection_mode": "multi_label",
            "sequence": ["a"],
            "discovered_labels": [{"key": "a", "name": "A"}],
        },
    }
    evaluation = _fake_evaluation({"a": "b"}, parent_id)
    out = normalize_scores_with_aliases(scores, evaluation, db, org_id)

    assert out[str(boolean_metric_id)] == {
        "type": "boolean",
        "value": True,
        "metric_name": "Some Boolean",
    }
    assert out[str(parent_id)]["sequence"] == ["b"]


# ---------------------------------------------------------------------------
# Sanity guard on the slug helper itself — many of the rewriting
# behaviors above only work because the slug function is stable.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Customer On Hold", "customer_on_hold"),
        ("  Mixed   spacing\t", "mixed_spacing"),
        ("ALREADY_SNAKE", "already_snake"),
        (None, ""),
        ("", ""),
    ],
)
def test_slug_label(raw, expected):
    assert _slug_label(raw) == expected
