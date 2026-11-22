"""HTTP transport shared by the sync and async clients: auth headers, retries, error mapping."""

from __future__ import annotations

import asyncio
import logging
import platform
import random
import time
from collections.abc import Mapping
from typing import Any, Optional, Union

import httpx

from efficientai_sdk._config import ClientConfig
from efficientai_sdk._exceptions import (
    APIConnectionError,
    APITimeoutError,
    make_status_error,
    parse_retry_after,
)
from efficientai_sdk._version import __version__

logger = logging.getLogger("efficientai_sdk")

HEADER_API_KEY = "X-API-Key"
HEADER_WORKSPACE_ID = "X-Workspace-Id"

USER_AGENT = f"efficientai-sdk-python/{__version__} (python {platform.python_version()})"

RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
# Statuses where the server did not process the request, so even POST/PATCH is safe to retry.
RETRYABLE_STATUS_NON_IDEMPOTENT = frozenset({429, 503})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

INITIAL_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0
MAX_RETRY_AFTER = 60.0

QueryParams = Mapping[str, Any]
Timeout = Union[float, httpx.Timeout, None]


class _BaseClient:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config

    @property
    def base_url(self) -> str:
        return self._config.base_url

    @property
    def workspace_id(self) -> Optional[str]:
        return self._config.workspace_id

    @property
    def max_retries(self) -> int:
        return self._config.max_retries

    def _default_headers(self) -> dict[str, str]:
        headers = {
            HEADER_API_KEY: self._config.api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if self._config.workspace_id:
            headers[HEADER_WORKSPACE_ID] = self._config.workspace_id
        return headers

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self._config.base_url}/{path.lstrip('/')}"

    def _merge_headers(self, extra: Optional[Mapping[str, str]]) -> dict[str, str]:
        headers = self._default_headers()
        if extra:
            headers.update(extra)
        return headers

    # ---- retry policy -------------------------------------------------

    @staticmethod
    def _should_retry_status(method: str, status: int, retry: Optional[bool]) -> bool:
        if retry is False:
            return False
        if retry is True or method in IDEMPOTENT_METHODS:
            return status in RETRYABLE_STATUS
        return status in RETRYABLE_STATUS_NON_IDEMPOTENT

    @staticmethod
    def _should_retry_exception(method: str, exc: Exception, retry: Optional[bool]) -> bool:
        if retry is False:
            return False
        if isinstance(exc, httpx.ConnectError):
            return True  # the request was never sent
        if not isinstance(exc, httpx.TransportError):
            return False
        return retry is True or method in IDEMPOTENT_METHODS

    @staticmethod
    def _retry_delay(attempt: int, response: Optional[httpx.Response]) -> float:
        if response is not None:
            hinted = parse_retry_after(response.headers.get("retry-after"))
            if hinted is not None:
                return min(hinted, MAX_RETRY_AFTER)
        backoff = min(INITIAL_RETRY_DELAY * (2.0**attempt), MAX_RETRY_DELAY)
        return backoff * (0.5 + random.random() / 2)  # jitter: 50-100%

    # ---- responses ----------------------------------------------------

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            try:
                return response.json()
            except ValueError:
                return response.text
        return response.text

    def _process_response(self, response: httpx.Response) -> Any:
        body = self._parse_body(response)
        if response.is_success:
            return body
        raise make_status_error(response, body)


class SyncAPIClient(_BaseClient):
    def __init__(self, config: ClientConfig, *, http_client: Optional[httpx.Client] = None) -> None:
        super().__init__(config)
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(timeout=config.timeout)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[QueryParams] = None,
        json: Any = None,
        content: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Timeout = None,
        retry: Optional[bool] = None,
    ) -> Any:
        """Send a request and return the parsed body.

        ``retry=None`` applies the default policy (idempotent methods retry on 5xx/timeouts,
        POST/PATCH only on 429/503 and connection failures). ``True``/``False`` force it.
        """
        method = method.upper()
        url = self._url(path)
        merged = self._merge_headers(headers)
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    content=content,
                    headers=merged,
                    timeout=timeout if timeout is not None else self._config.timeout,
                )
            except httpx.TransportError as exc:
                if attempt < self.max_retries and self._should_retry_exception(method, exc, retry):
                    delay = self._retry_delay(attempt, None)
                    logger.debug("Retrying %s %s after %r in %.2fs", method, url, exc, delay)
                    time.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=exc.request) from exc
                raise APIConnectionError(
                    str(exc) or "Connection error.", request=exc.request
                ) from exc

            if (
                not response.is_success
                and attempt < self.max_retries
                and self._should_retry_status(method, response.status_code, retry)
            ):
                delay = self._retry_delay(attempt, response)
                logger.debug(
                    "Retrying %s %s after HTTP %s in %.2fs",
                    method,
                    url,
                    response.status_code,
                    delay,
                )
                response.close()
                time.sleep(delay)
                attempt += 1
                continue

            return self._process_response(response)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()


class AsyncAPIClient(_BaseClient):
    def __init__(
        self, config: ClientConfig, *, http_client: Optional[httpx.AsyncClient] = None
    ) -> None:
        super().__init__(config)
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=config.timeout)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[QueryParams] = None,
        json: Any = None,
        content: Optional[bytes] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Timeout = None,
        retry: Optional[bool] = None,
    ) -> Any:
        """Async version of :meth:`SyncAPIClient.request`."""
        method = method.upper()
        url = self._url(path)
        merged = self._merge_headers(headers)
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    content=content,
                    headers=merged,
                    timeout=timeout if timeout is not None else self._config.timeout,
                )
            except httpx.TransportError as exc:
                if attempt < self.max_retries and self._should_retry_exception(method, exc, retry):
                    delay = self._retry_delay(attempt, None)
                    logger.debug("Retrying %s %s after %r in %.2fs", method, url, exc, delay)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    raise APITimeoutError(request=exc.request) from exc
                raise APIConnectionError(
                    str(exc) or "Connection error.", request=exc.request
                ) from exc

            if (
                not response.is_success
                and attempt < self.max_retries
                and self._should_retry_status(method, response.status_code, retry)
            ):
                delay = self._retry_delay(attempt, response)
                logger.debug(
                    "Retrying %s %s after HTTP %s in %.2fs",
                    method,
                    url,
                    response.status_code,
                    delay,
                )
                await response.aclose()
                await asyncio.sleep(delay)
                attempt += 1
                continue

            return self._process_response(response)

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()
