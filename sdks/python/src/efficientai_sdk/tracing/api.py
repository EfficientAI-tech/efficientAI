"""High-level tracing API, reached through ``client.trace``.

Async::

    client = AsyncEfficientAI()
    async with client.trace.session(agent_id="...", transport="websocket") as call:
        with call.turn():
            with call.stt(model="nova-3", provider="deepgram") as stt:
                stt.set_transcript("I'd like to book a table")
            with call.llm(model="gpt-4o", provider="openai") as llm:
                llm.set_output("Sure, for how many people?")
            with call.tts(model="sonic", provider="cartesia") as tts:
                tts.set_text("Sure, for how many people?")

Sync code uses ``EfficientAI`` and a plain ``with``. Nothing here raises because of
EfficientAI: if the session can't be opened, the call is disabled, a warning is logged,
and every span helper becomes a no-op. Exceptions from your own code inside a span are
recorded on the span and re-raised unchanged.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Optional, Union

from efficientai_sdk._exceptions import EfficientAIError
from efficientai_sdk._version import __version__
from efficientai_sdk.tracing import otel
from efficientai_sdk.tracing.context import (
    call_attributes,
    reset_call_attributes,
    set_call_attributes,
)
from efficientai_sdk.tracing.correlation import (
    extract_call_short_id,
    span_correlation_attributes,
)
from efficientai_sdk.tracing.handshake import parse_trace_handshake
from efficientai_sdk.tracing.session import (
    SESSIONS_PATH,
    VALID_TRANSPORTS,
    TraceSessionError,
    _run_id_from,
    resolve_otlp_endpoint,
)

if TYPE_CHECKING:
    from efficientai_sdk._base_client import AsyncAPIClient, SyncAPIClient

logger = logging.getLogger("efficientai_sdk.tracing")

__all__ = [
    "AsyncTraceResource",
    "CallTrace",
    "ComponentSpan",
    "RetrievalSpan",
    "ToolSpan",
    "TraceResource",
    "TurnSpan",
]

AttributeValue = Union[str, bool, int, float]

# Long tool arguments/results or prompts are truncated so a single span can't blow up
# the OTLP request (the server keeps attributes as strings).
MAX_ATTRIBUTE_CHARS = 8192


# ---------------------------------------------------------------------------
# Span wrappers
# ---------------------------------------------------------------------------


class ComponentSpan:
    """A span for one step of a turn. Setters are safe no-ops when tracing is off."""

    def __init__(self, span: Any = None) -> None:
        self._span = span

    @property
    def recording(self) -> bool:
        return self._span is not None

    def set_attribute(self, key: str, value: Optional[AttributeValue]) -> ComponentSpan:
        if self._span is not None and value is not None:
            if isinstance(value, str) and len(value) > MAX_ATTRIBUTE_CHARS:
                value = value[:MAX_ATTRIBUTE_CHARS] + "...[truncated]"
            try:
                self._span.set_attribute(key, value)
            except Exception:
                logger.debug("Failed to set span attribute %s", key, exc_info=True)
        return self

    def set_attributes(self, attributes: Mapping[str, Optional[AttributeValue]]) -> ComponentSpan:
        for key, value in attributes.items():
            self.set_attribute(key, value)
        return self

    def set_ttfb(self, seconds: float) -> ComponentSpan:
        """Time to first byte/token, in seconds. Shown as the component's latency."""
        return self.set_attribute("metrics.ttfb", float(seconds))

    # STT
    def set_transcript(self, text: str) -> ComponentSpan:
        """What the user said (STT) or, on an s2s span, the user's transcript."""
        self.set_attribute("transcript", text)
        return self.set_attribute("transcript.is_input", True)

    # LLM / s2s
    def set_input(self, text: str) -> ComponentSpan:
        return self.set_attribute("input", text)

    def set_output(self, text: str) -> ComponentSpan:
        """The agent's reply (LLM or s2s)."""
        return self.set_attribute("output", text)

    def set_usage(
        self, *, input_tokens: Optional[int] = None, output_tokens: Optional[int] = None
    ) -> ComponentSpan:
        self.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        return self.set_attribute("gen_ai.usage.output_tokens", output_tokens)

    # TTS
    def set_text(self, text: str) -> ComponentSpan:
        """The text that was spoken (TTS)."""
        return self.set_attribute("text", text)


