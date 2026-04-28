"""Regression tests for qualitative voice service config patching."""

from app.services.audio.qualitative_voice_service import _patch_none_vocab_size


def test_patch_none_vocab_size_patches_nested_entries():
    source = {
        "vocab_size": None,
        "inner": {
            "vocab_size": None,
            "keep": 123,
            "none_field": None,
        },
        "items": [
            {"vocab_size": None},
            {"vocab_size": 777},
            {"something_else": None},
        ],
    }

    patched = _patch_none_vocab_size(source)

    assert patched["vocab_size"] == 32
    assert patched["inner"]["vocab_size"] == 32
    assert patched["inner"]["keep"] == 123
    assert patched["inner"]["none_field"] is None
    assert patched["items"][0]["vocab_size"] == 32
    assert patched["items"][1]["vocab_size"] == 777
    assert patched["items"][2]["something_else"] is None


def test_patch_none_vocab_size_does_not_mutate_input():
    source = {"vocab_size": None, "nested": {"vocab_size": None}}
    patched = _patch_none_vocab_size(source)

    assert source["vocab_size"] is None
    assert source["nested"]["vocab_size"] is None
    assert patched["vocab_size"] == 32
    assert patched["nested"]["vocab_size"] == 32
