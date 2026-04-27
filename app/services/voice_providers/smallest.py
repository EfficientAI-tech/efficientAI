"""
Smallest Voice Provider Implementation
Handles integration with Smallest Atoms agents
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from loguru import logger

from app.services.voice_providers.base import BaseVoiceProvider

SMALLEST_ATOMS_API_URL = "https://api.smallest.ai/atoms/v1"


class SmallestVoiceProvider(BaseVoiceProvider):
    """Smallest Atoms voice provider implementation."""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.api_url = SMALLEST_ATOMS_API_URL

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            error_json = response.json()
            if isinstance(error_json, dict):
                return (
                    str(error_json.get("message"))
                    or str(error_json.get("detail"))
                    or str(error_json.get("error"))
                    or str(error_json)
                )
            return str(error_json)
        except Exception:
            return response.text[:500] if response.text else "Unknown error"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        url = f"{self.api_url}{path}"
        request_kwargs = {
            "method": method,
            "url": url,
            "headers": self._headers(),
            "params": params,
            "json": json,
            "timeout": timeout,
        }
        try:
            response = requests.request(**request_kwargs)
        except requests.exceptions.ProxyError as proxy_exc:
            # Some local dev setups export HTTPS_PROXY that blocks Smallest.
            # Retry once with env proxies disabled before surfacing an error.
            logger.warning(
                "Smallest request hit proxy error; retrying direct connection: {}",
                proxy_exc,
            )
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.request(**request_kwargs)
            except requests.exceptions.RequestException as exc:
                raise ValueError(
                    "Smallest API request failed after direct retry: "
                    f"{exc}. If needed, set NO_PROXY=api.smallest.ai"
                ) from exc
        except requests.exceptions.RequestException as exc:
            raise ValueError(f"Smallest API request failed: {exc}") from exc

        if not response.ok:
            error_message = self._extract_error_message(response)
            raise ValueError(
                f"Smallest API error ({response.status_code}) on {method} {path}: {error_message}"
            )

        if not response.content:
            return {}

        payload = response.json()
        if isinstance(payload, dict):
            return payload.get("data", payload)
        return {"data": payload}

    @staticmethod
    def _to_seconds(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_speaker(raw_role: Any) -> str:
        role = str(raw_role or "").strip().lower()
        if role in {"assistant", "agent", "bot", "ai"}:
            return "Agent"
        if role in {"user", "customer", "caller", "human"}:
            return "User"
        return "Unknown"

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _get_conversation(self, call_id: str) -> Dict[str, Any]:
        try:
            return self._request("GET", f"/conversation/{call_id}")
        except ValueError as direct_error:
            try:
                search_payload = {"conversationIds": [call_id]}
                search_data = self._request(
                    "POST",
                    "/conversation/search",
                    json=search_payload,
                )
                if isinstance(search_data, list) and search_data:
                    return search_data[0]
                if isinstance(search_data, dict):
                    conversations = (
                        search_data.get("conversations")
                        or search_data.get("items")
                        or search_data.get("results")
                        or []
                    )
                    if isinstance(conversations, list) and conversations:
                        return conversations[0]
            except Exception:
                pass
            raise direct_error

    def get_user_details(self) -> Dict[str, Any]:
        """Fetch Smallest account details from GET /atoms/v1/user."""
        return self._request("GET", "/user", timeout=15.0)

    def create_web_call(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        phone_number = kwargs.get("phone_number") or kwargs.get("to_number") or kwargs.get("to")
        if not phone_number:
            payload: Dict[str, Any] = {
                "agentId": agent_id,
            }
            if metadata:
                payload["metadata"] = metadata
            if kwargs.get("variables"):
                payload["variables"] = kwargs["variables"]

            data = self._request("POST", "/conversation/webcall", json=payload, timeout=45.0)

            call_id = data.get("callId") or data.get("conversationId") or data.get("id")
            access_token = data.get("token") or data.get("accessToken")
            host = data.get("host")
            room_name = data.get("roomName")
            conversation_id = data.get("conversationId")

            if not call_id:
                raise ValueError("Smallest webcall response missing call ID")
            if not access_token or not host:
                raise ValueError("Smallest webcall response missing token or host")

            return {
                "call_id": call_id,
                "call_type": "webcall",
                "agent_id": agent_id,
                "access_token": access_token,
                "host": host,
                "room_name": room_name,
                "conversation_id": conversation_id,
                "raw_response": data,
            }

        payload: Dict[str, Any] = {
            "agentId": agent_id,
            "phoneNumber": phone_number,
        }
        if metadata:
            payload["variables"] = metadata
        if kwargs.get("variables"):
            payload["variables"] = kwargs["variables"]
        if kwargs.get("from_product_id"):
            payload["fromProductId"] = kwargs["from_product_id"]

        data = self._request("POST", "/conversation/outbound", json=payload, timeout=45.0)
        conversation_id = data.get("conversationId") or data.get("id")
        if not conversation_id:
            raise ValueError("Smallest outbound call response missing conversation ID")

        return {
            "call_id": conversation_id,
            "call_type": "outbound",
            "agent_id": agent_id,
            "phone_number": phone_number,
            "raw_response": data,
        }

    def create_agent(self, response_engine: Dict[str, Any], voice_id: str, **kwargs) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "name": kwargs.get("name") or response_engine.get("name") or "EfficientAI Agent",
        }

        global_prompt = (
            kwargs.get("system_prompt")
            or kwargs.get("global_prompt")
            or response_engine.get("system_prompt")
            or response_engine.get("prompt")
        )
        if global_prompt:
            payload["globalPrompt"] = global_prompt

        description = kwargs.get("description")
        if description:
            payload["description"] = description

        if voice_id:
            payload["synthesizer"] = {
                "voiceConfig": {
                    "voiceId": voice_id,
                    "model": kwargs.get("tts_model", "waves_lightning_large"),
                }
            }

        data = self._request("POST", "/agent", json=payload, timeout=45.0)
        provider_agent_id = data.get("agentId") or data.get("id")
        if not provider_agent_id:
            raise ValueError("Smallest agent creation response missing agent ID")

        return {
            "agent_id": provider_agent_id,
            "raw_response": data,
        }

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/agent/{agent_id}", timeout=30.0)

    def get_agent_workflow(self, agent_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/agent/{agent_id}/workflow", timeout=30.0)

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        data = self._get_conversation(call_id)

        status = str(data.get("status") or "unknown").lower()
        status_map = {
            "completed": "ended",
            "finished": "ended",
            "cancelled": "failed",
            "canceled": "failed",
        }
        normalized_status = status_map.get(status, status)

        transcript_entries = data.get("transcript") or data.get("messages") or []
        transcript_segments: List[Dict[str, Any]] = []
        if isinstance(transcript_entries, list):
            for entry in transcript_entries:
                if not isinstance(entry, dict):
                    continue
                text = (
                    entry.get("text")
                    or entry.get("message")
                    or entry.get("content")
                    or ""
                )
                if not text:
                    continue
                start = self._to_seconds(
                    entry.get("start")
                    or entry.get("startTime")
                    or entry.get("time")
                    or entry.get("timestamp")
                    or entry.get("timeInCallSecs")
                )
                end = self._to_seconds(entry.get("end") or entry.get("endTime"))
                if end is None:
                    end = start
                transcript_segments.append(
                    {
                        "speaker": self._normalize_speaker(
                            entry.get("speaker") or entry.get("role") or entry.get("participant")
                        ),
                        "text": text,
                        "start": start or 0,
                        "end": end or start or 0,
                    }
                )

        transcript_text = "\n".join(
            f"{segment['speaker']}: {segment['text']}"
            for segment in transcript_segments
        )

        duration_seconds = self._to_seconds(
            data.get("duration")
            or data.get("durationSeconds")
            or data.get("callDuration")
        ) or 0

        start_timestamp = (
            data.get("startedAt")
            or data.get("createdAt")
            or data.get("startTime")
        )
        end_timestamp = data.get("endedAt") or data.get("endTime") or data.get("completedAt")

        if not end_timestamp and start_timestamp and duration_seconds > 0 and normalized_status == "ended":
            start_dt = self._parse_timestamp(start_timestamp)
            if start_dt:
                end_timestamp = (start_dt + timedelta(seconds=duration_seconds)).isoformat()

        recording_url = (
            data.get("recordingUrl")
            or data.get("audioUrl")
            or data.get("recording_url")
        )
        if not recording_url:
            artifacts = data.get("artifacts") or {}
            if isinstance(artifacts, dict):
                recording_url = artifacts.get("recordingUrl") or artifacts.get("audioUrl")

        return {
            "call_id": data.get("conversationId") or data.get("id") or call_id,
            "call_status": normalized_status,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "duration_seconds": duration_seconds,
            "transcript": transcript_text,
            "transcript_object": transcript_segments,
            "recording_url": recording_url,
            "analysis": {
                "summary": data.get("summary"),
                "latency_stats": data.get("latencyStats") or {},
                "cost": data.get("cost"),
            },
            "agent_id": data.get("agentId"),
            "raw_data": data,
        }

    def extract_agent_prompt(self, agent_id: str) -> Optional[str]:
        def _extract_from_paths(payload: Dict[str, Any], paths: List[tuple[str, ...]]) -> Optional[str]:
            for path in paths:
                node: Any = payload
                for key in path:
                    if not isinstance(node, dict):
                        node = None
                        break
                    node = node.get(key)
                if isinstance(node, str) and node.strip():
                    return node
            return None

        def _extract_from_workflow(workflow_payload: Dict[str, Any]) -> Optional[str]:
            if not isinstance(workflow_payload, dict):
                return None

            # single_prompt workflow shape:
            # {"type": "single_prompt", "data": {"prompt": "..."}}
            prompt = _extract_from_paths(
                workflow_payload,
                [
                    ("data", "prompt"),
                    ("prompt",),
                    ("data", "systemPrompt"),
                    ("systemPrompt",),
                ],
            )
            if prompt:
                return prompt

            # workflow_graph fallback: scan node configs for prompt-like keys.
            nodes = workflow_payload.get("data", {}).get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    node_data = node.get("data")
                    if not isinstance(node_data, dict):
                        continue
                    prompt = _extract_from_paths(
                        node_data,
                        [
                            ("prompt",),
                            ("systemPrompt",),
                            ("globalPrompt",),
                            ("instructions",),
                        ],
                    )
                    if prompt:
                        return prompt
            return None

        try:
            data = self.get_agent(agent_id)
            if not isinstance(data, dict):
                return None

            candidate_paths = [
                ("globalPrompt",),
                ("prompt",),
                ("systemPrompt",),
                ("instructions",),
                ("responseEngine", "globalPrompt"),
                ("responseEngine", "prompt"),
                ("responseEngine", "systemPrompt"),
                ("response_engine", "global_prompt"),
                ("response_engine", "prompt"),
                ("agent", "globalPrompt"),
                ("agent", "prompt"),
            ]

            prompt = _extract_from_paths(data, candidate_paths)
            if prompt:
                return prompt

            # For newer Smallest "single_prompt"/workflow-based agents, prompt
            # lives under the workflow payload rather than the agent payload.
            workflow = self.get_agent_workflow(agent_id)
            prompt = _extract_from_workflow(workflow)
            if prompt:
                return prompt

            return None
        except Exception as exc:
            logger.warning(f"[SmallestProvider] Failed to extract agent prompt: {exc}")
            return None

    def update_agent_prompt(self, agent_id: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "globalPrompt": system_prompt,
        }
        if kwargs.get("name"):
            payload["name"] = kwargs["name"]

        data = self._request("PATCH", f"/agent/{agent_id}", json=payload, timeout=45.0)
        return {
            "agent_id": agent_id,
            "updated": True,
            "raw_response": data,
        }

    def test_connection(self) -> bool:
        user = self.get_user_details()
        if not user:
            raise ValueError("Smallest API returned an empty user payload")
        return True
