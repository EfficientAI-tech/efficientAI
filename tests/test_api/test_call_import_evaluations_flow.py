"""Tests for the call import evaluation flow graph builder.

We exercise ``_build_flow_graph`` directly since it's a pure function
over the row's ``metric_scores`` payload — no DB round-trip required.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import (
    _build_flow_graph,
    _FLOW_START_NODE_ID,
)


def _row(metric_scores):
    return SimpleNamespace(metric_scores=metric_scores)


def _parent_and_children():
    parent = SimpleNamespace(
        id=uuid4(),
        name="Call Outcome",
        selection_mode="multi_label",
    )
    a = SimpleNamespace(id=uuid4(), name="connected")
    b = SimpleNamespace(id=uuid4(), name="answered")
    c = SimpleNamespace(id=uuid4(), name="hung_up")
    return parent, [a, b, c]


def test_flow_graph_emits_start_node_and_counts_transitions():
    parent, children = _parent_and_children()
    a, b, c = children
    parent_id_str = str(parent.id)
    rows = [
        _row(
            {
                parent_id_str: {
                    "sequence": ["connected", "answered", "hung_up"],
                }
            }
        ),
        _row(
            {
                parent_id_str: {
                    "sequence": ["connected", "hung_up"],
                }
            }
        ),
        _row(
            {
                parent_id_str: {
                    "sequence": ["connected", "answered", "hung_up"],
                }
            }
        ),
    ]

    flow = _build_flow_graph(rows, parent, children)

    assert flow.total_rows == 3
    assert flow.rows_with_sequence == 3

    node_by_id = {n.id: n for n in flow.nodes}
    # The synthetic START node is always emitted.
    assert _FLOW_START_NODE_ID in node_by_id
    assert node_by_id[_FLOW_START_NODE_ID].count == 3
    # ``connected`` appears in every sequence; ``hung_up`` in every
    # sequence too; ``answered`` in two of three.
    assert node_by_id[str(a.id)].count == 3
    assert node_by_id[str(b.id)].count == 2
    assert node_by_id[str(c.id)].count == 3

    # ``hung_up`` is the terminal of every row → above the 20% threshold
    # and should be flagged ``is_terminal``.
    assert node_by_id[str(c.id)].is_terminal is True
    # ``connected`` is never terminal so stays False.
    assert node_by_id[str(a.id)].is_terminal is False

    edge_map = {(e.source, e.target): e.count for e in flow.edges}
    # Two rows go connected -> answered, one goes connected -> hung_up.
    assert edge_map[(str(a.id), str(b.id))] == 2
    assert edge_map[(str(a.id), str(c.id))] == 1
    # Both answered rows go to hung_up.
    assert edge_map[(str(b.id), str(c.id))] == 2
    # Every row starts at ``connected`` so START -> connected counts 3.
    assert edge_map[(_FLOW_START_NODE_ID, str(a.id))] == 3


def test_flow_graph_ignores_rows_with_no_sequence():
    parent, children = _parent_and_children()
    a, _b, _c = children
    parent_id_str = str(parent.id)
    rows = [
        _row({parent_id_str: {"sequence": ["connected"]}}),
        # Missing sequence — count toward total_rows but not edges.
        _row({parent_id_str: {"value": "connected"}}),
        # No score for the parent at all.
        _row({}),
    ]

    flow = _build_flow_graph(rows, parent, children)
    assert flow.total_rows == 3
    assert flow.rows_with_sequence == 1
    node_by_id = {n.id: n for n in flow.nodes}
    assert node_by_id[str(a.id)].count == 1


def test_flow_graph_drops_unknown_keys_from_sequence():
    parent, children = _parent_and_children()
    a, _b, c = children
    parent_id_str = str(parent.id)
    rows = [
        _row(
            {
                parent_id_str: {
                    # ``bogus`` doesn't map to any child; it must be silently
                    # filtered so the flow stays inside the declared graph.
                    "sequence": ["connected", "bogus", "hung_up"],
                }
            }
        ),
    ]

    flow = _build_flow_graph(rows, parent, children)
    edge_map = {(e.source, e.target): e.count for e in flow.edges}
    # connected -> hung_up is the only transition that survives filtering.
    assert (str(a.id), str(c.id)) in edge_map
    assert (_FLOW_START_NODE_ID, str(a.id)) in edge_map


def test_flow_graph_resolves_child_uuids_in_sequence():
    parent, children = _parent_and_children()
    a, _b, c = children
    parent_id_str = str(parent.id)
    # Some clients persist child UUIDs in the sequence array instead of
    # the slug — the builder must resolve both shapes transparently.
    rows = [
        _row(
            {
                parent_id_str: {
                    "sequence": [str(a.id), str(c.id)],
                }
            }
        )
    ]
    flow = _build_flow_graph(rows, parent, children)
    edge_map = {(e.source, e.target): e.count for e in flow.edges}
    assert (str(a.id), str(c.id)) in edge_map
