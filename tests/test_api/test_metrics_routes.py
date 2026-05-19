"""API tests for metrics routes."""

import textwrap


def test_create_and_list_metrics(authenticated_client):
    payload = {
        "name": "Resolution Quality",
        "description": "Checks if the issue was resolved",
        "metric_type": "rating",
        "trigger": "always",
        "enabled": True,
    }
    create_response = authenticated_client.post("/api/v1/metrics", json=payload)

    assert create_response.status_code == 201
    assert create_response.json()["name"] == "Resolution Quality"

    list_response = authenticated_client.get("/api/v1/metrics")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_metric(authenticated_client, make_metric):
    metric = make_metric(name="Old Name", metric_type="number")

    response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"name": "New Name", "enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
    assert response.json()["enabled"] is False


def test_delete_metric(authenticated_client, make_metric):
    metric = make_metric(name="Delete Me")

    response = authenticated_client.delete(f"/api/v1/metrics/{metric.id}")

    assert response.status_code == 204


# =============================================================================
# capture_rationale: round-trips on create / update / response
# =============================================================================


def test_create_metric_with_capture_rationale_true(authenticated_client):
    payload = {
        "name": "Pitch Type",
        "description": "Classify how the agent pitched.",
        "metric_type": "rating",
        "custom_data_type": "enum",
        "custom_config": {"options": ["With data", "Without data"]},
        "capture_rationale": True,
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["capture_rationale"] is True


def test_create_metric_capture_rationale_defaults_false(authenticated_client):
    payload = {
        "name": "No Rationale",
        "description": "...",
        "metric_type": "rating",
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["capture_rationale"] is False


def test_update_metric_capture_rationale(authenticated_client, make_metric):
    metric = make_metric(name="Toggle Rationale")
    response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"capture_rationale": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["capture_rationale"] is True

    response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"capture_rationale": False},
    )
    assert response.status_code == 200
    assert response.json()["capture_rationale"] is False


# =============================================================================
# /metrics/parse-bulk: Label-block parser
# =============================================================================


_MEESHO_PROMPT = textwrap.dedent(
    """
    Label #1

    Label Name
    Pitch done WITH data (personalized growth/category stats)
    Label Definition
    The pitch window contains any numeric data tied to the seller or their category.

    This data may appear:

    In the first bot message OR
    In subsequent bot messages within the pitch window
    Example (Optional)
    Example 1 (data in first turn):
    assistant: Meesho par sale aa rahi hai. Aapke orders mein 120 percent growth hua tha.

    Label #2

    Label Name
    Pitch done WITHOUT data (generic pitch)
    Label Definition
    The pitch window contains no seller/category-specific numeric data.

    Only generic benefits or scale statements are present.
    Example (Optional)
    Example 1:
    assistant: Meesho par sale aa rahi hai jisme 10 crore buyers expected hain

    Label #3

    Label Name
    Others - Pitch did not happen at all
    Label Definition
    No valid pitch window exists.

    Use when:

    No sale/growth discussion happens
    Conversation derails before pitch
    Only greeting or identity check
    Transcript unusable
    Example (Optional)
    Example 1 (no pitch):
    assistant: kya meri baat seller se ho rahi hai?
    user: galat number
    """
).strip()


