"""
Example: Pipecat inbound phone bot with EfficientAI Tier 2 OTLP tracing.

EfficientAI synthetic phone tests dial your number with SIP header
``X-VH-EfficientAI-Call-Short-Id`` (6 digits). Read it from your carrier
webhook and pass into ``configure_pipecat_tracing()`` — STT/LLM/TTS spans
export automatically to Test Insights.

Requires: pip install efficientai[otel]
"""

from __future__ import annotations

import os

from efficientai.integrations.efficientai_traces import (
    configure_pipecat_tracing,
    extract_call_short_id,
)
from efficientai.pipeline.task import PipelineTask

# One-time env (from Test Insights → Pipecat setup):
# EFFICIENTAI_OTLP_ENDPOINT=https://<host>/api/v1/observability/traces
# EFFICIENTAI_API_KEY=<your-api-key>


def sip_headers_from_exotel_webhook(form: dict) -> dict:
    """Map Exotel / generic carrier fields to SIP-style header names."""
    headers = {}
    for key in (
        "SipHeader_X-VH-EfficientAI-Call-Short-Id",
        "SipHeader_X-PH-EfficientAI-Call-Short-Id",
        "CustomField",
    ):
        if form.get(key):
            headers[key] = form[key]
    if form.get("CallSid"):
        headers["call_sid"] = form["CallSid"]
    return headers


async def run_inbound_call(pipeline, telephony_payload: dict) -> PipelineTask:
    """
    Call from your telephony webhook handler after the inbound leg connects.

    telephony_payload: dict from Exotel/Plivo/Vobiz answer URL (form or JSON).
    """
    sip_headers = sip_headers_from_exotel_webhook(telephony_payload)
    call_short_id = extract_call_short_id(
        sip_headers=sip_headers,
        webhook_params=telephony_payload,
    )
    if not call_short_id:
        raise ValueError(
            "Missing EfficientAI call_short_id — ensure your SIP trunk forwards "
            "X-VH-EfficientAI-Call-Short-Id from the outbound INVITE."
        )

    tracing_kwargs = configure_pipecat_tracing(
        call_short_id=call_short_id,
        sip_headers=sip_headers,
        webhook_params=telephony_payload,
        service_name=os.getenv("EFFICIENTAI_SERVICE_NAME", "pipecat-agent"),
    )

    return PipelineTask(
        pipeline,
        **tracing_kwargs,
    )