class ToolSpan(ComponentSpan):
    """A tool/function call made by the agent."""

    def set_arguments(self, arguments: str) -> ToolSpan:
        self.set_attribute("gen_ai.tool.call.arguments", arguments)
        return self

    def set_result(self, result: str) -> ToolSpan:
        self.set_attribute("gen_ai.tool.call.result", result)
        return self

    def set_error(self, message: str) -> ToolSpan:
        self.set_attribute("error", True)
        self.set_attribute("error.message", message)
        return self


class RetrievalSpan(ComponentSpan):
    """A knowledge-base / RAG lookup."""

    def set_documents(self, count: int) -> RetrievalSpan:
        self.set_attribute("retrieval.documents.count", int(count))
        return self


class TurnSpan(ComponentSpan):
    """The span grouping one user/agent exchange."""

    def set_user_bot_latency(self, seconds: float) -> TurnSpan:
        """End of user speech to start of agent speech, measured by your stack."""
        self.set_attribute("turn.user_bot_latency_seconds", float(seconds))
        return self

    def set_interrupted(self, interrupted: bool = True) -> TurnSpan:
        self.set_attribute("turn.was_interrupted", bool(interrupted))
        return self


def _component_attributes(
    operation: str,
    *,
    model: Optional[str],
    provider: Optional[str],
    extra: Mapping[str, Optional[AttributeValue]],
) -> dict[str, AttributeValue]:
    attrs: dict[str, AttributeValue] = {"gen_ai.operation.name": operation}
    if model:
        attrs["gen_ai.request.model"] = model
    if provider:
        attrs["gen_ai.provider.name"] = provider.lower()
    for key, value in extra.items():
        if value is not None:
            attrs[key] = value
    return attrs


# ---------------------------------------------------------------------------
# Call
# ---------------------------------------------------------------------------


