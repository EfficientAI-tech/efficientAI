"""Thin Plivo SDK wrapper for telephony operations."""

from typing import Any, Dict, List, Optional
from loguru import logger

try:
    import plivo
except ImportError:  # pragma: no cover - environment-dependent optional dependency
    plivo = None


def normalize_e164(phone_number: str) -> str:
    """Normalize and validate an E.164 phone number."""
    if not phone_number:
        raise ValueError("Phone number is required")

    normalized = phone_number.strip().replace(" ", "")
    if not normalized.startswith("+"):
        raise ValueError("Phone number must be in E.164 format and start with '+'")
    if len(normalized) < 8 or len(normalized) > 20:
        raise ValueError("Phone number must be between 8 and 20 chars in E.164 format")
    if not normalized[1:].isdigit():
        raise ValueError("Phone number must contain digits only after '+'")
    return normalized


class PlivoClient:
    """Wrapper around plivo.RestClient that returns normalized dictionaries."""

    def __init__(self, auth_id: str, auth_token: str):
        if plivo is None:
            raise ValueError(
                "Plivo SDK is not installed. Install it with `pip install -e .` or `pip install plivo`."
            )
        self.client = plivo.RestClient(auth_id=auth_id, auth_token=auth_token)

    @staticmethod
    def _to_dict(data: Any) -> Dict[str, Any]:
        if isinstance(data, dict):
            return data
        if hasattr(data, "to_dict"):
            return data.to_dict()
        if hasattr(data, "dict"):
            return data.dict()
        if hasattr(data, "__dict__"):
            return dict(data.__dict__)
        return {"raw": str(data)}

    def test_connection(self) -> bool:
        """Check if the account credentials can perform API requests."""
        try:
            self.client.calls.list(limit=1)
            return True
        except Exception as e:
            logger.exception("Plivo connection test failed")
            raise ValueError(f"Failed to connect to Plivo: {str(e)}")

    def list_numbers(self) -> List[Dict[str, Any]]:
        """List account phone numbers."""
        try:
            response = self.client.numbers.list()
            response_dict = self._to_dict(response)
            objects = response_dict.get("objects", [])
            if isinstance(objects, list):
                return [self._to_dict(item) for item in objects]
            return []
        except Exception as e:
            logger.exception("Failed to list Plivo numbers")
            raise ValueError(f"Failed to list Plivo numbers: {str(e)}")

    def create_outbound_call(
        self,
        from_: str,
        to_: str,
        answer_url: str,
        hangup_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create outbound voice call."""
        try:
            kwargs: Dict[str, Any] = {
                "from_": from_,
                "to_": to_,
                "answer_url": answer_url,
                "answer_method": "POST",
            }
            if hangup_url:
                kwargs["hangup_url"] = hangup_url
                kwargs["hangup_method"] = "POST"
            response = self.client.calls.create(**kwargs)
            return self._to_dict(response)
        except Exception as e:
            logger.exception("Failed to create outbound call")
            raise ValueError(f"Failed to create outbound call: {str(e)}")

    def get_call_details(self, call_uuid: str) -> Dict[str, Any]:
        """Get call details by Plivo call UUID."""
        try:
            response = self.client.calls.get(call_uuid)
            return self._to_dict(response)
        except Exception as e:
            logger.exception("Failed to fetch call details")
            raise ValueError(f"Failed to fetch call details: {str(e)}")

    def start_voice_verification(
        self, recipient: str, app_uuid: str, callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Start voice OTP verification."""
        try:
            kwargs: Dict[str, Any] = {
                "recipient": recipient,
                "app_uuid": app_uuid,
                "channel": "voice",
            }
            if callback_url:
                kwargs["url"] = callback_url
                kwargs["method"] = "POST"
            response = self.client.verify_session.create(**kwargs)
            return self._to_dict(response)
        except Exception as e:
            logger.exception("Failed to start voice verification")
            raise ValueError(f"Failed to start voice verification: {str(e)}")

    def check_verification(self, session_uuid: str, otp_code: str) -> Dict[str, Any]:
        """Validate submitted OTP for a verification session."""
        try:
            response = self.client.verify_session.validate(session_uuid=session_uuid, otp=otp_code)
            return self._to_dict(response)
        except Exception as e:
            logger.exception("Failed to check voice verification")
            raise ValueError(f"Failed to check voice verification: {str(e)}")

    def get_verify_session(self, session_uuid: str) -> Dict[str, Any]:
        """Fetch verification session details."""
        try:
            response = self.client.verify_session.get(session_uuid)
            return self._to_dict(response)
        except Exception as e:
            logger.exception("Failed to fetch verify session")
            raise ValueError(f"Failed to fetch verify session: {str(e)}")
