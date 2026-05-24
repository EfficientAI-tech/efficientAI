"""Tests for the hierarchy-aware bits of the call import evaluation route.

We focus on the pure helpers (``_expand_metric_selection``) and the small
serialization helpers so we don't have to spin up the full Celery
worker stack. End-to-end behavior (worker prompt + parse) is covered in
``tests/test_workers/test_llm_evaluation_hierarchy.py``.
"""

from uuid import uuid4

from app.api.v1.routes.call_import_evaluations import _expand_metric_selection


def test_expand_parent_only_selection_pulls_in_all_enabled_children(
    db_session, org_id, make_metric
):
    parent = make_metric(name="Outcome", selection_mode="single_choice")
    c1 = make_metric(
        name="happy_completion",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )
    c2 = make_metric(
        name="angry_hangup",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )
    disabled = make_metric(
        name="ghost_label",
        metric_type="boolean",
        parent_metric_id=parent.id,
        enabled=False,
    )

    effective, parent_to_children = _expand_metric_selection(
        db_session, org_id, [parent.id]
    )

    effective_ids = {m.id for m in effective}
    # The parent itself never appears in the effective list — only its
    # children are scored.
    assert parent.id not in effective_ids
    assert c1.id in effective_ids
    assert c2.id in effective_ids
    # Disabled children are filtered out so the worker doesn't waste a
    # scoring slot on labels the user hid.
    assert disabled.id not in effective_ids
    # Grouping mirrors the parent->children relationship for the LLM
    # prompt builder.
    assert parent.id in parent_to_children
    assert {c.id for c in parent_to_children[parent.id]} == {c1.id, c2.id}


def test_expand_explicit_children_respects_user_filter(
    db_session, org_id, make_metric
):
    parent = make_metric(name="Outcome", selection_mode="multi_label")
    c1 = make_metric(
        name="connected",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )
    c2 = make_metric(
        name="answered",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )
    make_metric(
        name="hung_up",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )

    effective, parent_to_children = _expand_metric_selection(
        db_session, org_id, [parent.id, c1.id, c2.id]
    )

    effective_ids = {m.id for m in effective}
    # Even though the parent is selected, only the explicit subset is
    # used so the user can deselect specific labels without un-checking
    # the parent.
    assert effective_ids == {c1.id, c2.id}
    assert {c.id for c in parent_to_children[parent.id]} == {c1.id, c2.id}


def test_expand_standalone_metric_passes_through(db_session, org_id, make_metric):
    parent = make_metric(name="Outcome", selection_mode="single_choice")
    child = make_metric(
        name="happy",
        metric_type="boolean",
        parent_metric_id=parent.id,
    )
    standalone = make_metric(name="Resolution", metric_type="rating")

    effective, parent_to_children = _expand_metric_selection(
        db_session, org_id, [parent.id, standalone.id]
    )

    ids = [m.id for m in effective]
    # Standalone metric round-trips unchanged; the parent expands to the
    # one enabled child.
    assert standalone.id in ids
    assert child.id in ids
    assert parent.id not in ids
    # Standalone metrics never end up in parent_to_children.
    assert standalone.id not in parent_to_children


def test_expand_empty_selection_returns_empty(db_session, org_id):
    effective, parent_to_children = _expand_metric_selection(
        db_session, org_id, []
    )
    assert effective == []
    assert parent_to_children == {}


def test_expand_skips_unknown_ids(db_session, org_id, make_metric):
    standalone = make_metric(name="Resolution", metric_type="rating")
    bogus = uuid4()

    effective, _ = _expand_metric_selection(
        db_session, org_id, [bogus, standalone.id]
    )
    # Garbage ids are dropped silently — the route is responsible for
    # surfacing user-facing 4xx errors when nothing remains.
    assert [m.id for m in effective] == [standalone.id]
