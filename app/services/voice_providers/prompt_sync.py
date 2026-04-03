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
    decrypted_key = decrypt_api_key(integration.api_key)
    provider_class = get_voice_provider(
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )

    platform_val = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else integration.platform
    )
    if platform_val.lower() == "vapi":
        provider = provider_class(api_key=decrypted_key, public_key=integration.public_key)
    else:
        provider = provider_class(api_key=decrypted_key)

    prompt = provider.extract_agent_prompt(agent.voice_ai_agent_id)

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