class CallTrace:
    """One traced call. Get it from ``client.trace.session(...)``."""

    def __init__(
        self,
        *,
        call_short_id: Optional[str],
        enabled: bool,
        workspace_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        transport: Optional[str] = None,
        evaluator_result_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        owns_session: bool = False,
        error: Optional[str] = None,
        extra_attributes: Optional[Mapping[str, str]] = None,
        channel: Optional[str] = None,
    ) -> None:
        self.call_short_id = call_short_id
        self.enabled = enabled and bool(call_short_id)
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.transport = transport
        self.evaluator_result_id = evaluator_result_id
        self.trace_id = trace_id
        self.owns_session = owns_session
        self.error = error
        self.channel = channel
        self._turns = 0
        self._token: Optional[contextvars.Token[Optional[dict[str, str]]]] = None
        attrs = (
            span_correlation_attributes(
                call_short_id=call_short_id,
                evaluator_result_id=evaluator_result_id,
                agent_id=agent_id,
                workspace_id=workspace_id,
                transport=transport,
            )
            if self.enabled
            else {}
        )
        if self.enabled and channel:
            attrs["efficientai.channel"] = channel
        if self.enabled and extra_attributes:
            attrs.update(extra_attributes)
        self._attributes = attrs

    def __repr__(self) -> str:
        return (
            f"CallTrace(call_short_id={self.call_short_id!r}, enabled={self.enabled}, "
            f"transport={self.transport!r})"
        )

    @property
    def attributes(self) -> dict[str, str]:
        """``efficientai.*`` attributes for this call (empty when disabled).

        Pass these to frameworks that take extra span attributes, such as Pipecat's
        ``PipelineTask(additional_span_attributes=...)``.
        """
        return dict(self._attributes)

    # ---- context ---------------------------------------------------------

    @contextmanager
    def activate(self) -> Iterator[CallTrace]:
        """Tag spans created in this block (and tasks started from it) with this call.

        Sessions activate themselves; use this when work for the call runs in another
        thread or a task created before the session opened.
        """
        if not self.enabled:
            yield self
            return
        with call_attributes(self._attributes):
            yield self

    def _enter_context(self) -> None:
        if self.enabled:
            self._token = set_call_attributes(self._attributes)

    def _exit_context(self) -> None:
        if self._token is not None:
            reset_call_attributes(self._token)
            self._token = None

    # ---- spans -----------------------------------------------------------

    @contextmanager
    def _span(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue],
        wrapper: type[ComponentSpan] = ComponentSpan,
    ) -> Iterator[Any]:
        manager: Any = None
        span: Any = None
        if self.enabled and otel.OTEL_AVAILABLE:
            try:
                from opentelemetry import trace as otel_trace

                tracer = otel_trace.get_tracer("efficientai_sdk", __version__)
                manager = tracer.start_as_current_span(
                    name, attributes={**self._attributes, **attributes}
                )
                span = manager.__enter__()
            except Exception:
                logger.warning("EfficientAI: could not start span %r", name, exc_info=True)
                manager = None
        if manager is None:
            yield wrapper()
            return
        try:
            yield wrapper(span)
        except BaseException as exc:
            manager.__exit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.debug("EfficientAI: failed to end span %r", name, exc_info=True)

    def turn(self, number: Optional[int] = None, **attributes: AttributeValue) -> Any:
        """Group one user/agent exchange. Yields a :class:`TurnSpan`."""
        self._turns = number if number is not None else self._turns + 1
        return self._span("turn", {"turn.number": self._turns, **attributes}, TurnSpan)

    def stt(
        self,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        transcript: Optional[str] = None,
        **attributes: AttributeValue,
    ) -> Any:
        """Speech-to-text. Set the user's words with ``set_transcript``."""
        extra: dict[str, Optional[AttributeValue]] = {**attributes}
        if transcript is not None:
            extra.update({"transcript": transcript, "transcript.is_input": True})
        return self._span(
            "stt", _component_attributes("stt", model=model, provider=provider, extra=extra)
        )

    def llm(
        self,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        input: Optional[str] = None,
        output: Optional[str] = None,
        **attributes: AttributeValue,
    ) -> Any:
        """LLM call. Set the reply with ``set_output``."""
        extra: dict[str, Optional[AttributeValue]] = {
            "input": input,
            "output": output,
            **attributes,
        }
        return self._span(
            "llm", _component_attributes("chat", model=model, provider=provider, extra=extra)
        )

    def tts(
        self,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        text: Optional[str] = None,
        **attributes: AttributeValue,
    ) -> Any:
        """Text-to-speech. Set the spoken text with ``set_text``."""
        extra: dict[str, Optional[AttributeValue]] = {"text": text, **attributes}
        return self._span(
            "tts", _component_attributes("tts", model=model, provider=provider, extra=extra)
        )

    def s2s(
        self,
        *,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        **attributes: AttributeValue,
    ) -> Any:
        """Speech-to-speech / realtime model turn (replaces stt + llm + tts)."""
        return self._span(
            "s2s",
            _component_attributes("s2s", model=model, provider=provider, extra=attributes),
        )

    # ---- chat ------------------------------------------------------------

    def _message(self, name: str, text: str, attributes: Mapping[str, AttributeValue]) -> None:
        with self._span(name, {"gen_ai.operation.name": name, "message": text, **attributes}):
            pass

    def user_message(self, text: str, **attributes: AttributeValue) -> None:
        """Record what the user typed. Call it when the message arrives."""
        self._message("user_message", text, attributes)

    def assistant_message(self, text: str, **attributes: AttributeValue) -> None:
        """Record the reply sent to the user.

        Optional: without it, the last LLM output in the turn is used as the reply.
        Useful when the agent post-processes the LLM output before sending it.
        """
        self._message("assistant_message", text, attributes)

    def tool(
        self, name: str, *, arguments: Optional[str] = None, **attributes: AttributeValue
    ) -> Any:
        """A tool/function call. Yields a :class:`ToolSpan` (``set_result``, ``set_error``)."""
        extra: dict[str, Optional[AttributeValue]] = {
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.arguments": arguments,
            **attributes,
        }
        return self._span(
            f"execute_tool {name}",
            _component_attributes("execute_tool", model=None, provider=None, extra=extra),
            ToolSpan,
        )

    def retrieval(
        self,
        *,
        source: Optional[str] = None,
        query: Optional[str] = None,
        **attributes: AttributeValue,
    ) -> Any:
        """A knowledge-base / RAG lookup. Yields a :class:`RetrievalSpan` (``set_documents``)."""
        extra: dict[str, Optional[AttributeValue]] = {
            "retrieval.source": source,
            "retrieval.query": query,
            **attributes,
        }
        return self._span(
            "retrieval",
            _component_attributes("retrieval", model=None, provider=None, extra=extra),
            RetrievalSpan,
        )

    def span(self, name: str, **attributes: AttributeValue) -> Any:
        """Any other span you want attached to this call (tool calls, retrieval, ...)."""
        return self._span(name, attributes)


