"""Bounded, ephemeral intake on the caller's asyncio loop; no model or storage policy."""

import asyncio
import math

from vtuber.contracts.perception import Perception, PerceptionBatch


class PerceptionQueueFull(RuntimeError):
    """Meaningful input was not accepted; the adapter may retry it."""


class PerceptionBus:
    def __init__(self, *, live_gap: float = .30, text_gap: float = .75,
                 max_window: float = 2.0, max_pending: int = 256) -> None:
        for value in (live_gap, text_gap, max_window):
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
            self._pending.append((asyncio.get_running_loop().time(), item))
            self._stats['published'] += 1
            self._changed.notify_all()
            return True

    async def drain(self) -> PerceptionBatch | None:
        async with self._draining, self._changed:
            while not self._pending:
                if self._closed:
                    return None
                await self._changed.wait()
            first, head = self._pending[0]
            while True:
                gap = self.text_gap if head.kind == 'chat' else self.live_gap
                ceiling = first + self.max_window
                deadline = min(first + gap, ceiling)
                items = []
                for arrived, item in self._pending:
                    if item.conversation_key != head.conversation_key:
                        continue
                    # Late backlog belongs to a later batch even if no consumer was running.
                    if items and arrived >= deadline:
                        break
                    items.append(item)
                    if item.kind != 'chat':
                        gap = min(gap, self.live_gap)
                    deadline = min(arrived + gap, ceiling)
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0 or self._closed:
                    reason = ('max_window' if deadline == ceiling else 'quiet') if remaining <= 0 else 'immediate'
                    batch = PerceptionBatch(head.conversation_key, tuple(items), reason)
                    delivered = {item.perception_id for item in items}
                    # Items stay capacity-accounted until return; cancellation cannot lose them.
                    self._pending = [(stamp, item) for stamp, item in self._pending
                                     if item.perception_id not in delivered]
                    self._stats['batches'] += 1
                    return batch
                try:
                    async with asyncio.timeout(remaining):
                        await self._changed.wait()
                except TimeoutError:
                    pass

    async def close(self) -> None:
        async with self._changed:
            self._closed = True
            self._changed.notify_all()