def test_parse_bulk_metric_returns_one_draft_per_label(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": _MEESHO_PROMPT, "surface": "agent"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    drafts = body["metrics"]
    # Each "Label #N" block becomes its own draft metric — three in this prompt.
    assert len(drafts) == 3

    # Names must be preserved verbatim (no summarising) — they're derived from
    # the "Label Name" block and used as the proposed metric name.
    assert drafts[0]["name"].startswith("Pitch done WITH data")
    assert drafts[1]["name"].startswith("Pitch done WITHOUT data")
    assert drafts[2]["name"].startswith("Others")

    for draft in drafts:
        # Defaults reflect the most common case: "did <X> happen?" → boolean
        # with a free-form rationale.
        assert draft["metric_type"] == "boolean"
        assert draft["custom_data_type"] == "boolean"
        assert draft["capture_rationale"] is True
        # Surface plumbed through to every draft.
        assert draft["supported_surfaces"] == ["agent"]
        assert draft["enabled_surfaces"] == ["agent"]
        # The source label round-trips so the modal can show the rubric.
        assert "label_name" in draft["source_label"]

    # Description for each draft should embed that label's own definition (not
    # the entire prompt) so the LLM-judge sees a per-metric rubric.
    assert "first bot message" in drafts[0]["description"]
    assert "no seller/category-specific numeric data" in drafts[1]["description"]
    assert "No valid pitch window" in drafts[2]["description"]


def test_parse_bulk_metric_returns_single_draft_for_lone_label(authenticated_client):
    # A single Label #N block should still produce one draft now (used to
    # require >=2 labels when we built one enum metric).
    prompt = textwrap.dedent(
        """
        Label #1

        Label Name
        Language Adherence
        Label Definition
        The agent stays in the customer's language for the entire conversation.
        """
    ).strip()

    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": prompt, "surface": "agent"},
    )
    assert response.status_code == 200, response.text
    drafts = response.json()["metrics"]
    assert len(drafts) == 1
    assert drafts[0]["name"] == "Language Adherence"
    assert drafts[0]["metric_type"] == "boolean"
    assert drafts[0]["capture_rationale"] is True


def test_parse_bulk_metric_rejects_empty_prompt(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": "   ", "surface": "agent"},
    )
    assert response.status_code == 400


def test_parse_bulk_metric_rejects_unparseable_prompt(authenticated_client, monkeypatch):
    # The deterministic regex won't match this format and the LLM fallback
    # is patched to return nothing, so the endpoint must surface a 422.
    from app.api.v1.routes import metrics as metrics_module

    monkeypatch.setattr(
        metrics_module, "_llm_parse_labels", lambda *args, **kwargs: []
    )

    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": "just a single sentence with no label structure", "surface": "agent"},
    )
    assert response.status_code == 422


def test_parse_bulk_metric_auto_suffixes_on_name_conflict(
    authenticated_client, make_metric
):
    # Pre-create a metric whose name collides with the FIRST parsed label so
    # the route is forced to auto-suffix that draft (other drafts must
    # remain unchanged so order is preserved).
    make_metric(name="Pitch done WITH data (personalized growth/category stats)")
    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": _MEESHO_PROMPT, "surface": "agent"},
    )
    assert response.status_code == 200, response.text
    drafts = response.json()["metrics"]
    assert drafts[0]["name"].endswith("(2)")
    assert drafts[1]["name"].startswith("Pitch done WITHOUT data")
    assert drafts[2]["name"].startswith("Others")


def test_parse_bulk_metric_avoids_intra_batch_name_collisions(authenticated_client):
    # Two identically-named labels in the prompt would otherwise produce
    # two drafts with the same name; the route must dedupe to one.
    prompt = textwrap.dedent(
        """
        Label #1

        Label Name
        Greeting
        Label Definition
        Did the agent greet the user?

        Label #2

        Label Name
        Greeting
        Label Definition
        Duplicate label that should be dropped.
        """
    ).strip()

    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={"prompt": prompt, "surface": "agent"},
    )
    assert response.status_code == 200, response.text
    drafts = response.json()["metrics"]
    # Duplicates dedupe to one draft (preserving the first occurrence).
    assert len(drafts) == 1
    assert drafts[0]["name"] == "Greeting"


# =============================================================================
# Hierarchical metrics: parent/child CRUD + invariants
# =============================================================================


def _parent_payload(**overrides):
    payload = {
        "name": "Call Outcome",
        "description": "High-level category of how the call ended.",
        "metric_type": "boolean",
        "selection_mode": "single_choice",
    }
    payload.update(overrides)
    return payload


def _child_payload(**overrides):
    payload = {
        "name": "happy_completion",
        "description": "Customer answered every question and was satisfied.",
        "metric_type": "boolean",
    }
    payload.update(overrides)
    return payload