# ---------------------------------------------------------------------------
# Session open/close
# ---------------------------------------------------------------------------


def _session_payload(
    transport: str, agent_id: Optional[str], evaluator_result_id: Optional[str]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"transport": transport}
    if agent_id:
        payload["agent_id"] = str(agent_id)
    if evaluator_result_id:
        payload["evaluator_result_id"] = str(evaluator_result_id)
    return payload


def _call_from_correlation(
    *,
    channel: Optional[str],
    handshake: Optional[Mapping[str, Any]],
    call_short_id: Optional[str],
    sip_headers: Optional[Mapping[str, Any]],
    headers: Optional[Mapping[str, Any]],
    transport: str,
    agent_id: Optional[str],
    workspace_id: Optional[str],
    evaluator_result_id: Optional[str],
    attributes: Optional[Mapping[str, str]],
) -> tuple[Optional[CallTrace], Optional[str]]:
    """A call id the platform already gave us (handshake, SIP or HTTP headers).

    Returns ``(call, otlp_endpoint_hint)``, or ``(None, None)`` to mint a new session.
    """
    parsed = parse_trace_handshake(handshake) if handshake else None
    if parsed:
        otel_block = parsed.get("otel_correlation") or {}
        return (
            CallTrace(
                call_short_id=parsed["call_short_id"],
                enabled=True,
                workspace_id=str(parsed.get("workspace_id") or workspace_id or "") or None,
                agent_id=str(parsed.get("agent_id") or agent_id or "") or None,
                transport=parsed.get("transport") or transport,
                evaluator_result_id=_run_id_from(otel_block, evaluator_result_id),
                trace_id=parsed.get("trace_id"),
                extra_attributes=attributes,
                channel=channel,
            ),
            otel_block.get("otlp_endpoint"),
        )

    found = call_short_id or extract_call_short_id(sip_headers=sip_headers, webhook_params=headers)
    if found:
        run_id = evaluator_result_id
        if not run_id and headers:
            run_id = next(
                (str(v) for k, v in headers.items() if k.lower() == "x-efficientai-run-id"),
                None,
            )
        return (
            CallTrace(
                call_short_id=found,
                enabled=True,
                workspace_id=workspace_id,
                agent_id=agent_id,
                transport=transport,
                evaluator_result_id=run_id,
                extra_attributes=attributes,
                channel=channel,
            ),
            None,
        )
    return None, None


def _call_from_session(
    body: Any,
    *,
    channel: Optional[str],
    transport: str,
    agent_id: Optional[str],
    workspace_id: Optional[str],
    attributes: Optional[Mapping[str, str]],
) -> tuple[CallTrace, Optional[str]]:
    if not isinstance(body, dict) or not body.get("call_short_id"):
        raise TraceSessionError(f"Unexpected session response: {body!r}")
    otel_block = body.get("otel_correlation") or {}
    return (
        CallTrace(
            call_short_id=str(body["call_short_id"]),
            enabled=True,
            workspace_id=str(body.get("workspace_id") or workspace_id or "") or None,
            agent_id=agent_id,
            transport=body.get("transport") or transport,
            evaluator_result_id=_run_id_from(otel_block),
            trace_id=str(body["trace_id"]) if body.get("trace_id") else None,
            owns_session=True,
            extra_attributes=attributes,
            channel=channel,
        ),
        otel_block.get("otlp_endpoint"),
    )


