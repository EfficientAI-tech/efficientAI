"""
ElevenLabs Voice Provider Implementation
Handles integration with ElevenLabs Conversational AI agents
"""
from typing import Dict, Any, Optional
import requests
from loguru import logger

from app.services.voice_providers.base import BaseVoiceProvider

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"


class ElevenLabsVoiceProvider(BaseVoiceProvider):
    """ElevenLabs voice provider implementation for Conversational AI."""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.api_url = ELEVENLABS_API_URL

    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a web call session with an ElevenLabs Conversational AI agent.

        Requests a signed URL from the ElevenLabs API that the frontend SDK
        can use to establish a WebSocket connection with the agent.

        Args:
            agent_id: ElevenLabs agent ID
            metadata: Optional metadata (unused by ElevenLabs, kept for interface compat)

        Returns:
            Dictionary containing signed_url and agent_id for the frontend SDK.
        """
        try:
            url = f"{self.api_url}/convai/conversation/get-signed-url"
            headers = {
                "xi-api-key": self.api_key,
            }
            params = {"agent_id": agent_id}

            logger.info(f"[ElevenLabsProvider] Requesting signed URL for agent_id={agent_id}")

            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 200:
                data = response.json()
                signed_url = data.get("signed_url")

                if not signed_url:
                    logger.error(f"[ElevenLabsProvider] Response missing 'signed_url': {data}")
                    raise ValueError("ElevenLabs API returned success but no signed_url")

                logger.info(f"[ElevenLabsProvider] Signed URL obtained for agent {agent_id}")

                return {
                    "signed_url": signed_url,
                    "agent_id": agent_id,
                    "call_type": "web_call",
                    "call_id": None,
                }
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", {}).get("message", "") or str(error_data)
                except Exception:
                    error_msg = response.text[:500]

                logger.error(
                    f"[ElevenLabsProvider] Failed to get signed URL "
                    f"(status {response.status_code}): {error_msg}"
                )
                raise ValueError(f"ElevenLabs API error ({response.status_code}): {error_msg}")

        except requests.exceptions.RequestException as e:
            logger.error(f"[ElevenLabsProvider] Request error: {e}")
            raise ValueError(f"Failed to create ElevenLabs web call: {str(e)}")

    def create_agent(self, response_engine: Dict[str, Any], voice_id: str, **kwargs) -> Dict[str, Any]:
        """Not implemented - agents are created via the ElevenLabs dashboard."""
        raise NotImplementedError("ElevenLabs agents are managed through the ElevenLabs dashboard")

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """Get agent details from ElevenLabs."""
        try:
            url = f"{self.api_url}/convai/agents/{agent_id}"
            headers = {"xi-api-key": self.api_key}

            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise ValueError(f"Failed to get ElevenLabs agent: {str(e)}")

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        """
        Retrieve conversation details from ElevenLabs.

        Calls GET /v1/convai/conversations/{conversation_id}

        ElevenLabs status values: initiated, in-progress, processing, done, failed
        Response includes transcript (list), metadata (start_time_unix_secs,
        call_duration_secs), analysis, and audio flags.

        Args:
            call_id: ElevenLabs conversation ID
        """
        try:
            url = f"{self.api_url}/convai/conversations/{call_id}"
            headers = {"xi-api-key": self.api_key}

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            el_status = data.get("status", "unknown")
            logger.info(
                f"[ElevenLabsProvider] Retrieved conversation {call_id}, "
                f"status: {el_status}"
            )

            # Map ElevenLabs status to the normalised values the poller recognises
            STATUS_MAP = {
                "done": "ended",
                "failed": "failed",
                "in-progress": "in-progress",
                "processing": "processing",
                "initiated": "initiated",
            }
            normalised_status = STATUS_MAP.get(el_status, el_status)

            # --- Transcript --------------------------------------------------
            transcript_text = ""
            speaker_segments = []
            transcript_entries = data.get("transcript", [])
            if isinstance(transcript_entries, list):
                for entry in transcript_entries:
                    role = entry.get("role", "unknown")
                    message = entry.get("message", "")
                    if not message:
                        continue
                    speaker = "Agent" if role in ("agent", "ai") else "User"
                    time_secs = entry.get("time_in_call_secs", 0)
                    speaker_segments.append({
                        "speaker": speaker,
                        "text": message,
                        "start": time_secs,
                        "end": time_secs,
                    })
                transcript_text = "\n".join(
                    f"{seg['speaker']}: {seg['text']}" for seg in speaker_segments
                )

            # --- Metadata / timing -------------------------------------------
            metadata = data.get("metadata") or {}
            duration_seconds = metadata.get("call_duration_secs", 0)
            start_time_unix = metadata.get("start_time_unix_secs")

            start_timestamp = None
            end_timestamp = None
            if start_time_unix:
                from datetime import datetime, timezone
                start_dt = datetime.fromtimestamp(start_time_unix, tz=timezone.utc)
                start_timestamp = start_dt.isoformat()
                if duration_seconds and normalised_status == "ended":
                    from datetime import timedelta
                    end_dt = start_dt + timedelta(seconds=duration_seconds)
                    end_timestamp = end_dt.isoformat()

            # --- Analysis (if returned by ElevenLabs) ------------------------
            el_analysis = data.get("analysis") or {}
            analysis = {
                "summary": el_analysis.get("transcript_summary", ""),
                "evaluation": el_analysis.get("evaluation_criteria_results"),
                "data_collection": el_analysis.get("data_collection_results"),
                "latency_stats": {},
                "interruption_count": 0,
            }

            # --- Audio URLs --------------------------------------------------
            recording_urls = {}
            if data.get("has_audio"):
                recording_urls["conversation_audio"] = (
                    f"{self.api_url}/convai/conversations/{call_id}/audio"
                )

            return {
                "call_id": data.get("conversation_id") or call_id,
                "call_status": normalised_status,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "duration_seconds": duration_seconds,
                "transcript": transcript_text,
                "transcript_object": speaker_segments,
                "analysis": analysis,
                "cost": metadata.get("cost"),
                "recording_urls": recording_urls,
                "agent_id": data.get("agent_id"),
                "raw_data": data,
            }
        except Exception as e:
            logger.error(f"[ElevenLabsProvider] Error getting conversation: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve ElevenLabs conversation: {str(e)}")

    def update_agent_prompt(self, agent_id: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Update an ElevenLabs Conversational AI agent's system prompt.

        Args:
            agent_id: ElevenLabs agent ID
            system_prompt: New system prompt text

        Returns:
            Updated agent data from ElevenLabs
        """
        try:
            url = f"{self.api_url}/convai/agents/{agent_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "conversation_config": {
                    "agent": {
                        "prompt": {
                            "prompt": system_prompt,
                        },
                    },
                },
            }
            logger.info(f"[ElevenLabsProvider] Updating agent prompt: PATCH {url}")
            response = requests.patch(url, headers=headers, json=payload, timeout=30)

            if not response.ok:
                try:
                    error_body = response.json()
                except Exception:
                    error_body = response.text[:500]
                raise ValueError(
                    f"ElevenLabs API error ({response.status_code}): {error_body}"
                )

            data = response.json()
            logger.info(f"[ElevenLabsProvider] Agent {agent_id} prompt updated")
            return data
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to update ElevenLabs agent prompt: {str(e)}")

    def test_connection(self) -> bool:
        """Test the ElevenLabs API connection."""
        try:
            url = f"{self.api_url}/user"
            headers = {"xi-api-key": self.api_key}

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                raise ValueError("Invalid API key")
            else:
                raise ValueError(f"API error (status {response.status_code})")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"ElevenLabs connection test failed: {str(e)}")
