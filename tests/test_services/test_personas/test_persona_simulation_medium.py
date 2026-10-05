from app.models.enums import SimulationMediumEnum
from app.services.personas.persona_simulation_medium import (
    infer_simulation_medium_from_fields,
    persona_simulation_medium,
)


class _Persona:
    def __init__(self, **kwargs):
        self.simulation_medium = kwargs.get("simulation_medium", "voice")
        self.tts_provider = kwargs.get("tts_provider")


def test_infer_text_without_tts():
    assert (
        infer_simulation_medium_from_fields(explicit=None, tts_provider=None)
        == SimulationMediumEnum.TEXT.value
    )


def test_infer_voice_with_tts():
    assert (
        infer_simulation_medium_from_fields(explicit=None, tts_provider="elevenlabs")
        == SimulationMediumEnum.VOICE.value
    )


def test_explicit_text_wins():
    assert (
        infer_simulation_medium_from_fields(explicit="text", tts_provider="elevenlabs")
        == SimulationMediumEnum.TEXT.value
    )


def test_persona_simulation_medium_on_model():
    p = _Persona(simulation_medium="text")
    assert persona_simulation_medium(p) == "text"
