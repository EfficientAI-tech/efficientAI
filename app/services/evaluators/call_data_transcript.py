"""Extract transcript text from voice-provider call payloads."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def extract_transcript_from_call_data(
    call_data: Dict[str, Any],
    provider_platform: str,
) -> Tuple[str, List[dict]]:
    """Return plain-text transcript and speaker segments from provider call_data."""
    transcript_text = ""
    speaker_segments: List[dict] = []

    if not call_data:
        return transcript_text, speaker_segments

    provider_platform_lower = provider_platform.lower() if provider_platform else ""

    if provider_platform_lower == "vapi":
        transcript_text = call_data.get("transcript", "") or ""
        transcript_object = call_data.get("transcript_object", [])
        if not transcript_object:
            artifact = call_data.get("artifact", {}) if isinstance(call_data, dict) else {}
            messages = call_data.get("messages", []) or artifact.get("messages", [])
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("message", "") or msg.get("content", "")
                if not content or role == "system":
                    continue
                if role in ("bot", "assistant"):
                    normalized_role = "agent"
                elif role == "user":
                    normalized_role = "user"
                else:
                    continue
                speaker_segments.append(
                    {
                        "speaker": "Agent" if normalized_role == "agent" else "User",
                        "text": content,
                        "start": msg.get("secondsFromStart", 0),
                        "end": msg.get("secondsFromStart", 0)
                        + (msg.get("duration", 0) / 1000),
                    }
                )
        else:
            for entry in transcript_object:
                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                if not content:
                    continue
                speaker_segments.append(
                    {
                        "speaker": "Agent" if role == "agent" else "User",
                        "text": content,
                        "start": entry.get("seconds_from_start", 0),
                        "end": entry.get("seconds_from_start", 0)
                        + (entry.get("duration_ms", 0) / 1000),
                    }
                )
        if not transcript_text and speaker_segments:
            transcript_text = "\n".join(
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            )

    elif provider_platform_lower == "elevenlabs":
        raw_transcript = call_data.get("transcript")
        transcript_obj = call_data.get("transcript_object", [])
        if isinstance(raw_transcript, str) and raw_transcript:
            transcript_text = raw_transcript
            if isinstance(transcript_obj, list):
                for seg in transcript_obj:
                    speaker_segments.append(
                        {
                            "speaker": seg.get("speaker", "Unknown"),
                            "text": seg.get("text", ""),
                            "start": seg.get("start", 0),
                            "end": seg.get("end", 0),
                        }
                    )
        elif isinstance(raw_transcript, list):
            for entry in raw_transcript:
                role = entry.get("role", "unknown")
                content = entry.get("message", "") or entry.get("text", "")
                if not content:
                    continue
                speaker = "Agent" if role in ("agent", "assistant", "ai") else "User"
                speaker_segments.append(
                    {
                        "speaker": speaker,
                        "text": content,
                        "start": entry.get("time_in_call_secs", 0) or entry.get("start", 0),
                        "end": entry.get("time_in_call_secs", 0) or entry.get("end", 0),
                    }
                )
            transcript_text = "\n".join(
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            )

    elif provider_platform_lower == "smallest":
        transcript_raw = call_data.get("transcript")
        transcript_object = call_data.get("transcript_object", [])
        if isinstance(transcript_object, list) and transcript_object:
            for entry in transcript_object:
                if not isinstance(entry, dict):
                    continue
                text = entry.get("text", "")
                if not text:
                    continue
                speaker_segments.append(
                    {
                        "speaker": entry.get("speaker", "Unknown"),
                        "text": text,
                        "start": entry.get("start", 0),
                        "end": entry.get("end", entry.get("start", 0)),
                    }
                )
            if not transcript_text:
                transcript_text = "\n".join(
                    f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
                )
        elif isinstance(transcript_raw, list):
            for entry in transcript_raw:
                if not isinstance(entry, dict):
                    continue
                role = str(entry.get("speaker") or entry.get("role") or "").lower()
                speaker = "Agent" if role in ("agent", "assistant", "ai", "bot") else "User"
                text = entry.get("text", "") or entry.get("message", "") or entry.get("content", "")
                if not text:
                    continue
                ts = entry.get("timeInCallSecs", 0) or entry.get("start", 0) or entry.get("timestamp", 0)
                speaker_segments.append(
                    {
                        "speaker": speaker,
                        "text": text,
                        "start": ts,
                        "end": entry.get("end", ts),
                    }
                )
            transcript_text = "\n".join(
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            )
        elif isinstance(transcript_raw, str):
            transcript_text = transcript_raw

    elif provider_platform_lower == "retell":
        transcript_raw = call_data.get("transcript", "")
        if isinstance(transcript_raw, str):
            transcript_text = transcript_raw
            lines = transcript_raw.split("\n") if transcript_raw else []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Agent:") or line.startswith("agent:"):
                    speaker_segments.append(
                        {
                            "speaker": "Agent",
                            "text": line.split(":", 1)[1].strip() if ":" in line else line,
                            "start": 0,
                            "end": 0,
                        }
                    )
                elif line.startswith("User:") or line.startswith("user:"):
                    speaker_segments.append(
                        {
                            "speaker": "User",
                            "text": line.split(":", 1)[1].strip() if ":" in line else line,
                            "start": 0,
                            "end": 0,
                        }
                    )
        elif isinstance(transcript_raw, list):
            for item in transcript_raw:
                if not isinstance(item, dict):
                    continue
                role = item.get("role", "")
                content = item.get("content", "") or item.get("text", "")
                if not content:
                    continue
                speaker = "Agent" if role in ["agent", "assistant", "bot"] else "User"
                speaker_segments.append(
                    {
                        "speaker": speaker,
                        "text": content,
                        "start": item.get("start_time", 0) or item.get("timestamp", 0),
                        "end": item.get("end_time", 0),
                    }
                )
            transcript_text = "\n".join(
                f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
            )

    return transcript_text, speaker_segments
