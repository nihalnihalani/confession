"""Unit tests for the event bus — ring buffer bounds, ordering, and replay-on-subscribe."""

import asyncio

import pytest

from confession.events import EventBus
from confession.models import Event, EventType


def test_ring_buffer_is_bounded():
    async def scenario():
        bus = EventBus(buffer_size=5)
        for i in range(12):
            await bus.emit(EventType.AUDIT_PROGRESS, i=i)
        history = bus.history()
        assert len(history) == 5
        # only the last 5 survive, in order
        assert [e.payload["i"] for e in history] == [7, 8, 9, 10, 11]

    asyncio.run(scenario())


def test_history_preserves_publish_order():
    async def scenario():
        bus = EventBus(buffer_size=100)
        kinds = [
            EventType.CLAIM_SUBMITTED,
            EventType.AUDIT_STARTED,
            EventType.VERDICT_REACHED,
        ]
        for kind in kinds:
            await bus.emit(kind)
        assert [e.type for e in bus.history()] == kinds

    asyncio.run(scenario())


def test_subscriber_replays_buffer_then_receives_live():
    async def scenario():
        bus = EventBus(buffer_size=100)
        await bus.emit(EventType.CLAIM_SUBMITTED, n=1)
        await bus.emit(EventType.AUDIT_STARTED, n=2)

        received = []
        async with bus.subscribe(replay_history=True) as stream:
            # two buffered events are already queued; drain them
            for _ in range(2):
                received.append(await asyncio.wait_for(stream.__anext__(), timeout=1))
            # a live event arrives after subscription
            await bus.emit(EventType.VERDICT_REACHED, n=3)
            received.append(await asyncio.wait_for(stream.__anext__(), timeout=1))

        assert [e.payload["n"] for e in received] == [1, 2, 3]

    asyncio.run(scenario())


def test_subscribe_without_replay_only_sees_live():
    async def scenario():
        bus = EventBus(buffer_size=100)
        await bus.emit(EventType.CLAIM_SUBMITTED, n=1)
        async with bus.subscribe(replay_history=False) as stream:
            await bus.emit(EventType.VERDICT_REACHED, n=2)
            event = await asyncio.wait_for(stream.__anext__(), timeout=1)
            assert event.payload["n"] == 2

    asyncio.run(scenario())


def test_unsubscribe_on_exit():
    async def scenario():
        bus = EventBus(buffer_size=10)
        async with bus.subscribe() as _stream:
            assert bus.subscriber_count == 1
        assert bus.subscriber_count == 0

    asyncio.run(scenario())


def test_every_event_is_timestamped():
    async def scenario():
        bus = EventBus()
        event = await bus.emit(EventType.RECEIPTS_UPDATED, ok=True)
        assert event.timestamp is not None
        assert event.payload == {"ok": True}

    asyncio.run(scenario())


def test_sink_persists_before_delivery_and_restore_does_not_duplicate():
    async def scenario():
        persisted = []

        async def sink(event):
            persisted.append(event)

        bus = EventBus(sink=sink)
        event = await bus.emit(EventType.CLAIM_SUBMITTED, claim_id="c1")
        assert persisted == [event]

        restored = Event(type=EventType.AUDIT_STARTED, payload={"claim_id": "c0"})
        bus.restore([restored])
        assert bus.history() == [restored]
        assert persisted == [event]

    asyncio.run(scenario())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
