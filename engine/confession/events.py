"""In-process asyncio event bus with a bounded replay buffer.

The auditor publishes typed `Event`s at every step; the FastAPI WebSocket subscribes
and streams them to the dashboard. A new subscriber first receives the ring buffer (the
last N events) so a freshly-opened dashboard shows recent history, then live events.

All state mutation happens on the event loop; publish/subscribe are safe to call from
any coroutine running on that loop.
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .models import Event, EventType


class EventBus:
    """Fan-out bus: one publisher, many subscribers, with a bounded history buffer."""

    def __init__(self, buffer_size: int = 500) -> None:
        self._buffer: deque[Event] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue[Event]] = set()

    # -- history ------------------------------------------------------------

    def history(self) -> list[Event]:
        """Snapshot of the ring buffer (oldest first)."""
        return list(self._buffer)

    def buffer_size(self) -> int:
        return self._buffer.maxlen or 0

    # -- publish ------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        """Append to the ring buffer and fan out to every current subscriber."""
        self._buffer.append(event)
        for queue in list(self._subscribers):
            # Queues are unbounded, so this never blocks or drops.
            queue.put_nowait(event)

    async def emit(self, type: EventType, **payload: Any) -> Event:
        """Convenience wrapper: build a timestamped `Event` and publish it."""
        event = Event(type=type, payload=payload)
        await self.publish(event)
        return event

    # -- subscribe ----------------------------------------------------------

    @asynccontextmanager
    async def subscribe(self, replay_history: bool = True) -> AsyncIterator[AsyncIterator[Event]]:
        """Async context manager yielding an async iterator of events.

        On entry the subscriber's queue is pre-loaded with the current ring buffer (when
        `replay_history`), so iteration begins with recent history and continues live.
        The subscription is always removed on exit, even if the consumer errors.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        if replay_history:
            for event in self._buffer:
                queue.put_nowait(event)
        self._subscribers.add(queue)

        async def _iterator() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield _iterator()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
