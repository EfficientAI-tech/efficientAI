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
