"""Studio User WER / User CER must score the same text as an import eval."""

from app.services.metric_studio.source_resolver import ResolvedCallSample
from app.workers.tasks.evaluate_studio_run_item import computed_metric_source_from_sample


def test_studio_computed_source_keeps_native_turns_and_aliases():
    segments = [
        {"speaker": "Member", "text": "romanised", "text_native": "हिंदी"},
        {"speaker": "Agent", "text": "ok", "text_native": "ठीक"},
    ]
    sample = ResolvedCallSample(
        source_kind="call_import_row",
        source_ref="row-1",
        label="call",
        transcript="User: hello",
        diarised_transcript="Member: romanised\nAgent: ok",
        audio_s3_key=None,
        call_data=None,
        agent_id=None,
        diarised_segments=segments,
        diarised_speaker_swap=True,
        diarised_native_transcript="full native call",
        speaker_aliases={"user": ["Member"], "agent": ["IVR"]},
    )

    source = computed_metric_source_from_sample(sample)

    assert source.diarised_segments == segments
    assert source.diarised_speaker_swap is True
    assert source.diarised_native_transcript == "full native call"
    assert sample.speaker_aliases == {"user": ["Member"], "agent": ["IVR"]}
    assert source.transcript == "User: hello"
    assert source.diarised_transcript == "Member: romanised\nAgent: ok"
