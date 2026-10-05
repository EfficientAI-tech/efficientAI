"""Twilio REST client for number inventory and SMS webhook configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import httpx


class TwilioClient:
    def __init__(self, account_sid: str, auth_token: str) -> None:
        self.account_sid = (account_sid or "").strip()
        self.auth_token = (auth_token or "").strip()
        if not self.account_sid or not self.auth_token:
            raise ValueError("Twilio Account SID and Auth Token are required")

    def _base_url(self) -> str:
        return f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"

    def list_incoming_phone_numbers(self) -> List[Dict[str, Any]]:
        numbers: List[Dict[str, Any]] = []
        url: Optional[str] = f"{self._base_url()}/IncomingPhoneNumbers.json?PageSize=100"
        with httpx.Client(timeout=60.0) as client:
            while url:
                resp = client.get(url, auth=(self.account_sid, self.auth_token))
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    batch = data.get("incoming_phone_numbers") or []
                    if isinstance(batch, list):
                        numbers.extend(batch)
                    next_page = data.get("next_page_uri")
                    if next_page:
                        url = f"https://api.twilio.com{next_page}"
                    else:
                        url = None
                else:
                    break
        return [
            {
                "e164": item.get("phone_number"),
                "phone_number": item.get("phone_number"),
                "sid": item.get("sid"),
                "friendly_name": item.get("friendly_name"),
                "capabilities": item.get("capabilities"),
                "status": item.get("status"),
            }
            for item in numbers
            if isinstance(item, dict) and item.get("phone_number")
        ]

    def set_number_voice_webhook(
        self,
        incoming_phone_number_sid: str,
        voice_url: str,
    ) -> Tuple[bool, str, Optional[str]]:
        sid = (incoming_phone_number_sid or "").strip()
        if not sid:
            return False, "Missing Twilio incoming phone number SID", None
        url = f"{self._base_url()}/IncomingPhoneNumbers/{sid}.json"
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                url,
                auth=(self.account_sid, self.auth_token),
                data={"VoiceUrl": voice_url, "VoiceMethod": "POST"},
            )
            if resp.is_error:
                detail = (resp.text or "")[:300]
                return False, f"Twilio voice webhook update failed: {detail}", sid
        return True, "Twilio voice inbound webhook configured", sid

    def set_number_sms_webhook(
        self,
        incoming_phone_number_sid: str,
        sms_url: str,
    ) -> Tuple[bool, str, Optional[str]]:
        sid = (incoming_phone_number_sid or "").strip()
        if not sid:
            return False, "Missing Twilio incoming phone number SID", None
        url = f"{self._base_url()}/IncomingPhoneNumbers/{sid}.json"
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                url,
                auth=(self.account_sid, self.auth_token),
                data={"SmsUrl": sms_url, "SmsMethod": "POST"},
            )
            if resp.is_error:
                detail = (resp.text or "")[:300]
                return False, f"Twilio SMS webhook update failed: {detail}", sid
        return True, "Twilio SMS inbound webhook configured", sid
