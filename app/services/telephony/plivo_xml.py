"""Plivo XML builders for webhook responses."""

def _get_plivoxml():
    try:
        from plivo import plivoxml
    except ImportError as exc:  # pragma: no cover - environment-dependent optional dependency
        raise ValueError(
            "Plivo SDK is not installed. Install it with `pip install -e .` or `pip install plivo`."
        ) from exc
    return plivoxml


def speak_and_hangup(message: str) -> str:
    """Build XML to speak a message and hang up."""
    plivoxml = _get_plivoxml()
    response = plivoxml.ResponseElement()
    response.add(plivoxml.SpeakElement(message))
    response.add(plivoxml.HangupElement())
    return response.to_string()


def dial_number(to_number: str, caller_id: str) -> str:
    """Build XML to dial a target number with caller ID."""
    plivoxml = _get_plivoxml()
    response = plivoxml.ResponseElement()
    dial = plivoxml.DialElement(callerId=caller_id)
    dial.add(plivoxml.NumberElement(to_number))
    response.add(dial)
    return response.to_string()


def reject_call(reason: str = "This number is not available.") -> str:
    """Build XML to reject a call with a message."""
    plivoxml = _get_plivoxml()
    response = plivoxml.ResponseElement()
    response.add(plivoxml.SpeakElement(reason))
    response.add(plivoxml.HangupElement())
    return response.to_string()
