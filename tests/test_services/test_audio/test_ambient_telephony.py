"""Tests for direction-aware telephony ambient placement."""

import pytest

from app.models.enums import BackgroundNoiseSourceEnum
from app.services.audio.ambient_telephony import resolve_ambient_for_telephony


class _Persona:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.mark.asyncio
async def test_inbound_human_caller_ambient_targets_input_bed_only(monkeypatch):
    from app.services.audio.ambient_mixer import AmbientBed, AmbientMixer

    bed = AmbientBed.__new__(AmbientBed)
    mixer = AmbientMixer(bed)

    async def fake_resolve(persona, sample_rate):
        assert sample_rate == 8000
        return mixer

    monkeypatch.setattr(
        "app.services.audio.ambient_telephony.resolve_ambient_mixer",
        fake_resolve,
    )

    persona = _Persona(
        background_noise_source=BackgroundNoiseSourceEnum.PLATFORM.value,
        background_noise_preset="cafe",
    )
    config = await resolve_ambient_for_telephony(
        persona,
        call_direction="inbound",
        input_sample_rate=8000,
        output_sample_rate=8000,
        persona_speaks_via_tts=False,
    )
    assert config.output_mixer is None
    assert config.input_bed is bed


@pytest.mark.asyncio
async def test_simulated_persona_ambient_targets_output_mixer(monkeypatch):
    from app.services.audio.ambient_mixer import AmbientBed, AmbientMixer

    bed = AmbientBed.__new__(AmbientBed)
    mixer = AmbientMixer(bed)

    async def fake_resolve(persona, sample_rate):
        assert sample_rate == 8000
        return mixer

    monkeypatch.setattr(
        "app.services.audio.ambient_telephony.resolve_ambient_mixer",
        fake_resolve,
    )

    persona = _Persona(
        background_noise_source=BackgroundNoiseSourceEnum.PLATFORM.value,
        background_noise_preset="cafe",
    )
    config = await resolve_ambient_for_telephony(
        persona,
        call_direction="inbound",
        input_sample_rate=8000,
        output_sample_rate=8000,
        persona_speaks_via_tts=True,
    )
    assert config.output_mixer is mixer
    assert config.input_bed is None


@pytest.mark.asyncio
async def test_outbound_simulation_ambient_targets_output_mixer(monkeypatch):
    from app.services.audio.ambient_mixer import AmbientBed, AmbientMixer

    bed = AmbientBed.__new__(AmbientBed)
    mixer = AmbientMixer(bed)

    async def fake_resolve(persona, sample_rate):
        assert sample_rate == 8000
        return mixer

    monkeypatch.setattr(
        "app.services.audio.ambient_telephony.resolve_ambient_mixer",
        fake_resolve,
    )

    persona = _Persona(
        background_noise_source=BackgroundNoiseSourceEnum.PLATFORM.value,
        background_noise_preset="cafe",
    )
    config = await resolve_ambient_for_telephony(
        persona,
        call_direction="outbound",
        input_sample_rate=8000,
        output_sample_rate=8000,
        persona_speaks_via_tts=True,
    )
    assert config.output_mixer is mixer
    assert config.input_bed is None


@pytest.mark.asyncio
async def test_outbound_without_simulation_role_has_no_ambient(monkeypatch):
    async def fake_resolve(persona, sample_rate):
        raise AssertionError("resolve_ambient_mixer should not be called")

    monkeypatch.setattr(
        "app.services.audio.ambient_telephony.resolve_ambient_mixer",
        fake_resolve,
    )

    persona = _Persona(
        background_noise_source=BackgroundNoiseSourceEnum.PLATFORM.value,
        background_noise_preset="cafe",
    )
    config = await resolve_ambient_for_telephony(
        persona,
        call_direction="outbound",
        input_sample_rate=8000,
        output_sample_rate=8000,
        persona_speaks_via_tts=False,
    )
    assert config.output_mixer is None
    assert config.input_bed is None
