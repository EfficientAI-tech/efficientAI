"""Tests for ``POST /api/v1/metrics/from-discovered``.

Promotes an LLM-discovered top-level metric candidate into a real
standalone :class:`Metric` row. Mirrors the existing
``test_promote_discovered_child_*`` tests but for the new
parent-less promote path.
"""


def test_promote_discovered_metric_creates_standalone_boolean(
    authenticated_client,
):
    response = authenticated_client.post(
        "/api/v1/metrics/from-discovered",
        json={
            "key": "needs_human_handoff",
            "name": "needs human handoff",
            "description": "true when the caller asks for an agent",
            "metric_type": "boolean",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "needs human handoff"
    # Slug invariant: name slugifies back to the key so any
    # already-scored rows that referenced the candidate keep
    # resolving against the promoted metric.
    assert body["name"].replace(" ", "_") == "needs_human_handoff"
    # No parent — standalone.
    assert body.get("parent_metric_id") in (None, "")
    # Default settings: enabled, capture_rationale on by default to
    # mirror discovered-labels promote UX.
    assert body["enabled"] is True
    assert body["capture_rationale"] is True


def test_promote_discovered_metric_supports_rating_type(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/metrics/from-discovered",
        json={
            "key": "customer_satisfaction",
            "name": "customer satisfaction",
            "description": "0-1 rating of how the customer left the call",
            "metric_type": "rating",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # MetricType serializes lowercase via the str enum.
    assert body["metric_type"].lower() == "rating"


def test_promote_discovered_metric_category_creates_multi_label_parent(
    authenticated_client,
):
    """``category`` becomes a parent (multi_label) with no children
    yet; the user adds children afterwards in the Metrics page."""

    response = authenticated_client.post(
        "/api/v1/metrics/from-discovered",
        json={
            "key": "call_outcome",
            "name": "call outcome",
            "description": "Bucket of distinct call outcomes",
            "metric_type": "category",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selection_mode"] == "multi_label"
    assert body.get("children", []) == []


def test_promote_discovered_metric_rejects_slug_mismatch(authenticated_client):
    """The slug(name) == key invariant is enforced server-side so the
    promoted metric stays addressable by the slug under which
    already-scored rows referenced it."""

    response = authenticated_client.post(
        "/api/v1/metrics/from-discovered",
        json={
            "key": "customer_intent",
            # ``slug("Fancy Metric")`` is "fancy_metric" -- doesn't
            # match the key.
            "name": "Fancy Metric",
            "metric_type": "boolean",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "slug" in detail.lower()


def test_promote_discovered_metric_rejects_duplicate_name(authenticated_client):
    payload = {
        "key": "first_call_resolution",
        "name": "first call resolution",
        "description": "whether the issue resolved on the first call",
        "metric_type": "boolean",
    }
    first = authenticated_client.post("/api/v1/metrics/from-discovered", json=payload)
    assert first.status_code == 201, first.text
    second = authenticated_client.post(
        "/api/v1/metrics/from-discovered", json=payload
    )
    assert second.status_code == 400
    assert "already exists" in second.json()["detail"]
