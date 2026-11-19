"""Bounded, ephemeral intake on the caller's asyncio loop; no model or storage policy."""

import asyncio
import math
from typing import Literal

from vtuber.contracts.events import new_id, utc_now
from vtuber.contracts.perception import Perception, PerceptionBatch
from vtuber.contracts.trace import TraceSink, emit_trace


class PerceptionQueueFull(RuntimeError):
    """Meaningful input was not accepted; the adapter may retry it."""


class PerceptionBus:
    def __init__(self, *, live_gap: float = .30, text_gap: float = 1.20,
                 max_window: float | None = 3.0, max_pending: int = 256,
                 trace: TraceSink | None = None) -> None:
        timings = (live_gap, text_gap) if max_window is None else (live_gap, text_gap, max_window)
        for value in timings:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('Perception timing must be finite and nonnegative')
        if type(max_pending) is not int or max_pending < 1:
            raise ValueError('max_pending must be a positive integer')
        self.live_gap, self.text_gap = live_gap, text_gap
        self.max_window, self.max_pending = max_window, max_pending
        self._pending: list[tuple[float, Perception]] = []
        self._changed = asyncio.Condition()
        self._draining = asyncio.Lock()
        self._closed = False
        self._trace = trace
        self._stats = dict(published=0, duplicate=0, noise_dropped=0, overflow=0, batches=0)

    @property
    def stats(self) -> dict[str, int]:
        return self._stats.copy()

    async def publish(self, item: Perception) -> bool:
        async with self._changed:
            if self._closed:
                raise RuntimeError('Perception Bus is closed')
            if not isinstance(item, Perception):
                raise ValueError('Expected a Perception')
            for _, pending in self._pending:
                if pending.perception_id == item.perception_id:
                    if pending != item:
                        raise ValueError('Conflicting pending perception ID')
                    self._stats['duplicate'] += 1
                    return False
            if item.delivery == 'noise':
                self._stats['noise_dropped'] += 1
                return False
            if len(self._pending) >= self.max_pending:
                self._stats['overflow'] += 1
                raise PerceptionQueueFull('Perception queue is full; input was not accepted')
            arrived = asyncio.get_running_loop().time()
            self._pending.append((arrived, item))
            self._stats['published'] += 1
            self._changed.notify_all()
            emit_trace(self._trace, 'perception.enqueued', item.perception_id,
                       perception_id=item.perception_id, arrived=arrived, occurred_at=item.occurred_at,
                       queue_size=len(self._pending))
            return True

    async def drain(self) -> PerceptionBatch | None:
        async with self._draining, self._changed:
            while not self._pending:
                if self._closed:
                    return None
                await self._changed.wait()
            return await self._settle()

    def drain_nowait(self) -> PerceptionBatch | None:
        if self._draining.locked():
            raise RuntimeError('Perception Bus already has an active consumer')
        if self._pending:
            return self._take_available()
        return None

    async def steer(self, *, wait_for_typing: bool = False) -> PerceptionBatch | None:
        async with self._draining, self._changed:
            if not self._pending:
                return None
            if not wait_for_typing:
                return self._take_available()
            return await self._settle(steering=True)

    def _available(self) -> list[tuple[float, Perception]]:
        key = self._pending[0][1].conversation_key
        return [(arrived, item) for arrived, item in self._pending if item.conversation_key == key]

    def _open(self, entries: list[tuple[float, Perception]]) -> str:
        batch_id = new_id('batch')
        emit_trace(self._trace, 'batch.opened', batch_id, batch_id=batch_id, opened_at=utc_now(),
                   perception_ids=[item.perception_id for _, item in entries],
                   count=len(entries), queue_size=len(self._pending))
        return batch_id

    def _take_available(self) -> PerceptionBatch:
        entries = self._available()
        return self._take(self._open(entries), entries, 'immediate')

    def _take(self, batch_id: str, entries: list[tuple[float, Perception]],
              reason: Literal['quiet', 'max_window', 'immediate']) -> PerceptionBatch:
        items = tuple(item for _, item in entries)
        batch = PerceptionBatch(items[0].conversation_key, items, reason, batch_id=batch_id)
        delivered = {item.perception_id for item in items}
        # Keep entries capacity-accounted until return so cancelled waits leave the queue intact.
        self._pending = [(stamp, item) for stamp, item in self._pending if item.perception_id not in delivered]
        self._stats['batches'] += 1
        emit_trace(self._trace, 'batch.closed', batch_id, batch_id=batch_id,
                   perception_ids=[item.perception_id for item in items], count=len(items),
                   arrivals=[stamp for stamp, _ in entries], closed_at=utc_now(),
                   reason=reason, queue_size=len(self._pending))
        return batch

    def _gap(self, item: Perception) -> float:
        return self.text_gap if item.kind == 'chat' else self.live_gap

    async def _settle(self, *, steering: bool = False) -> PerceptionBatch:
        loop = asyncio.get_running_loop()
        ceiling = math.inf if self.max_window is None else loop.time() + self.max_window
        entries = self._available()
        cursor = len(self._pending)
        batch_id = self._open(entries)
        key = entries[0][1].conversation_key
        gap = min(self._gap(item) for _, item in entries)
        quiet = entries[-1][0] + gap
        if steering and any(item.kind != 'chat' for _, item in entries):
            return self._take(batch_id, entries, 'immediate')

        while True:
            for arrived, item in self._pending[cursor:]:
                if item.conversation_key != key:
                    continue
                if arrived >= min(quiet, ceiling):
                    break
                entries.append((arrived, item))
                if steering and item.kind != 'chat':
                    return self._take(batch_id, entries, 'immediate')
                gap = min(gap, self._gap(item))
                quiet = arrived + gap
            cursor = len(self._pending)
            deadline = min(quiet, ceiling)
            remaining = deadline - loop.time()
            # A future live hold can defer quiet closure here, bounded by the same ceiling.
            if remaining <= 0:
                return self._take(batch_id, entries, 'max_window' if ceiling == deadline else 'quiet')
            if self._closed:
                return self._take(batch_id, entries, 'immediate')
            try:
                async with asyncio.timeout(remaining):
                    await self._changed.wait()
            except TimeoutError:
                pass

    async def close(self) -> None:
        async with self._changed:
            self._closed = True
            self._changed.notify_all()
