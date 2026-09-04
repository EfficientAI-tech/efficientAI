"""Tests for Plivo XML response builders."""

import pytest

from app.services.telephony.plivo_xml import dial_number, reject_call, speak_and_hangup

pytest.importorskip("plivo")


def test_dial_number_includes_destination_and_caller_id():
    xml = dial_number("+14155559999", "+14155551234")

    assert "+14155559999" in xml
    assert "+14155551234" in xml
    assert "callerId" in xml or "caller_id" in xml


def test_speak_and_hangup_returns_xml():
    xml = speak_and_hangup("Hello")

    assert "Hello" in xml
    assert "Hangup" in xml


def test_reject_call_returns_xml():
    xml = reject_call("Unavailable")

    assert "Unavailable" in xml
    assert "Hangup" in xml
