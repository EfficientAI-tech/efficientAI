"""Thin Plivo SDK wrapper for telephony operations."""

from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

try:
    import plivo
except ImportError:  # pragma: no cover - environment-dependent optional dependency
    plivo = None


def normalize_e164(phone_number: str, *, default_country_code: str = "91") -> str:
    """Normalize and validate an E.164 phone number."""
    if not phone_number:
        raise ValueError("Phone number is required")

    normalized = phone_number.strip().replace(" ", "").replace("-", "")
    country_code = (default_country_code or "91").lstrip("+")

    if not normalized.startswith("+"):
        digits = normalized
        if not digits.isdigit():
            raise ValueError("Phone number must contain digits only")

        # Indian/local trunk prefix: 0 + 10-digit national number.
        if digits.startswith("0") and len(digits) == 11:
            normalized = f"+{country_code}{digits[1:]}"
        elif digits.startswith(country_code) and len(digits) >= len(country_code) + 8:
            normalized = f"+{digits}"
        elif len(digits) == 10 and digits[0] in "6789":
            normalized = f"+{country_code}{digits}"
        else:
            normalized = f"+{digits}"
    else:
        normalized = normalized

    if len(normalized) < 8 or len(normalized) > 20:
        raise ValueError("Phone number must be between 8 and 20 chars in E.164 format")
    if not normalized[1:].isdigit():
        raise ValueError("Phone number must contain digits only after '+'")
    return normalized


def expand_phone_candidates(
    phone_number: Optional[str],
    *,
    default_country_code: Optional[str] = None,
) -> list[str]:
    """Return deduplicated E.164 variants for provider webhook matching."""
    if not phone_number:
        return []

    from app.config import settings

    country_code = (default_country_code or settings.VOBIZ_DEFAULT_COUNTRY_CODE or "91").lstrip("+")
    raw = str(phone_number).strip().replace(" ", "").replace("-", "")
    if not raw:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(value: Optional[str]) -> None:
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    try:
        _add(normalize_e164(raw, default_country_code=country_code))
    except ValueError:
        pass

    digits = raw[1:] if raw.startswith("+") else raw
    if digits.isdigit():
        if digits.startswith("0") and len(digits) == 11:
            _add(f"+{country_code}{digits[1:]}")
        if digits.startswith(country_code):
            _add(f"+{digits}")
        if len(digits) == 10 and digits[0] in "6789":
            _add(f"+{country_code}{digits}")

    return candidates


class PlivoClient:
    """Wrapper around plivo.RestClient that returns normalized dictionaries."""

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        *,
        credential_fingerprint: Optional[str] = None,
    ):
        if plivo is None:
            raise ValueError(
                "Plivo SDK is not installed. Install it with `pip install -e .` or `pip install plivo`."
            )
        self.client = plivo.RestClient(auth_id=auth_id, auth_token=auth_token)
        self._auth_id = auth_id
        self._auth_token = auth_token
        self._credential_fingerprint = credential_fingerprint

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

    def set_number_answer_url(
        self,
        number: str,
        answer_url: str,
        *,
        hangup_url: Optional[str] = None,
        existing_application_id: Optional[str] = None,
        app_name: Optional[str] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """Point inbound calls for a number at our answer webhook."""
        e164 = normalize_e164(number)
        plivo_number = e164.lstrip("+")
        hangup = hangup_url or answer_url
        app_id = existing_application_id

        if app_id:
            try:
                self.client.applications.update(
                    app_id,
                    answer_url=answer_url,
                    answer_method="POST",
                    hangup_url=hangup,
                    hangup_method="POST",
                )
                self.client.numbers.update(plivo_number, app_id=app_id)
                return True, "Updated existing Plivo application", app_id
            except Exception as exc:
                logger.warning(
                    "Plivo update/attach for existing app {} failed: {}; creating new app",
                    app_id,
                    exc,
                )
                app_id = None

        try:
            created = self.client.applications.create(
                app_name=app_name or "efficientai",
                answer_url=answer_url,
                answer_method="POST",
                hangup_url=hangup,
                hangup_method="POST",
            )
            created_dict = self._to_dict(created)
            app_id = created_dict.get("app_id") or created_dict.get("application_id")
            if not app_id:
                return False, "Plivo application created but app_id missing", None
            self.client.numbers.update(plivo_number, app_id=app_id)
            return True, "Created Plivo application and attached number", app_id
        except Exception as e:
            logger.exception("Failed to configure Plivo number webhook")
            return False, f"Failed to configure Plivo webhook: {str(e)}", app_id

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

    def download_recording(self, recording_url: str) -> Tuple[bytes, str]:
        """Download a recording from Plivo with HTTP Basic auth."""
        from app.services.telephony.recording_download import download_recording_url

        return download_recording_url(
            recording_url,
            auth=(self._auth_id, self._auth_token),
            credential_fingerprint=self._credential_fingerprint,
        )

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
