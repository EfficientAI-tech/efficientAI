"""Backward-compatible re-exports for platform outbound pool helpers."""

from app.services.telephony.platform_outbound_pool import (
    PlatformOutboundPoolEntry,
    acquire_pool_slot,
    configured_outbound_pool,
    configured_outbound_pool_numbers,
    get_org_pool_usage,
    outbound_pool_api_payload,
    pool_max_concurrent_per_org,
    release_pool_slot,
    resolve_outbound_from_number,
)

__all__ = [
    "PlatformOutboundPoolEntry",
    "acquire_pool_slot",
    "configured_outbound_pool",
    "configured_outbound_pool_numbers",
    "get_org_pool_usage",
    "outbound_pool_api_payload",
    "pool_max_concurrent_per_org",
    "release_pool_slot",
    "resolve_outbound_from_number",
]
