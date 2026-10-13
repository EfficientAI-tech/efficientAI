from app.services.imported_agent_constants import merge_imported_agent_tags_on_update

IMPORT_ID = "__call_import__:abc-123"
PROVIDER = "__agent_provider_prompt__:integ:agent-1"


def test_merge_keeps_link_tags_when_client_sends_only_imported_agent():
    existing = ["__imported_agent__", PROVIDER, IMPORT_ID, "my-tag"]
    merged = merge_imported_agent_tags_on_update(existing, ["__imported_agent__"])
    assert IMPORT_ID in merged
    assert PROVIDER in merged
    assert "__imported_agent__" in merged
    assert "my-tag" in merged


def test_merge_preserves_user_tags_from_incoming():
    existing = ["__imported_agent__", IMPORT_ID]
    merged = merge_imported_agent_tags_on_update(existing, ["__imported_agent__", "new-user"])
    assert merged == ["__imported_agent__", IMPORT_ID, "new-user"]


def test_merge_clears_user_tags_when_client_sends_link_tags_only():
    existing = ["__imported_agent__", PROVIDER, IMPORT_ID, "my-tag"]
    merged = merge_imported_agent_tags_on_update(
        existing, ["__imported_agent__", PROVIDER, IMPORT_ID]
    )
    assert "my-tag" not in merged
    assert IMPORT_ID in merged
