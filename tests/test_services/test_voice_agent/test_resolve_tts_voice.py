"""Tests for resolve_effective_tts_voice_id."""

from types import SimpleNamespace


def test_persona_voice_wins_over_bundle():
    from app.services.voice_agent.resolve_tts_voice import resolve_effective_tts_voice_id

    persona = SimpleNamespace(tts_voice_id="persona-voice")
    bundle = SimpleNamespace(tts_voice="bundle-voice")

    assert (
        resolve_effective_tts_voice_id(
            persona=persona,
            voice_bundle=bundle,
            default_voice="default-voice",
        )
        == "persona-voice"
    )


def test_falls_back_to_bundle_when_persona_voice_missing():
    from app.services.voice_agent.resolve_tts_voice import resolve_effective_tts_voice_id

    persona = SimpleNamespace(tts_voice_id=None)
    bundle = SimpleNamespace(tts_voice="bundle-voice")

    assert (
        resolve_effective_tts_voice_id(
            persona=persona,
            voice_bundle=bundle,
            default_voice="default-voice",
        )
        == "bundle-voice"
    )


def test_falls_back_to_default_when_both_missing():
    from app.services.voice_agent.resolve_tts_voice import resolve_effective_tts_voice_id

    persona = SimpleNamespace(tts_voice_id=None)
    bundle = SimpleNamespace(tts_voice=None)

    assert (
        resolve_effective_tts_voice_id(
            persona=persona,
            voice_bundle=bundle,
            default_voice="default-voice",
        )
        == "default-voice"
    )


def test_no_persona_uses_bundle():
    from app.services.voice_agent.resolve_tts_voice import resolve_effective_tts_voice_id

    bundle = SimpleNamespace(tts_voice="bundle-voice")

    assert (
        resolve_effective_tts_voice_id(
            persona=None,
            voice_bundle=bundle,
            default_voice="default-voice",
        )
        == "bundle-voice"
    )
