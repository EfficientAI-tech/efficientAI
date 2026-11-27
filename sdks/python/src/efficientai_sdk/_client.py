"""Public client entry points."""

from __future__ import annotations

from functools import cached_property
from types import TracebackType
from typing import TYPE_CHECKING, Optional

import httpx

from efficientai_sdk._base_client import AsyncAPIClient, SyncAPIClient
from efficientai_sdk._config import resolve_config

if TYPE_CHECKING:
    from efficientai_sdk.simulations.api import (
        AsyncEvaluatorsResource,
        AsyncResultsResource,
        AsyncSimulationsResource,
        AsyncSuitesResource,
        EvaluatorsResource,
        ResultsResource,
        SimulationsResource,
        SuitesResource,
    )
    from efficientai_sdk.tracing.api import AsyncTraceResource, TraceResource


class EfficientAI(SyncAPIClient):
    """Synchronous EfficientAI client.

    Every argument falls back to an environment variable:
    ``EFFICIENTAI_API_KEY``, ``EFFICIENTAI_WORKSPACE_ID``, ``EFFICIENTAI_BASE_URL``,
    and ``EFFICIENTAI_API_PREFIX`` (defaults to ``/api/v1``).

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
        api_prefix: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        config = resolve_config(
            api_key=api_key,
            workspace_id=workspace_id,
            base_url=base_url,
            api_prefix=api_prefix,
            timeout=timeout,
            max_retries=max_retries,
        )
        super().__init__(config, http_client=http_client)

    def verify(self) -> bool:
        """Check the API key against the server.

        Returns ``True``, or raises ``AuthenticationError`` for a bad key and
        ``APIConnectionError`` when the server can't be reached.
        """
        self.request("POST", self.api_path("auth/validate"), retry=True)
        return True

    @cached_property
    def trace(self) -> TraceResource:
        """Live call tracing. See :mod:`efficientai_sdk.tracing.api`."""
        from efficientai_sdk.tracing.api import TraceResource

        return TraceResource(self)

    @cached_property
    def simulations(self) -> SimulationsResource:
        """Start and inspect simulation runs. See :mod:`efficientai_sdk.simulations`."""
        from efficientai_sdk.simulations.api import SimulationsResource

        return SimulationsResource(self)

    @cached_property
    def suites(self) -> SuitesResource:
        """Run an evaluator suite."""
        from efficientai_sdk.simulations.api import SuitesResource

        return SuitesResource(self)

    @cached_property
    def evaluators(self) -> EvaluatorsResource:
        """Run specific evaluators."""
        from efficientai_sdk.simulations.api import EvaluatorsResource

        return EvaluatorsResource(self)

    @cached_property
    def results(self) -> ResultsResource:
        """Read evaluator results."""
        from efficientai_sdk.simulations.api import ResultsResource

        return ResultsResource(self)

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
        api_prefix: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        config = resolve_config(
            api_key=api_key,
            workspace_id=workspace_id,
            base_url=base_url,
            api_prefix=api_prefix,
            timeout=timeout,
            max_retries=max_retries,
        )
        super().__init__(config, http_client=http_client)

    async def verify(self) -> bool:
        """Async version of :meth:`EfficientAI.verify`."""
        await self.request("POST", self.api_path("auth/validate"), retry=True)
        return True

    @cached_property
    def trace(self) -> AsyncTraceResource:
        """Live call tracing. See :mod:`efficientai_sdk.tracing.api`."""
        from efficientai_sdk.tracing.api import AsyncTraceResource

        return AsyncTraceResource(self)

    @cached_property
    def simulations(self) -> AsyncSimulationsResource:
        """Async form of :attr:`EfficientAI.simulations`."""
        from efficientai_sdk.simulations.api import AsyncSimulationsResource

        return AsyncSimulationsResource(self)

    @cached_property
    def suites(self) -> AsyncSuitesResource:
        """Async form of :attr:`EfficientAI.suites`."""
        from efficientai_sdk.simulations.api import AsyncSuitesResource

        return AsyncSuitesResource(self)

    @cached_property
    def evaluators(self) -> AsyncEvaluatorsResource:
        """Async form of :attr:`EfficientAI.evaluators`."""
        from efficientai_sdk.simulations.api import AsyncEvaluatorsResource

        return AsyncEvaluatorsResource(self)

    @cached_property
    def results(self) -> AsyncResultsResource:
        """Async form of :attr:`EfficientAI.results`."""
        from efficientai_sdk.simulations.api import AsyncResultsResource

        return AsyncResultsResource(self)

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
