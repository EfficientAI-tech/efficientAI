"""Poll a run until it reaches a terminal status."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from efficientai_sdk._exceptions import APITimeoutError

T = TypeVar("T")


def _timeout(timeout: float) -> APITimeoutError:
    return APITimeoutError(f"Timed out after {timeout:g}s waiting for the run to finish.")


def poll_sync(
    current: T,
    fetch: Callable[[float], T],
    done: Callable[[T], bool],
    *,
    timeout: float,
    interval: float,
) -> T:
    deadline = time.monotonic() + timeout
    while not done(current):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout(timeout)
        time.sleep(min(interval, remaining) if interval > 0 else 0)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout(timeout)
        current = fetch(remaining)
    return current


async def poll_async(
    current: T,
    fetch: Callable[[float], Awaitable[T]],
    done: Callable[[T], bool],
    *,
    timeout: float,
    interval: float,
) -> T:
    deadline = time.monotonic() + timeout
    while not done(current):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout(timeout)
        await asyncio.sleep(min(interval, remaining) if interval > 0 else 0)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout(timeout)
        current = await fetch(remaining)
    return current