def _as_session_error(exc: EfficientAIError) -> TraceSessionError:
    if isinstance(exc, TraceSessionError):
        return exc
    return TraceSessionError(str(exc), status_code=getattr(exc, "status_code", None))


def _disabled(error: str, transport: str) -> CallTrace:
    return CallTrace(call_short_id=None, enabled=False, transport=transport, error=error)


def _check_transport(transport: str) -> str:
    value = (transport or "custom").lower()
    if value not in VALID_TRANSPORTS:
        raise ValueError(f"transport must be one of {sorted(VALID_TRANSPORTS)}")
    return value


class _TraceResourceBase:
    def __init__(self, client: Any, *, service_name: str = "efficientai-agent") -> None:
        self._client = client
        self.service_name = service_name

    def _start_export(self, call: CallTrace, endpoint_hint: Optional[str]) -> None:
        if not call.enabled:
            return
        config = self._client._config
        ok = otel.ensure_export_pipeline(
            endpoint=resolve_otlp_endpoint(endpoint_hint, api_base_url=config.base_url),
            api_key=config.api_key,
            workspace_id=call.workspace_id or config.workspace_id,
            service_name=self.service_name,
        )
        if not ok and not otel.OTEL_AVAILABLE:
            logger.warning(
                "EfficientAI: OpenTelemetry is not installed, so spans for call %s won't be "
                "exported. Install with: pip install 'efficientai-sdk[otel]'",
                call.call_short_id,
            )

    def instrument(self, *, console_export: bool = False) -> bool:
        """Export this process's OpenTelemetry spans to EfficientAI.

        For stacks that already create their own spans. Spans are tagged with the call
        active in the current context (see :meth:`CallTrace.activate`).
        """
        config = self._client._config
        return otel.ensure_export_pipeline(
            endpoint=resolve_otlp_endpoint(api_base_url=config.base_url),
            api_key=config.api_key,
            workspace_id=config.workspace_id,
            service_name=self.service_name,
            console_export=console_export,
        )


class TraceResource(_TraceResourceBase):
    """``EfficientAI().trace``: tracing for synchronous code."""

    _client: SyncAPIClient

    def start_session(
        self,
        *,
        transport: str = "custom",
        agent_id: Optional[str] = None,
        evaluator_result_id: Optional[str] = None,
        handshake: Optional[Mapping[str, Any]] = None,
        call_short_id: Optional[str] = None,
        sip_headers: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, Any]] = None,
        attributes: Optional[Mapping[str, str]] = None,
        channel: Optional[str] = None,
        strict: bool = False,
    ) -> CallTrace:
        """Open a call and activate it in the current context. Pair with :meth:`end_session`.

        Reuses the platform's call id when one is supplied (``handshake``,
        ``call_short_id``, ``sip_headers`` or ``headers``); otherwise opens a new session.
        Pass ``channel="chat"`` for text agents so turns are built from messages, tool
        calls and LLM output instead of STT/TTS.
        """
        transport = _check_transport(transport)
        call, hint = _call_from_correlation(
            channel=channel,
            handshake=handshake,
            call_short_id=call_short_id,
            sip_headers=sip_headers,
            headers=headers,
            transport=transport,
            agent_id=agent_id,
            workspace_id=self._client.workspace_id,
            evaluator_result_id=evaluator_result_id,
            attributes=attributes,
        )
        if call is None:
            try:
                body = self._client.request(
                    "POST",
                    SESSIONS_PATH,
                    json=_session_payload(transport, agent_id, evaluator_result_id),
                )
                call, hint = _call_from_session(
                    body,
                    channel=channel,
                    transport=transport,
                    agent_id=agent_id,
                    workspace_id=self._client.workspace_id,
                    attributes=attributes,
                )
            except EfficientAIError as exc:
                if strict:
                    raise _as_session_error(exc) from exc
                logger.warning("EfficientAI trace session failed, tracing disabled: %s", exc)
                return _disabled(str(exc), transport)
        self._start_export(call, hint)
        call._enter_context()
        return call

    def end_session(self, call: CallTrace, *, close: Optional[bool] = None) -> None:
        """Flush spans and close the session. Never raises.

        ``close=None`` closes only sessions this SDK opened; platform-owned test calls
        are closed by the platform.
        """
        call._exit_context()
        if not call.enabled:
            return
        otel.flush_efficientai_tracing()
        if not (call.owns_session if close is None else close):
            return
        try:
            self._client.request("POST", f"{SESSIONS_PATH}/{call.call_short_id}/close")
        except EfficientAIError as exc:
            logger.warning("EfficientAI trace close failed: %s", exc)

    @contextmanager
    def session(self, **kwargs: Any) -> Iterator[CallTrace]:
        """``with client.trace.session(...) as call:``. Same arguments as :meth:`start_session`."""
        call = self.start_session(**kwargs)
        try:
            yield call
        finally:
            self.end_session(call)


