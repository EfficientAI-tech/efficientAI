"""
VoiceMaker Provider (API-key validation support).
"""

from typing import Any, Dict, Optional

import requests

from app.services.voice_providers.base import BaseVoiceProvider


class VoiceMakerProvider(BaseVoiceProvider):
    """VoiceMaker provider implementation for integration key validation."""

    def create_web_call(self, agent_id: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("VoiceMaker does not support web-call agent orchestration in this app")

    def create_agent(self, response_engine: Dict[str, Any], voice_id: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("VoiceMaker agent creation is not supported in this app")

    def get_agent(self, agent_id: str) -> Dict[str, Any]:
        raise NotImplementedError("VoiceMaker agent retrieval is not supported in this app")

    def retrieve_call_metrics(self, call_id: str) -> Dict[str, Any]:
        raise NotImplementedError("VoiceMaker call metrics are not supported in this app")

    def extract_agent_prompt(self, agent_id: str) -> Optional[str]:
        raise NotImplementedError("VoiceMaker does not support agent prompt extraction")

    def update_agent_prompt(self, agent_id: str, system_prompt: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("VoiceMaker does not support agent prompt updates")

    def test_connection(self) -> bool:
        """Validate API key via a tiny TTS conversion request."""
        url = "https://developer.voicemaker.in/api/v1/voice/convert"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "VoiceId": "ai3-Jony",
            "Text": "Connection test.",
            "LanguageCode": "en-US",
            "OutputFormat": "mp3",
            "SampleRate": "22050",
            "ResponseType": "file",
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            return True
        error_text = response.text[:300] if response.text else "Unknown error"
        raise ValueError(f"VoiceMaker connection test failed ({response.status_code}): {error_text}")

