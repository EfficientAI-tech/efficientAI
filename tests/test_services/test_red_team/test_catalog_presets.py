"""Attack catalog integrity and intensity presets."""

import pytest

from app.services.red_team.catalog import (
    AUDIO_NATIVE,
    CONTENT_HARM,
    FAMILIES,
    HARM_CATEGORIES,
    OWASP_CATEGORIES,
    TECHNIQUES,
    TEXT_NATIVE,
    catalog_payload,
    techniques_for,
)
from app.services.red_team.presets import (
    MAX_FAMILY_QUOTA,
    PresetError,
    preview,
    resolve_config,
    root_allocation,
)


def test_every_technique_maps_to_exactly_one_category():
    for technique in TECHNIQUES:
        assert technique.family in FAMILIES
        assert bool(technique.owasp) != bool(technique.harm), technique.id
        if technique.owasp:
            assert technique.owasp in OWASP_CATEGORIES
        else:
            assert technique.family == CONTENT_HARM
            assert technique.harm in HARM_CATEGORIES
        assert technique.seed_openers, f"{technique.id} needs a fallback opener"


def test_technique_ids_unique_and_every_category_reachable():
    ids = [t.id for t in TECHNIQUES]
    assert len(ids) == len(set(ids))
    assert {t.owasp for t in TECHNIQUES if t.owasp} == set(OWASP_CATEGORIES)
    assert {t.harm for t in TECHNIQUES if t.harm} == set(HARM_CATEGORIES)


def test_channel_specific_families():
    assert techniques_for(TEXT_NATIVE, "voice") == []
    assert techniques_for(AUDIO_NATIVE, "chat") == []
    assert techniques_for(AUDIO_NATIVE, "voice")
    payload = catalog_payload()
    families = {f["id"]: f for f in payload["families"]}
    assert families[TEXT_NATIVE]["voice"] is False
    assert families[AUDIO_NATIVE]["chat"] is False


@pytest.mark.parametrize("intensity", ["quick", "standard", "thorough"])
def test_presets_drop_families_that_do_not_apply(intensity):
    chat = resolve_config(intensity, modality="chat")
    voice = resolve_config(intensity, modality="voice")
    assert chat["attack_quotas"][AUDIO_NATIVE] == 0
    assert voice["attack_quotas"][TEXT_NATIVE] == 0
    assert chat["max_attacks"] == sum(chat["attack_quotas"].values())


def test_presets_escalate_with_intensity():
    quick, standard, thorough = (resolve_config(i, modality="chat") for i in ("quick", "standard", "thorough"))
    assert quick["max_attacks"] < standard["max_attacks"] < thorough["max_attacks"]
    assert quick["max_levels"] < thorough["max_levels"]


def test_custom_quotas_are_clamped_and_validated():
    config = resolve_config("custom", modality="chat", attack_quotas={"prompt_injection": 99, "content_harm": -3})
    assert config["attack_quotas"]["prompt_injection"] == MAX_FAMILY_QUOTA
    assert config["attack_quotas"]["content_harm"] == 0
    assert config["max_attacks"] == MAX_FAMILY_QUOTA

    with pytest.raises(PresetError):
        resolve_config("custom", modality="chat", attack_quotas={"prompt_injection": 0})
    with pytest.raises(PresetError):
        resolve_config("custom", modality="chat", attack_quotas={"audio_native": 5})  # voice-only family
    with pytest.raises(PresetError):
        resolve_config("custom", modality="chat", attack_quotas={"made_up": 2})
    with pytest.raises(PresetError):
        resolve_config("custom", modality="chat")
    with pytest.raises(PresetError):
        resolve_config("extreme", modality="chat")


def test_root_allocation_keeps_budget_for_escalation():
    assert root_allocation(0, 3) == 0
    assert root_allocation(1, 3) == 1
    assert root_allocation(5, 3) == 3
    assert root_allocation(5, 1) == 5


def test_preview_counts_voice_minutes():
    config = resolve_config("quick", modality="voice")
    summary = preview(config, modality="voice")
    assert summary["max_total_conversations"] == config["max_attacks"] + config["recon_count"]
    assert summary["max_voice_minutes"] == summary["max_total_conversations"] * config["max_call_minutes"]
    assert preview(resolve_config("quick", modality="chat"), modality="chat")["max_voice_minutes"] is None
