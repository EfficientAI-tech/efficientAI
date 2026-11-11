"""Per-LLM-call memo for catalog lookups.

One ``generate_response`` call used to read the same ``organizations`` row
three times (key resolution, routing, gateway kwargs) and could resolve the
same credential twice. Inside ``llm_call_scope()`` each lookup runs once per
call; outside a scope, ``scoped`` just calls the loader.

The scope lives in a ``ContextVar``, so it is per thread and per asyncio task
and never leaks between concurrent calls.
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, Hashable, Iterator, Optional

_scope: ContextVar[Optional[Dict[Hashable, Any]]] = ContextVar(
    "llm_call_scope", default=None
)


@contextmanager
def llm_call_scope() -> Iterator[None]:
    """Memoize catalog lookups for the duration of one LLM call.

    Nested scopes reuse the outer one.
    """
    if _scope.get() is not None:
        yield
        return
    token = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(token)


def scoped(key: Hashable, loader: Callable[[], Any]) -> Any:
    memo = _scope.get()
    if memo is None:
        return loader()
    if key in memo:
        return memo[key]
    value = loader()
    memo[key] = value
    return value


def with_llm_call_scope(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run ``fn`` inside ``llm_call_scope()`` (for plain, non-generator calls)."""

    @functools.wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        with llm_call_scope():
            return fn(*args, **kwargs)

    return _wrapped
