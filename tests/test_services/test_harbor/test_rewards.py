"""Reward normalization from platform metric scores to Harbor rewards."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.harbor.rewards import compute_rewards, metric_reward_key, normalize_metric_score


def _metric(name="Empathy", metric_type="rating", **kw):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        metric_type=metric_type,
        parent_metric_id=None,
        custom_config=None,
        **kw,
    )


@pytest.mark.parametrize(
    "entry,metric_type,expected",
    [
        ({"value": 0.8, "type": "rating"}, "rating", 0.8),
        ({"value": 1.7, "type": "rating"}, "rating", 1.0),
        ({"value": True, "type": "boolean"}, "boolean", 1.0),
        ({"value": False, "type": "boolean"}, "boolean", 0.0),
        ({"value": "yes", "type": "boolean"}, "boolean", 1.0),
        ({"value": "free text", "type": "text"}, "text", None),
        ({"value": None, "type": "rating"}, "rating", None),
        ({"value": 0.9, "type": "rating", "error": "timeout"}, "rating", None),
        ({"value": None, "type": "rating", "skipped": "audio_required"}, "rating", None),
    ],
)
def test_normalize_metric_score(entry, metric_type, expected):
    assert normalize_metric_score(entry, _metric(metric_type=metric_type)) == expected


def test_number_metric_uses_custom_range():
    metric = _metric(metric_type="number")
    metric.custom_config = {"min": 0, "max": 20}
    assert normalize_metric_score({"value": 5, "type": "number"}, metric) == 0.25
    metric.custom_config = None
    assert normalize_metric_score({"value": 5, "type": "number"}, metric) is None


def test_categorization_children_do_not_count():
    child = _metric(metric_type="boolean")
    child.parent_metric_id = uuid4()
    assert normalize_metric_score({"value": True, "type": "boolean"}, child) is None


def test_compute_rewards_aggregates_mean_and_unique_keys():
    a, b, c = _metric("Empathy"), _metric("Empathy", "boolean"), _metric("Summary", "text")
    scores = {
        str(a.id): {"value": 0.5, "type": "rating"},
        str(b.id): {"value": True, "type": "boolean"},
        str(c.id): {"value": "ok", "type": "text"},
    }
    aggregate, rewards, ids = compute_rewards(scores, [a, b, c])
    assert aggregate == 0.75
    assert rewards == {"empathy": 0.5, "empathy_2": 1.0}
    assert ids == {"empathy": str(a.id), "empathy_2": str(b.id)}


def test_compute_rewards_none_when_nothing_scorable():
    assert compute_rewards({}, [_metric()]) == (None, {}, {})


def test_metric_reward_key_never_shadows_aggregate():
    assert metric_reward_key("Reward", {"reward"}) == "metric_reward"
