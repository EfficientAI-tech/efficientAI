"""Direction-aware ambient placement for live telephony pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.audio.ambient_catalog import persona_has_active_ambient, resolve_ambient_mixer
from app.services.audio.ambient_mixer import AmbientBed, AmbientMixer


@dataclass(frozen=True)
class TelephonyAmbientConfig:
    """Resolved ambient wiring for a telephony call leg."""

    output_mixer: Optional[AmbientMixer] = None
    input_bed: Optional[AmbientBed] = None


async def resolve_ambient_for_telephony(
    persona: Any,
    *,
    call_direction: str,
    input_sample_rate: int,
    output_sample_rate: int,
    persona_speaks_via_tts: bool = False,
) -> TelephonyAmbientConfig:
    """
    Place persona ambient on the correct telephony leg.

    Use ``persona_speaks_via_tts`` (simulation role), not session direction alone:

    - **Simulated customer/caller** (persona speech is TTS on this leg): mix onto
      output toward the remote party — the agent hears caller speech + continuous
      ambient live, same as web-bridge ``AmbientMicPump``.
    - **Live PSTN caller → production agent** (inbound answer, human on the phone):
      mix onto input only (STT + recording). Never attach ``audio_out_mixer`` here;
      its idle loop streams ambient on the agent→caller downlink and breaks the call.
    """
    if persona is None or not persona_has_active_ambient(persona):
        return TelephonyAmbientConfig()

    if persona_speaks_via_tts:
        mixer = await resolve_ambient_mixer(persona, output_sample_rate)
        if mixer is None:
            return TelephonyAmbientConfig()
        return TelephonyAmbientConfig(output_mixer=mixer)

    direction = (call_direction or "outbound").strip().lower()
    if direction == "inbound":
        input_mixer = await resolve_ambient_mixer(persona, input_sample_rate)
        if input_mixer is None:
            return TelephonyAmbientConfig()
        return TelephonyAmbientConfig(input_bed=input_mixer.bed)

    return TelephonyAmbientConfig()
