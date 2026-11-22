"""Per-call correlation context.

Each call's ``efficientai.*`` attributes live in a :class:`contextvars.ContextVar`, so
concurrent calls handled by one process (separate asyncio tasks or threads) each stamp
their own call id onto their spans. Asyncio tasks inherit the context they were created
in, so everything a call handler starts after the session opens is tagged correctly.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Optional

__all__ = [
    "call_attributes",
    "get_call_attributes",
    "reset_call_attributes",
    "set_call_attributes",
]

_CALL_ATTRIBUTES: contextvars.ContextVar[Optional[dict[str, str]]] = contextvars.ContextVar(
    "efficientai_call_attributes", default=None
)


def get_call_attributes() -> Optional[dict[str, str]]:
    """Correlation attributes of the call active in this context, if any."""
    return _CALL_ATTRIBUTES.get()


def set_call_attributes(
    attributes: Mapping[str, str],
) -> contextvars.Token[Optional[dict[str, str]]]:
    """Make ``attributes`` the active call for this context. Returns a reset token."""
    return _CALL_ATTRIBUTES.set(dict(attributes))


def reset_call_attributes(token: contextvars.Token[Optional[dict[str, str]]]) -> None:
    """Undo :func:`set_call_attributes`. Safe to call from a different context."""
    try:
        _CALL_ATTRIBUTES.reset(token)
    except ValueError:
        # Token created in another context (e.g. session opened in one callback and
        # closed in another). That context ends on its own; clear ours instead.
        _CALL_ATTRIBUTES.set(None)


@contextmanager
def call_attributes(attributes: Mapping[str, str]) -> Iterator[None]:
    """Activate ``attributes`` for the duration of the ``with`` block."""
    token = set_call_attributes(attributes)
    try:
        yield
    finally:
        reset_call_attributes(token)
