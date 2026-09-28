"""Thread/async-safe EfficientAI correlation attributes for active pipeline spans."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict

_correlation_attrs: ContextVar[Dict[str, Any]] = ContextVar("efficientai_correlation_attrs", default={})


def set_correlation_attributes(attrs: Dict[str, Any]) -> None:
    _correlation_attrs.set(dict(attrs))


def get_correlation_attributes() -> Dict[str, Any]:
    return dict(_correlation_attrs.get())


def clear_correlation_attributes() -> None:
    _correlation_attrs.set({})