def test_create_parent_metric_with_selection_mode(authenticated_client):
    response = authenticated_client.post("/api/v1/metrics", json=_parent_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selection_mode"] == "single_choice"
    assert body["parent_metric_id"] is None


def test_create_child_metric_links_to_parent(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics", json=_parent_payload()
    ).json()
    response = authenticated_client.post(
        "/api/v1/metrics",
        json=_child_payload(parent_metric_id=parent["id"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parent_metric_id"] == parent["id"]
    # Children must not carry a selection_mode.
    assert body["selection_mode"] is None


def test_create_metric_with_children_atomic(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Call Outcome",
            "description": "High-level category of how the call ended.",
            "selection_mode": "multi_label",
            "children": [
                {"name": "call_connected", "description": "did connect"},
                {
                    "name": "customer_answered_some",
                    "description": "answered some",
                },
                {"name": "customer_hung_up", "description": "hung up"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selection_mode"] == "multi_label"
    assert len(body["children"]) == 3
    assert {c["name"] for c in body["children"]} == {
        "call_connected",
        "customer_answered_some",
        "customer_hung_up",
    }
    for child in body["children"]:
        assert child["parent_metric_id"] == body["id"]
        assert child["selection_mode"] is None


def test_post_child_to_existing_parent(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics", json=_parent_payload()
    ).json()
    response = authenticated_client.post(
        f"/api/v1/metrics/{parent['id']}/children",
        json=_child_payload(name="angry_hangup"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["parent_metric_id"] == parent["id"]


def test_reject_grandchild_metric(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics", json=_parent_payload()
    ).json()
    child = authenticated_client.post(
        "/api/v1/metrics",
        json=_child_payload(parent_metric_id=parent["id"]),
    ).json()
    # Try to nest a grandchild under the child — must be rejected because
    # depth is capped at 2.
    response = authenticated_client.post(
        "/api/v1/metrics",
        json=_child_payload(name="grandkid", parent_metric_id=child["id"]),
    )
    assert response.status_code == 400, response.text


def test_reject_selection_mode_on_child(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics", json=_parent_payload()
    ).json()
    response = authenticated_client.post(
        "/api/v1/metrics",
        json=_child_payload(
            parent_metric_id=parent["id"], selection_mode="multi_label"
        ),
    )
    assert response.status_code == 400


def test_reject_invalid_selection_mode_value(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics",
        json=_parent_payload(selection_mode="some_random_mode"),
    )
    assert response.status_code == 422


def test_list_metrics_returns_tree_by_default(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Call Outcome",
            "description": "Outcome category.",
            "selection_mode": "single_choice",
            "children": [
                {"name": "child_a", "description": "first"},
                {"name": "child_b", "description": "second"},
            ],
        },
    ).json()
    response = authenticated_client.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    # Default list response embeds children under the parent and never
    # returns children at the top level.
    parent_entries = [m for m in body if m["id"] == parent["id"]]
    assert len(parent_entries) == 1
    assert len(parent_entries[0]["children"]) == 2
    top_level_ids = {m["id"] for m in body}
    for child in parent_entries[0]["children"]:
        assert child["id"] not in top_level_ids


def test_list_metrics_flat_includes_children_at_top_level(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Pitch Outcome",
            "description": "Pitch outcome.",
            "selection_mode": "single_choice",
            "children": [{"name": "leaf_one", "description": "one"}],
        },
    ).json()
    response = authenticated_client.get(
        "/api/v1/metrics?include_children=false"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {m["id"] for m in body}
    assert parent["id"] in ids
    # Flat mode returns children alongside parents (caller flattens
    # itself), and the parent entry omits a children list.
    leaf_ids = [m for m in body if m.get("parent_metric_id") == parent["id"]]
    assert len(leaf_ids) == 1


def test_delete_parent_cascades_children(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Cascade Outcome",
            "description": "Outcome.",
            "selection_mode": "single_choice",
            "children": [{"name": "leaf_one", "description": "leaf"}],
        },
    ).json()
    child_id = parent["children"][0]["id"]
    delete_response = authenticated_client.delete(
        f"/api/v1/metrics/{parent['id']}"
    )
    assert delete_response.status_code == 204
    # Direct GET on the child should now 404 — FK ``ON DELETE CASCADE``
    # removes the row alongside its parent.
    get_response = authenticated_client.get(f"/api/v1/metrics/{child_id}")
    assert get_response.status_code == 404


def test_parse_bulk_creates_hierarchy_when_parent_supplied(authenticated_client):
    # When parent_name + selection_mode are passed, the parsed labels
    # become children of the new parent metric rather than free-floating
    # boolean metrics.
    response = authenticated_client.post(
        "/api/v1/metrics/parse-bulk",
        json={
            "prompt": _MEESHO_PROMPT,
            "surface": "agent",
            "parent_name": "Pitch Outcome",
            "parent_description": "Whether the pitch landed.",
            "selection_mode": "single_choice",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Backend returns a parent draft alongside the child drafts.
    assert body.get("parent") is not None
    assert body["parent"]["name"] == "Pitch Outcome"
    assert body["parent"]["selection_mode"] == "single_choice"
    assert len(body["metrics"]) == 3


# =============================================================================
# allow_discovery + promote-discovered endpoint
# =============================================================================


def test_create_multi_label_parent_with_allow_discovery(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Discovery Outcome",
            "description": "Multi-label with discovery enabled.",
            "selection_mode": "multi_label",
            "allow_discovery": True,
            "children": [{"name": "first_label", "description": "..."}],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["allow_discovery"] is True
    assert body["selection_mode"] == "multi_label"


def test_allow_discovery_accepted_on_single_choice_parent(authenticated_client):
    """Single_choice parents can opt into LLM discovery too.

    Discovered labels for single_choice are supplemental — the worker
    + prompt builder keep the "exactly one true" invariant intact and
    surface the discovered entries as analytics-only candidates the
    user can later promote into real children.
    """
    response = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Outcome Pickone",
            "description": "...",
            "selection_mode": "single_choice",
            "allow_discovery": True,
            "children": [{"name": "leaf", "description": "..."}],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["allow_discovery"] is True
    assert body["selection_mode"] == "single_choice"


def test_reject_allow_discovery_on_standalone_metric(authenticated_client):
    """``allow_discovery`` still requires a parent (selection_mode set)."""
    response = authenticated_client.post(
        "/api/v1/metrics",
        json={
            "name": "Lonely",
            "description": "...",
            "metric_type": "boolean",
            "trigger": "always",
            "enabled": True,
            "allow_discovery": True,
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "selection_mode" in detail or "parent" in detail


def test_promote_discovered_child_creates_real_metric(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Outcome",
            "description": "...",
            "selection_mode": "multi_label",
            "allow_discovery": True,
            "children": [{"name": "first_label", "description": "..."}],
        },
    ).json()

    response = authenticated_client.post(
        f"/api/v1/metrics/{parent['id']}/children/from-discovered",
        json={
            "key": "customer_on_hold",
            "name": "customer on hold",
            "description": "agent placed caller on hold",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # The new child is nested under the parent in the response.
    child_names = {c["name"] for c in body["children"]}
    assert "customer on hold" in child_names


def test_promote_discovered_child_rejects_slug_mismatch(authenticated_client):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Outcome Mismatch",
            "description": "...",
            "selection_mode": "multi_label",
            "allow_discovery": True,
            "children": [{"name": "first_label", "description": "..."}],
        },
    ).json()
    response = authenticated_client.post(
        f"/api/v1/metrics/{parent['id']}/children/from-discovered",
        json={
            "key": "customer_on_hold",
            # The name's slug is "fancy_label" — does NOT match the key.
            # We reject because the worker's sequence arrays would
            # otherwise stop resolving once the candidate is removed.
            "name": "Fancy Label",
            "description": "...",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "slugify" in detail or "slug" in detail


def test_promote_discovered_child_works_on_single_choice_parent(
    authenticated_client,
):
    """Single_choice parents with allow_discovery can still promote
    discovered candidates into real children."""
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Pickone",
            "description": "...",
            "selection_mode": "single_choice",
            "allow_discovery": True,
            "children": [{"name": "first_label", "description": "..."}],
        },
    ).json()
    response = authenticated_client.post(
        f"/api/v1/metrics/{parent['id']}/children/from-discovered",
        json={
            "key": "another_outcome",
            "name": "another outcome",
            "description": "newly discovered single-choice candidate",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    child_names = {c["name"] for c in body["children"]}
    assert "another outcome" in child_names


def test_promote_discovered_child_rejects_when_discovery_disabled(
    authenticated_client,
):
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "No Discovery",
            "description": "...",
            "selection_mode": "multi_label",
            "allow_discovery": False,
            "children": [{"name": "first_label", "description": "..."}],
        },
    ).json()
    response = authenticated_client.post(
        f"/api/v1/metrics/{parent['id']}/children/from-discovered",
        json={
            "key": "anything",
            "name": "anything",
            "description": "...",
        },
    )
    assert response.status_code == 400
    assert "allow_discovery" in response.json()["detail"]


# =============================================================================
# input_columns: column-input judge metric round-trips and validation
# =============================================================================


def test_create_metric_with_input_columns_round_trip(authenticated_client):
    """A non-empty ``input_columns`` is persisted and returned by the API."""
    payload = {
        "name": "Column-Input Judge",
        "description": "Score the customer_intent + agent_response columns",
        "metric_type": "rating",
        "input_columns": ["customer_intent", "agent_response"],
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["input_columns"] == ["customer_intent", "agent_response"]

    list_response = authenticated_client.get("/api/v1/metrics")
    assert list_response.status_code == 200
    [created] = [m for m in list_response.json() if m["name"] == "Column-Input Judge"]
    assert created["input_columns"] == ["customer_intent", "agent_response"]


def test_create_metric_input_columns_defaults_to_empty_list(authenticated_client):
    """Omitting ``input_columns`` leaves the metric in transcript-judge mode."""
    payload = {
        "name": "Plain Transcript Judge",
        "description": "...",
        "metric_type": "rating",
    }
    response = authenticated_client.post("/api/v1/metrics", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["input_columns"] == []


def test_create_metric_rejects_blank_input_column_entry(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics",
        json={
            "name": "Blank Header",
            "description": "...",
            "metric_type": "rating",
            "input_columns": ["customer_intent", "   "],
        },
    )
    assert response.status_code == 400
    assert "input_columns" in response.json()["detail"]


def test_create_metric_input_columns_dedupes_case_insensitively(
    authenticated_client,
):
    """Duplicate entries differing only in case collapse to a single value."""
    response = authenticated_client.post(
        "/api/v1/metrics",
        json={
            "name": "Dedupe Headers",
            "description": "...",
            "metric_type": "rating",
            "input_columns": ["Customer_Intent", "customer_intent", "agent_response"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # First-occurrence wins; duplicates are dropped.
    assert body["input_columns"] == ["Customer_Intent", "agent_response"]


def test_create_child_metric_with_input_columns_is_rejected(authenticated_client):
    """Child sub-metrics cannot opt into the column-input feature."""
    parent = authenticated_client.post(
        "/api/v1/metrics/with-children",
        json={
            "name": "Outcome Buckets",
            "description": "...",
            "selection_mode": "single_choice",
            "children": [{"name": "happy_path", "description": "..."}],
        },
    ).json()

    response = authenticated_client.post(
        "/api/v1/metrics",
        json={
            "name": "Bad Child",
            "description": "...",
            "metric_type": "boolean",
            "parent_metric_id": parent["id"],
            "input_columns": ["customer_intent"],
        },
    )
    assert response.status_code == 400
    assert "input_columns" in response.json()["detail"]


def test_update_metric_input_columns(authenticated_client, make_metric):
    """PUT with a list rewrites ``input_columns``; an empty list clears it."""
    metric = make_metric(name="Rewriteable Inputs")

    set_response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"input_columns": ["customer_intent"]},
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["input_columns"] == ["customer_intent"]

    clear_response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"input_columns": []},
    )
    assert clear_response.status_code == 200, clear_response.text
    assert clear_response.json()["input_columns"] == []


def test_update_metric_input_columns_omitted_leaves_value_unchanged(
    authenticated_client, make_metric
):
    """Sending ``None`` (i.e. omitting the field) preserves the existing list."""
    metric = make_metric(name="Sticky Inputs")

    authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"input_columns": ["foo", "bar"]},
    )

    response = authenticated_client.put(
        f"/api/v1/metrics/{metric.id}",
        json={"description": "unrelated change"},
    )
    assert response.status_code == 200
    assert response.json()["input_columns"] == ["foo", "bar"]
