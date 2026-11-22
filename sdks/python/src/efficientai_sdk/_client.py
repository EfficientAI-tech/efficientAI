"""Public client entry points."""

from __future__ import annotations

from functools import cached_property
from types import TracebackType
from typing import TYPE_CHECKING, Optional

import httpx

from efficientai_sdk._base_client import AsyncAPIClient, SyncAPIClient
from efficientai_sdk._config import resolve_config

if TYPE_CHECKING:
    from efficientai_sdk.tracing.api import AsyncTraceResource, TraceResource

_VALIDATE_PATH = "/api/v1/auth/validate"


class EfficientAI(SyncAPIClient):
    """Synchronous EfficientAI client.

    Every argument falls back to an environment variable:
    ``EFFICIENTAI_API_KEY``, ``EFFICIENTAI_WORKSPACE_ID`` and ``EFFICIENTAI_BASE_URL``.

    >>> client = EfficientAI()
    >>> client.verify()
    True
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        workspace_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        config = resolve_config(
            api_key=api_key,
            workspace_id=workspace_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        super().__init__(config, http_client=http_client)

    def verify(self) -> bool:
        """Check the API key against the server.

        Returns ``True``, or raises ``AuthenticationError`` for a bad key and
        ``APIConnectionError`` when the server can't be reached.
        """
        self.request("POST", _VALIDATE_PATH, retry=True)
        return True

    @cached_property
    def trace(self) -> TraceResource:
        """Live call tracing. See :mod:`efficientai_sdk.tracing.api`."""
        from efficientai_sdk.tracing.api import TraceResource

        return TraceResource(self)

    def __enter__(self) -> EfficientAI:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"EfficientAI(base_url={self.base_url!r}, workspace_id={self.workspace_id!r})"


class AsyncEfficientAI(AsyncAPIClient):
    """Asynchronous EfficientAI client. Same arguments as :class:`EfficientAI`."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        workspace_id: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        config = resolve_config(
            api_key=api_key,
            workspace_id=workspace_id,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        super().__init__(config, http_client=http_client)

    async def verify(self) -> bool:
        """Async version of :meth:`EfficientAI.verify`."""
        await self.request("POST", _VALIDATE_PATH, retry=True)
        return True

    @cached_property
    def trace(self) -> AsyncTraceResource:
        """Live call tracing. See :mod:`efficientai_sdk.tracing.api`."""
        from efficientai_sdk.tracing.api import AsyncTraceResource

        return AsyncTraceResource(self)

    async def __aenter__(self) -> AsyncEfficientAI:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    def __repr__(self) -> str:
        return f"AsyncEfficientAI(base_url={self.base_url!r}, workspace_id={self.workspace_id!r})"
