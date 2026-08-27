import numpy as np
import pytest

from app.services.audio.ambient_catalog import normalize_ambient_preset
from app.services.audio.ambient_mixer import AmbientBed, AmbientMixer, clamp_ambient_volume, resample_mono_int16
from app.services.personas.persona_ambient_noise import validate_persona_ambient_fields
from app.models.enums import BackgroundNoiseSourceEnum


def test_clamp_ambient_volume():
    assert clamp_ambient_volume(None) == 0.22
    assert clamp_ambient_volume(0.01) == 0.05
    assert clamp_ambient_volume(0.9) == 0.6


def test_normalize_ambient_preset_aliases_street_to_traffic():
    assert normalize_ambient_preset("street") == "traffic"


def test_ambient_bed_loops_and_mixes():
    bed_pcm = np.array([1000, -1000, 500, -500], dtype=np.int16)
    bed = AmbientBed(bed_pcm, volume=0.5)
    speech = np.array([100, 200, 300, 400], dtype=np.int16).tobytes()
    mixed = bed.mix_speech(speech)
    mixed_np = np.frombuffer(mixed, dtype=np.int16)
    assert mixed_np[0] == 600
    assert mixed_np[1] == -300

    first = bed.chunk(4)
    second = bed.chunk(4)
    assert np.array_equal(first, second)


def test_ambient_bed_clone_is_independent():
    bed_pcm = np.array([1000, -1000, 500, -500], dtype=np.int16)
    original = AmbientBed(bed_pcm, volume=0.5)
    cloned = original.clone()

    speech = np.array([100, 200, 300, 400], dtype=np.int16).tobytes()
    cloned.mix_speech(speech)

    assert original._pos == 0
    assert cloned._pos == 4


def test_ambient_mixer_mixes_silence_frames():
    bed = AmbientBed(np.array([1000, -1000], dtype=np.int16), volume=0.5)
    mixer = AmbientMixer(bed)

    async def _run():
        await mixer.start(16000)
        mixed = await mixer.mix(b"")
        assert len(mixed) > 0

    import asyncio

    asyncio.run(_run())


def test_resample_mono_int16_changes_length():
    source = np.arange(160, dtype=np.int16)
    resampled = resample_mono_int16(source, 16000, 8000)
    assert len(resampled) == 80


def test_validate_persona_ambient_none_clears_fields():
    result = validate_persona_ambient_fields(
        source="none",
        preset=None,
        volume=0.3,
        s3_key="organizations/x/personas/y/ambient.wav",
    )
    assert result["background_noise_source"] == BackgroundNoiseSourceEnum.NONE.value
    assert result["background_noise_s3_key"] is None


def test_validate_persona_ambient_platform_requires_preset():
    with pytest.raises(ValueError, match="background_noise_preset"):
        validate_persona_ambient_fields(
            source="platform",
            preset=None,
            volume=0.2,
            s3_key=None,
        )
