"""
Shared helper for syncing the provider prompt into the local Agent row.

Used by agent create/update routes and the manual sync endpoint.
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.encryption import decrypt_api_key
from app.models.database import Agent, Integration
from app.services.voice_providers import get_voice_provider


def build_voice_provider_from_integration(
    integration: Integration,
    *,
    decrypted_key: Optional[str] = None,
):
    """Instantiate a voice provider for an org integration row."""
    if decrypted_key is None:
        decrypted_key = decrypt_api_key(integration.api_key)
    platform_val = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )
    platform_key = str(platform_val).lower()
    provider_class = get_voice_provider(platform_val)
    kwargs: dict = {"api_key": decrypted_key}
    if platform_key == "vapi":
        kwargs["public_key"] = integration.public_key
    elif platform_key == "elevenlabs" and getattr(integration, "api_base_url", None):
        kwargs["base_url"] = integration.api_base_url
    return provider_class(**kwargs)


def _build_voice_provider(integration: Integration):
    return build_voice_provider_from_integration(integration)


def fetch_provider_prompt(
    integration: Integration,
    voice_ai_agent_id: str,
    *,
    agent_channel: Optional[str] = None,
) -> Optional[str]:
    """Fetch a provider agent prompt without persisting it."""
    provider = _build_voice_provider(integration)
    return provider.extract_agent_prompt(
        voice_ai_agent_id,
        agent_channel=agent_channel,
    )


def sync_provider_prompt(
    agent: Agent,
    integration: Integration,
    db: Session,
) -> Optional[str]:
    """
    Fetch the system prompt from the voice provider and persist it on the
    agent row.

    Returns the fetched prompt string, or None if extraction fails.
    Callers that want best-effort semantics should wrap this in try/except.
    """
    platform_val = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )
    medium = getattr(agent, "call_medium", None)
    agent_channel = "chat" if str(medium or "").lower() == "chat" else None
    prompt = fetch_provider_prompt(
        integration,
        agent.voice_ai_agent_id,
        agent_channel=agent_channel,
    )

    if prompt is not None:
        agent.provider_prompt = prompt
        agent.provider_prompt_synced_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"[PromptSync] Synced provider prompt for agent {agent.name} "
            f"({len(prompt)} chars)"
        )
    else:
        logger.warning(
            f"[PromptSync] No prompt returned for agent {agent.name} "
            f"on {platform_val}"
        )

    return prompt
