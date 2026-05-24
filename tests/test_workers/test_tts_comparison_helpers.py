"""Unit tests for app.workers.tasks.tts_comparison helpers.

Covers:
- _filter_qualitative_metrics: drops disabled qualitative audio keys, preserves
  WER/CER/ASR Transcript and any other passthrough keys.
- _load_enabled_voice_metric_names: returns a lowercased set of metric names
  that are enabled on the voice_playground surface for a given org.
"""

from uuid import uuid4

from app.models.database import Metric, Organization, Workspace
from app.workers.tasks import tts_comparison


# ---------------------------------------------------------------------------
# _filter_qualitative_metrics
# ---------------------------------------------------------------------------

def _all_metrics_dict():
    """A representative dict matching what qualitative_voice_service returns
    plus the auxiliary keys the worker adds in the same evaluation_metrics blob."""
    return {
        "MOS Score": 4.2,
        "Valence": 0.3,
        "Arousal": 0.6,
        "Prosody Score": 0.7,
        "Emotion Category": "happy",
        "Emotion Confidence": 0.85,
        "Speaker Consistency": 0.92,
        "WER": 0.04,
        "CER": 0.01,
        "ASR Transcript": "the quick brown fox",
        "custom_metric_scores": {
            "uuid-1": {"value": 0.8, "type": "rating", "metric_name": "Tone"}
        },
    }


def test_filter_qualitative_metrics_drops_disabled_qualitative_keys():
    enabled_lower = {"mos score", "valence"}
    out = tts_comparison._filter_qualitative_metrics(_all_metrics_dict(), enabled_lower)

    # Enabled qualitative metrics survive.
    assert "MOS Score" in out
    assert "Valence" in out
    # Disabled qualitative metrics are dropped.
    for dropped in ("Arousal", "Prosody Score", "Emotion Category",
                    "Emotion Confidence", "Speaker Consistency"):
        assert dropped not in out
    # Non-qualitative keys always pass through.
    assert out["WER"] == 0.04
    assert out["CER"] == 0.01
    assert out["ASR Transcript"] == "the quick brown fox"
    assert "custom_metric_scores" in out


def test_filter_qualitative_metrics_keeps_everything_when_all_enabled():
    enabled_lower = {k.lower() for k in tts_comparison._QUALITATIVE_AUDIO_KEYS}
    metrics = _all_metrics_dict()
    out = tts_comparison._filter_qualitative_metrics(metrics, enabled_lower)
    assert out == metrics


def test_filter_qualitative_metrics_drops_all_qualitative_when_none_enabled():
    out = tts_comparison._filter_qualitative_metrics(_all_metrics_dict(), set())
    for key in tts_comparison._QUALITATIVE_AUDIO_KEYS:
        assert key not in out
    # Passthrough keys (WER/CER/ASR/custom) still survive.
    assert "WER" in out
    assert "ASR Transcript" in out
    assert "custom_metric_scores" in out


def test_filter_qualitative_metrics_preserves_unknown_keys():
    # Future / org-specific keys should never be dropped just because
    # they aren't in the qualitative set or the enabled set.
    metrics = {"MOS Score": 4.0, "Some Future Field": "x"}
    out = tts_comparison._filter_qualitative_metrics(metrics, set())
    assert "MOS Score" not in out
    assert out["Some Future Field"] == "x"


# ---------------------------------------------------------------------------
# _load_enabled_voice_metric_names
# ---------------------------------------------------------------------------

def _seed_org(db_session):
    org = Organization(id=uuid4(), name="VP Helpers Org")
    db_session.add(org)
    db_session.add(
        Workspace(
            id=uuid4(),
            organization_id=org.id,
            name="Default",
            slug="default",
            is_default=True,
        )
    )
    db_session.commit()
    return org


def _default_workspace_id(db_session, org_id):
    return (
        db_session.query(Workspace)
        .filter(Workspace.organization_id == org_id, Workspace.is_default.is_(True))
        .first()
        .id
    )


def _add_metric(db_session, org_id, *, name, enabled, surfaces):
    metric = Metric(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=_default_workspace_id(db_session, org_id),
        name=name,
        metric_type="rating",
        trigger="always",
        enabled=enabled,
        is_default=False,
        supported_surfaces=surfaces,
        enabled_surfaces=surfaces if enabled else [],
    )
    db_session.add(metric)
    db_session.commit()
    return metric


def test_load_enabled_voice_metric_names_returns_only_voice_playground_metrics(db_session):
    org = _seed_org(db_session)
    _add_metric(db_session, org.id, name="MOS Score", enabled=True,
                surfaces=["voice_playground"])
    _add_metric(db_session, org.id, name="Valence", enabled=True,
                surfaces=["voice_playground", "agent"])
    _add_metric(db_session, org.id, name="Professionalism", enabled=True,
                surfaces=["agent"])
    _add_metric(db_session, org.id, name="Disabled Voice Metric", enabled=False,
                surfaces=["voice_playground"])

    names = tts_comparison._load_enabled_voice_metric_names(db_session, org.id)

    # Only voice_playground-enabled metrics are returned, lowercased.
    assert names == {"mos score", "valence"}


def test_load_enabled_voice_metric_names_is_scoped_per_org(db_session):
    org_a = _seed_org(db_session)
    org_b = Organization(id=uuid4(), name="Other Org")
    db_session.add(org_b)
    db_session.add(
        Workspace(
            id=uuid4(),
            organization_id=org_b.id,
            name="Default",
            slug="default",
            is_default=True,
        )
    )
    db_session.commit()

    _add_metric(db_session, org_a.id, name="MOS Score", enabled=True,
                surfaces=["voice_playground"])
    _add_metric(db_session, org_b.id, name="Speaker Consistency", enabled=True,
                surfaces=["voice_playground"])

    names_a = tts_comparison._load_enabled_voice_metric_names(db_session, org_a.id)
    names_b = tts_comparison._load_enabled_voice_metric_names(db_session, org_b.id)

    assert names_a == {"mos score"}
    assert names_b == {"speaker consistency"}


def test_load_enabled_voice_metric_names_returns_empty_when_no_metrics(db_session):
    org = _seed_org(db_session)
    assert tts_comparison._load_enabled_voice_metric_names(db_session, org.id) == set()
