"""Thin Vobiz REST API client for telephony operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key
from app.models.database import TelephonyIntegration
from app.services.credentials import resolve_telephony_integration
from app.services.telephony.plivo_client import normalize_e164


class VobizClient:
    """HTTP client for the Vobiz telephony API (Plivo-compatible surface)."""

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        api_base: Optional[str] = None,
    ):
        if not auth_id or not auth_token:
            raise ValueError("Vobiz auth_id and auth_token are required")
        self.auth_id = auth_id
        self.auth_token = auth_token
        self.api_base = (api_base or settings.VOBIZ_API_BASE).rstrip("/")
        self._headers = {
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
            "Content-Type": "application/json",
        }

    def _account_base(self) -> str:
        return f"{self.api_base}/api/v1/Account/{self.auth_id}"

    def _call_endpoint(self) -> str:
        return f"{self._account_base()}/Call/"

    def _numbers_endpoint(self) -> str:
        return f"{self._account_base()}/numbers"

    def _application_endpoint(self) -> str:
        return f"{self._account_base()}/Application/"

    @staticmethod
    def _to_dict(data: Any) -> Dict[str, Any]:
        if isinstance(data, dict):
            return data
        return {"raw": str(data)}

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, headers=self._headers, json=json)
        return response

    def test_connection(self) -> bool:
        """Check if credentials can reach the Vobiz API."""
        try:
            response = self._request("GET", self._call_endpoint(), timeout=15.0)
            if response.status_code >= 400:
                raise ValueError(f"Vobiz API returned HTTP {response.status_code}")
            return True
        except Exception as e:
            logger.exception("Vobiz connection test failed")
            raise ValueError(f"Failed to connect to Vobiz: {str(e)}") from e

    def list_account_numbers(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List phone numbers owned by this Vobiz account (paginated)."""
        items: List[Dict[str, Any]] = []
        offset = 0
        page_limit = max(min(limit, 100), 1)

        while True:
            url = f"{self._numbers_endpoint()}?limit={page_limit}&offset={offset}"
            try:
                response = self._request("GET", url, timeout=30.0)
            except Exception as e:
                logger.exception("Failed to list Vobiz account numbers")
                raise ValueError(f"Failed to list account numbers: {str(e)}") from e

            if response.status_code >= 400:
                raise ValueError(
                    f"Vobiz list numbers failed (HTTP {response.status_code}): {response.text[:300]}"
                )

            data = response.json() if response.content else {}
            batch = data.get("items") or data.get("objects") or []
            if not isinstance(batch, list):
                batch = []
            items.extend(batch)

            total = data.get("total")
            if not batch or (total is not None and len(items) >= int(total)):
                break
            if len(batch) < page_limit:
                break
            offset += page_limit

        return items

    def create_application(
        self,
        *,
        app_name: str,
        answer_url: str,
        hangup_url: Optional[str] = None,
        answer_method: str = "POST",
        hangup_method: str = "POST",
    ) -> Dict[str, Any]:
        """Create a Vobiz voice application with webhook URLs."""
        payload: Dict[str, Any] = {
            "app_name": app_name,
            "answer_url": answer_url,
            "answer_method": answer_method,
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url
            payload["hangup_method"] = hangup_method

        try:
            response = self._request("POST", self._application_endpoint(), json=payload)
            if response.status_code >= 400:
                raise ValueError(
                    f"Vobiz create application failed (HTTP {response.status_code}): {response.text[:300]}"
                )
            return self._to_dict(response.json() if response.content else {})
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Failed to create Vobiz application")
            raise ValueError(f"Failed to create application: {str(e)}") from e

    def update_application(
        self,
        app_id: str,
        *,
        answer_url: str,
        hangup_url: Optional[str] = None,
        answer_method: str = "POST",
        hangup_method: str = "POST",
    ) -> Dict[str, Any]:
        """Update an existing Vobiz voice application."""
        payload: Dict[str, Any] = {
            "answer_url": answer_url,
            "answer_method": answer_method,
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url
            payload["hangup_method"] = hangup_method

        endpoint = f"{self._application_endpoint()}{app_id}/"
        try:
            response = self._request("POST", endpoint, json=payload)
            if response.status_code >= 400:
                raise ValueError(
                    f"Vobiz update application failed (HTTP {response.status_code}): {response.text[:300]}"
                )
            return self._to_dict(response.json() if response.content else {})
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Failed to update Vobiz application")
            raise ValueError(f"Failed to update application: {str(e)}") from e

    def attach_number_to_application(self, number: str, application_id: str) -> Dict[str, Any]:
        """Attach a phone number to a Vobiz application."""
        e164 = normalize_e164(number)
        encoded = quote(e164, safe="")
        endpoint = f"{self._numbers_endpoint()}/{encoded}/application"
        try:
            response = self._request(
                "POST",
                endpoint,
                json={"application_id": application_id},
            )
            if response.status_code >= 400:
                raise ValueError(
                    f"Vobiz attach number failed (HTTP {response.status_code}): {response.text[:300]}"
                )
            return self._to_dict(response.json() if response.content else {})
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Failed to attach Vobiz number to application")
            raise ValueError(f"Failed to attach number to application: {str(e)}") from e

    def set_number_answer_url(
        self,
        number: str,
        answer_url: str,
        *,
        hangup_url: Optional[str] = None,
        existing_application_id: Optional[str] = None,
        app_name: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """Point inbound calls for a number at our answer webhook.

        Returns ``(success, message, application_id)``.
        """
        hangup = hangup_url or answer_url
        app_id = existing_application_id

        if app_id:
            try:
                self.update_application(
                    app_id,
                    answer_url=answer_url,
                    hangup_url=hangup,
                )
                self.attach_number_to_application(number, app_id)
                return True, "Updated existing Vobiz application", app_id
            except ValueError as exc:
                logger.warning(
                    "Vobiz update/attach for existing app {} failed: {}; creating new app",
                    app_id,
                    exc,
                )

        safe_name = (app_name or f"efficientai_{normalize_e164(number).lstrip('+')}").replace(" ", "_")
        try:
            created = self.create_application(
                app_name=safe_name[:64],
                answer_url=answer_url,
                hangup_url=hangup,
            )
            app_id = str(created.get("app_id") or "")
            if not app_id:
                return False, "Vobiz application created but app_id missing in response", None
            self.attach_number_to_application(number, app_id)
            return True, "Created and attached Vobiz application", app_id
        except ValueError as exc:
            return False, str(exc), None

    def create_outbound_call(
        self,
        from_: str,
        to_: str,
        answer_url: str,
        hangup_url: Optional[str] = None,
        answer_method: str = "POST",
        hangup_method: str = "POST",
        sip_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create an outbound voice call."""
        from efficientai.integrations.efficientai_traces.correlation import format_plivo_sip_headers

        from_ = normalize_e164(from_)
        to_ = normalize_e164(to_)
        payload: Dict[str, Any] = {
            "from": from_,
            "to": to_,
            "answer_url": answer_url,
            "answer_method": answer_method,
        }
        if hangup_url:
            payload["hangup_url"] = hangup_url
            payload["hangup_method"] = hangup_method
        if sip_headers:
            payload["sipHeaders"] = format_plivo_sip_headers(sip_headers)

        try:
            response = self._request("POST", self._call_endpoint(), json=payload)
            if response.status_code >= 400:
                raise ValueError(
                    f"Vobiz outbound call failed (HTTP {response.status_code}): {response.text[:300]}"
                )
            data = response.json() if response.content else {}
            return self._to_dict(data)
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Failed to create Vobiz outbound call")
            raise ValueError(f"Failed to create outbound call: {str(e)}") from e

    def hangup_call(self, call_id: str) -> bool:
        """Terminate an active call."""
        if not call_id:
            raise ValueError("call_id is required")
        endpoint = f"{self._call_endpoint()}{call_id}/"
        try:
            response = self._request("DELETE", endpoint, timeout=15.0)
            if response.status_code in (200, 204, 404):
                return True
            raise ValueError(
                f"Vobiz hangup failed (HTTP {response.status_code}): {response.text[:300]}"
            )
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Failed to hang up Vobiz call")
            raise ValueError(f"Failed to hang up call: {str(e)}") from e


def build_vobiz_client_from_settings() -> VobizClient:
    """Build a VobizClient from platform-level settings."""
    if not settings.VOBIZ_AUTH_ID or not settings.VOBIZ_AUTH_TOKEN:
        raise ValueError("Vobiz is not configured. Set VOBIZ_AUTH_ID and VOBIZ_AUTH_TOKEN.")
    return VobizClient(
        auth_id=settings.VOBIZ_AUTH_ID,
        auth_token=settings.VOBIZ_AUTH_TOKEN,
        api_base=settings.VOBIZ_API_BASE,
    )


def build_vobiz_client_for_org(
    db: Session,
    org_id: UUID,
    *,
    credential_id: Optional[UUID] = None,
) -> Tuple[VobizClient, Optional[TelephonyIntegration]]:
    """Resolve per-org BYO Vobiz credentials, else platform-level settings."""
    integration = resolve_telephony_integration("vobiz", db, org_id, credential_id=credential_id)
    if integration:
        auth_id = decrypt_api_key(integration.auth_id)
        auth_token = decrypt_api_key(integration.auth_token)
        return (
            VobizClient(auth_id=auth_id, auth_token=auth_token, api_base=settings.VOBIZ_API_BASE),
            integration,
        )
    return build_vobiz_client_from_settings(), None
