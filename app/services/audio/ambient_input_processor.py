"""Mix persona ambient bed into inbound telephony caller audio."""

from __future__ import annotations

from app.services.audio.ambient_mixer import AmbientBed

_ambient_input_processor_class = None


def get_ambient_input_processor_class():
    """Return AmbientInputProcessor (lazy efficientai import)."""
    global _ambient_input_processor_class
    if _ambient_input_processor_class is not None:
        return _ambient_input_processor_class

    from efficientai.frames.frames import AudioRawFrame
    from efficientai.processors.frame_processor import FrameProcessor

    class AmbientInputProcessor(FrameProcessor):
        """Overlay looping ambient bed on caller-side AudioRawFrame streams."""

        def __init__(self, bed: AmbientBed):
            super().__init__()
            self._bed = bed

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            # Mix in place so InputAudioRawFrame keeps Frame metadata (pts,
            # transport_source, etc.). Replacing with a bare AudioRawFrame mixin
            # drops those fields and the frame can reach the output transport.
            if isinstance(frame, AudioRawFrame) and frame.audio:
                frame.audio = self._bed.mix_speech(frame.audio)
            await self.push_frame(frame, direction)

    _ambient_input_processor_class = AmbientInputProcessor
    return _ambient_input_processor_class
