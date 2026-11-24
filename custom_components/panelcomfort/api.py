"""Shared request coordination for PanelComfort entities."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


_STATUS_CACHE_SECONDS = 1.5
# A failed status request is remembered for a little under one 30 s poll cycle, so
# when the TV is off the other entities polled in the same cycle fail at once
# instead of each waiting behind the lock for its own connect timeout.
_FAILURE_CACHE_SECONDS = 25.0
_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_STATUS_FAILURES: dict[str, tuple[float, BaseException]] = {}
_STATUS_LOCKS: dict[str, asyncio.Lock] = {}
_CONFIG_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(locks: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


def async_config_lock(entry_id: str) -> asyncio.Lock:
    """Return a per-device lock shared by every HA entity that writes settings."""
    return _lock_for(_CONFIG_LOCKS, entry_id)


def invalidate_status(entry_id: str) -> None:
    _STATUS_CACHE.pop(entry_id, None)
    _STATUS_FAILURES.pop(entry_id, None)


def _recent_failure(entry_id: str, now: float) -> BaseException | None:
    failure = _STATUS_FAILURES.get(entry_id)
    if failure and now - failure[0] < _FAILURE_CACHE_SECONDS:
        return failure[1]
    return None


async def async_cached_status(
    entry_id: str,
    request: Callable[[], Awaitable[dict]],
    *,
    force: bool = False,
) -> dict:
    """Collapse simultaneous entity polls into one status request per device."""
    now = time.monotonic()
    cached = _STATUS_CACHE.get(entry_id)
    if not force and cached and now - cached[0] < _STATUS_CACHE_SECONDS:
        return cached[1]
    if not force and (failure := _recent_failure(entry_id, now)) is not None:
        raise failure

    async with _lock_for(_STATUS_LOCKS, entry_id):
        now = time.monotonic()
        cached = _STATUS_CACHE.get(entry_id)
        if not force and cached and now - cached[0] < _STATUS_CACHE_SECONDS:
            return cached[1]
        if not force and (failure := _recent_failure(entry_id, now)) is not None:
            raise failure
        try:
            payload = await request()
        except Exception as err:
            _STATUS_FAILURES[entry_id] = (time.monotonic(), err)
            raise
        _STATUS_FAILURES.pop(entry_id, None)
        _STATUS_CACHE[entry_id] = (time.monotonic(), payload)
        return payload