class _AsyncSession:
    def __init__(self, resource: AsyncTraceResource, kwargs: dict[str, Any]) -> None:
        self._resource = resource
        self._kwargs = kwargs
        self._call: Optional[CallTrace] = None

    async def __aenter__(self) -> CallTrace:
        self._call = await self._resource.start_session(**self._kwargs)
        return self._call

    async def __aexit__(self, *exc_info: object) -> None:
        if self._call is not None:
            await self._resource.end_session(self._call)


class AsyncTraceResource(_TraceResourceBase):
    """``AsyncEfficientAI().trace``: tracing for asyncio code."""

    _client: AsyncAPIClient

    async def start_session(
        self,
        *,
        transport: str = "custom",
        agent_id: Optional[str] = None,
        evaluator_result_id: Optional[str] = None,
        handshake: Optional[Mapping[str, Any]] = None,
        call_short_id: Optional[str] = None,
        sip_headers: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, Any]] = None,
        attributes: Optional[Mapping[str, str]] = None,
        channel: Optional[str] = None,
        strict: bool = False,
    ) -> CallTrace:
        """Async version of :meth:`TraceResource.start_session`.

        The call is activated in the calling task's context, so tasks it creates
        afterwards inherit it.
        """
        transport = _check_transport(transport)
        call, hint = _call_from_correlation(
            channel=channel,
            handshake=handshake,
            call_short_id=call_short_id,
            sip_headers=sip_headers,
            headers=headers,
            transport=transport,
            agent_id=agent_id,
            workspace_id=self._client.workspace_id,
            evaluator_result_id=evaluator_result_id,
            attributes=attributes,
        )
        if call is None:
            try:
                body = await self._client.request(
                    "POST",
                    SESSIONS_PATH,
                    json=_session_payload(transport, agent_id, evaluator_result_id),
                )
                call, hint = _call_from_session(
                    body,
                    channel=channel,
                    transport=transport,
                    agent_id=agent_id,
                    workspace_id=self._client.workspace_id,
                    attributes=attributes,
                )
            except EfficientAIError as exc:
                if strict:
                    raise _as_session_error(exc) from exc
                logger.warning("EfficientAI trace session failed, tracing disabled: %s", exc)
                return _disabled(str(exc), transport)
        self._start_export(call, hint)
        call._enter_context()
        return call

    async def end_session(self, call: CallTrace, *, close: Optional[bool] = None) -> None:
        """Async version of :meth:`TraceResource.end_session`."""
        call._exit_context()
        if not call.enabled:
            return
        # force_flush blocks on network I/O; keep it off the event loop.
        await asyncio.get_running_loop().run_in_executor(None, otel.flush_efficientai_tracing)
        if not (call.owns_session if close is None else close):
            return
        try:
            await self._client.request("POST", f"{SESSIONS_PATH}/{call.call_short_id}/close")
        except EfficientAIError as exc:
            logger.warning("EfficientAI trace close failed: %s", exc)

    def session(self, **kwargs: Any) -> _AsyncSession:
        """``async with client.trace.session(...) as call:``. Same arguments as
        :meth:`start_session`."""
        return _AsyncSession(self, kwargs)
