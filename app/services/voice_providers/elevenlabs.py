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

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute an HTTP request with a no-proxy retry fallback.

        Some local environments inject HTTP(S)_PROXY values that block
        ElevenLabs with tunnel 403 responses. We first try the default
        request path, then retry once with ``trust_env=False`` to bypass
        environment proxy settings.
        """
        try:
            return requests.request(method, url, **kwargs)
        except requests.exceptions.ProxyError as proxy_error:
            logger.warning(
                "[ElevenLabsProvider] Proxy error for {} {}: {}. "
                "Retrying without environment proxies.",
                method,
                url,
                proxy_error,
            )
            with requests.Session() as session:
                session.trust_env = False
                retry_kwargs = dict(kwargs)
                # Ensure explicit per-request proxies cannot force the same bad tunnel.
                retry_kwargs.pop("proxies", None)
                return session.request(
                    method,
                    url,
                    proxies={"http": None, "https": None},
                    **retry_kwargs,
                )

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

            response = self._request("GET", url, headers=headers, params=params, timeout=30)

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

            response = self._request("GET", url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise ValueError(f"Failed to get ElevenLabs agent: {str(e)}")

    def list_agents(
        self,
        *,
        page_size: int = 30,
        search: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List ElevenLabs Conversational AI agents."""
        try:
            url = f"{self.api_url}/convai/agents"
            headers = {"xi-api-key": self.api_key}
            params: Dict[str, Any] = {"page_size": max(1, min(page_size, 100))}
            if search:
                params["search"] = search
            if cursor:
                params["cursor"] = cursor

            response = self._request("GET", url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                payload = {"agents": payload}
            if not isinstance(payload, dict):
                payload = {"agents": []}

            # ElevenLabs response shape has changed across API versions.
            # Support common containers so the UI doesn't silently render empty.
            items = (
                payload.get("agents")
                or payload.get("items")
                or payload.get("data")
                or payload.get("conversational_ai_agents")
                or []
            )
            if isinstance(items, dict):
                items = (
                    items.get("agents")
                    or items.get("items")
                    or items.get("data")
                    or []
                )
            normalized_agents = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Some variants nest core fields under `agent`.
                agent_obj = item.get("agent") if isinstance(item.get("agent"), dict) else item
                agent_id = (
                    agent_obj.get("agent_id")
                    or agent_obj.get("id")
                    or agent_obj.get("agentId")
                )
                if not agent_id:
                    continue
                name = (
                    agent_obj.get("name")
                    or agent_obj.get("agent_name")
                    or item.get("name")
                    or str(agent_id)
                )
                created_at = (
                    agent_obj.get("created_at")
                    or agent_obj.get("created_at_unix_secs")
                    or agent_obj.get("created_at_unix_ms")
                )
                normalized_agents.append(
                    {
                        "id": str(agent_id),
                        "name": str(name),
                        "archived": bool(
                            agent_obj.get("archived", False)
                            or agent_obj.get("is_archived", False)
                        ),
                        "created_at": created_at,
                        "metadata": item,
                    }
                )

            return {
                "agents": normalized_agents,
                "has_more": bool(payload.get("has_more", False)),
                "next_cursor": payload.get("next_cursor") or payload.get("cursor"),
            }
        except Exception as e:
            raise ValueError(f"Failed to list ElevenLabs agents: {str(e)}")

    def retrieve_conversation_trace(self, conversation_id: str) -> Dict[str, Any]:
        """Fetch conversation details with OpenTelemetry payload."""
        try:
            url = f"{self.api_url}/convai/conversations/{conversation_id}"
            headers = {"xi-api-key": self.api_key}
            response = self._request(
                "GET",
                url,
                headers=headers,
                params={"format": "opentelemetry"},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise ValueError(f"Failed to retrieve ElevenLabs conversation trace: {str(e)}")

    def retrieve_provider_trace(self, call_id: str, **kwargs) -> Dict[str, Any]:
        """Provider-agnostic alias used by adapter flows."""
        del kwargs
        return self.retrieve_conversation_trace(call_id)

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

            response = self._request("GET", url, headers=headers, timeout=30)
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
                "cost": metadata.get("cost"),
            }

            # --- Audio URLs --------------------------------------------------
            recording_urls = {}
            if data.get("has_audio"):
                recording_urls["conversation_audio"] = (
                    f"{self.api_url}/convai/conversations/{call_id}/audio"
                )
            recording_url = recording_urls.get("conversation_audio")

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
                "ended_reason": metadata.get("termination_reason"),
                "recording_url": recording_url,
                "recording_urls": recording_urls,
                "agent_id": data.get("agent_id"),
                "raw_data": data,
            }
        except Exception as e:
            logger.error(f"[ElevenLabsProvider] Error getting conversation: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve ElevenLabs conversation: {str(e)}")

    def extract_agent_prompt(self, agent_id: str) -> Optional[str]:
        """Extract the system prompt from an ElevenLabs Conversational AI agent."""
        try:
            data = self.get_agent(agent_id)
            conv_config = data.get("conversation_config") or {}
            agent_config = conv_config.get("agent") or {}
            prompt_config = agent_config.get("prompt") or {}
            prompt = prompt_config.get("prompt")
            if prompt:
                prompt = self._strip_code_fences(prompt)
            return prompt
        except Exception as e:
            logger.warning(f"[ElevenLabsProvider] Failed to extract agent prompt: {e}")
            return None

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove wrapping triple-backtick code fences that some providers add.

        Handles both complete fences (opening + closing) and prompts that
        only start with an opening fence (e.g. truncated or provider quirk).
        """
        import re
        trimmed = text.strip()
        # Try complete fence first (opening + closing)
        m = re.match(r'^```[\w]*\n?([\s\S]*?)```\s*$', trimmed)
        if m:
            return m.group(1).strip()
        # Opening fence only (no closing)
        m = re.match(r'^```[\w]*\n?([\s\S]*)$', trimmed)
        if m:
            return m.group(1).strip()
        return trimmed

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
            response = self._request("PATCH", url, headers=headers, json=payload, timeout=30)

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

            response = self._request("GET", url, headers=headers, timeout=10)
            if response.status_code == 200:
                return True
            elif response.status_code == 401:
                raise ValueError("Invalid API key")
            else:
                raise ValueError(f"API error (status {response.status_code})")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"ElevenLabs connection test failed: {str(e)}")
