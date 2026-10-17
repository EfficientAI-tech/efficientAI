"""Auto-link platform imports to imported-agent prompt partials."""

from types import SimpleNamespace
from uuid import uuid4

from app.services.platform_import_imported_agent import (
    _single_voice_agent_ref,
    imported_agent_partial_name,
    linked_partial_id,
    platform_voice_agent_link_tag,
)


def test_single_voice_agent_ref_from_agents_array():
    call_import = SimpleNamespace(
        source_format="platform",
        platform_filters={
            "agents": [{"id": "agent-1", "name": "Ola outbound", "medium": "voice"}],
            "agent_ids": ["agent-1"],
        },
    )
    assert _single_voice_agent_ref(call_import) == ("agent-1", "Ola outbound")


def test_single_voice_agent_ref_requires_one_agent():
    call_import = SimpleNamespace(
        source_format="platform",
        platform_filters={"agent_ids": ["a", "b"]},
    )
    assert _single_voice_agent_ref(call_import) is None


def test_linked_partial_id_from_filters():
    partial_id = uuid4()
    call_import = SimpleNamespace(
        platform_filters={"imported_agent_partial_id": str(partial_id)},
    )
    assert linked_partial_id(call_import) == partial_id


def test_platform_voice_agent_link_tag():
    integration_id = uuid4()
    assert (
        platform_voice_agent_link_tag(integration_id, "agent-1")
        == f"__agent_provider_prompt__:{integration_id}:agent-1"
    )


def test_imported_agent_partial_name_includes_import_batch():
    import_id = uuid4()
    call_import = SimpleNamespace(
        id=import_id,
        original_filename="ElevenLabs 1 Jan 2026 – 7 Jan 2026",
    )
    assert imported_agent_partial_name("Ola outbound", call_import) == (
        "Ola outbound · ElevenLabs 1 Jan 2026 – 7 Jan 2026"
    )
