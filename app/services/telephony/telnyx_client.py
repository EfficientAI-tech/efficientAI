"""Telnyx REST client for numbers, Call Control, and messaging."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import httpx


class TelnyxClient:
    def __init__(self, api_key: str, *, messaging_profile_id: Optional[str] = None) -> None:
        self.api_key = (api_key or "").strip()
        self.messaging_profile_id = (messaging_profile_id or "").strip() or None
        if not self.api_key:
            raise ValueError("Telnyx API key is required")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_phone_numbers(self) -> List[Dict[str, Any]]:
        numbers: List[Dict[str, Any]] = []
        url: Optional[str] = "https://api.telnyx.com/v2/phone_numbers?page[size]=100"
        with httpx.Client(timeout=60.0) as client:
            while url:
                resp = client.get(url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    break
                batch = data.get("data") or []
                if isinstance(batch, list):
                    numbers.extend(batch)
                meta = data.get("meta") or {}
                url = (meta.get("next_page_url") or "").strip() or None
        return [
            {
                "e164": item.get("phone_number"),
                "phone_number": item.get("phone_number"),
                "id": item.get("id"),
                "status": item.get("status"),
                "country_iso2": item.get("country_iso_alpha2") or item.get("country_code"),
                "region": item.get("region_information"),
                "capabilities": {
                    "voice": True,
                    "sms": bool(item.get("messaging_profile_id")),
                },
                "messaging_profile_id": item.get("messaging_profile_id"),
                "connection_id": item.get("connection_id"),
            }
            for item in numbers
            if isinstance(item, dict) and item.get("phone_number")
        ]

    def send_message(
        self,
        *,
        from_e164: str,
        to_e164: str,
        text: str,
        messaging_profile_id: Optional[str] = None,
    ) -> str:
        profile_id = (messaging_profile_id or self.messaging_profile_id or "").strip()
        if not profile_id:
            raise ValueError("Telnyx messaging profile id is required to send SMS")
        payload = {
            "from": from_e164,
            "to": to_e164,
            "text": text,
            "messaging_profile_id": profile_id,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.telnyx.com/v2/messages",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict) and inner.get("id"):
                return str(inner["id"])
        return ""

    def patch_messaging_profile_webhook(
        self,
        profile_id: str,
        webhook_url: str,
    ) -> Tuple[bool, str]:
        pid = (profile_id or "").strip()
        if not pid:
            return False, "Missing Telnyx messaging profile id"
        url = f"https://api.telnyx.com/v2/messaging_profiles/{pid}"
        with httpx.Client(timeout=60.0) as client:
            resp = client.patch(
                url,
                headers=self._headers(),
                json={"webhook_url": webhook_url},
            )
            if resp.is_error:
                return False, (resp.text or "")[:300]
        return True, "Telnyx messaging profile webhook configured"

    def answer_call(self, call_control_id: str) -> None:
        self._call_action(call_control_id, "answer")

    def streaming_start(
        self,
        call_control_id: str,
        stream_url: str,
        *,
        stream_track: str = "both_tracks",
    ) -> None:
        self._call_action(
            call_control_id,
            "streaming_start",
            {"stream_url": stream_url, "stream_track": stream_track},
        )

    def hangup(self, call_control_id: str) -> None:
        self._call_action(call_control_id, "hangup")

    def _call_action(
        self,
        call_control_id: str,
        action: str,
        body: Optional[dict[str, Any]] = None,
    ) -> None:
        ccid = (call_control_id or "").strip()
        if not ccid:
            raise ValueError("call_control_id is required")
        url = f"https://api.telnyx.com/v2/calls/{ccid}/actions/{action}"
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=self._headers(), json=body or {})
            if resp.is_error:
                detail = (resp.text or "")[:400]
                raise httpx.HTTPStatusError(
                    f"Telnyx {action} failed: {detail}",
                    request=resp.request,
                    response=resp,
                )
