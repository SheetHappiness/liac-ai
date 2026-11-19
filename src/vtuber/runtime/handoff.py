"""Summarize a fixed journal prefix without blocking the conversation."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import closing

from vtuber.contracts.events import new_id
from vtuber.contracts.trace import TraceSink, emit_trace
from vtuber.minds.m6_context import RECAP_TOKENS, SingleContext, dialogue_turns, project_event
from vtuber.runtime.journal import Journal


class HandoffWorker:
    def __init__(self, character: str, journal: Journal, context: SingleContext,
                 summarize: Callable[[tuple[dict, ...]], Awaitable[str]],
                 trace: TraceSink | None = None) -> None:
        self.character = character
        self.journal = journal
        self.context = context
        self.summarize = summarize
        self.trace = trace
        self.task: asyncio.Task[None] | None = None
        self._completed = 0
        self._retry_at = 0
        self._closed = False

    def schedule(self, *, completed: bool = False) -> None:
        self._completed += completed
        if not self._closed and self._completed >= self._retry_at and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._run(), name='context-handoff')

    def _boundary(self, previous: int, recap: str) -> int:
        budget = self.context.budget
        tokens = self.context.base_tokens(recap)
        threshold = budget.handoff_threshold
        completed = last_speak = hot_start = 0
        with closing(self.journal.iter_dialogue_newest_first(self.character, after=previous)) as events:
            for turn in dialogue_turns(events):
                newest = turn[0]
                if newest.kind == 'character.reply.completed':
                    completed += 1
                    if not last_speak and newest.payload.get('action', 'speak') == 'speak':
                        last_speak = newest.sequence
                    if completed == 2:
                        hot_start = turn[-1].sequence
                if tokens < threshold:
                    tokens += sum(budget.message(message) for event in turn
                                  for message in project_event(event, self.journal.get))
                if hot_start and last_speak and tokens >= threshold:
                    return min(hot_start - 1, last_speak)
        return 0

    async def _run(self) -> None:
        identifier = new_id('handoff')
        try:
            previous, recap = self.journal.read_recap(self.character)
            boundary = self._boundary(previous, recap)
            if boundary <= previous:
                return
            with closing(self.journal.iter_dialogue_between(self.character, previous, boundary)) as events:
                messages, through, estimated = self.context.handoff(events, recap, self.journal.get)
            if not through:
                emit_trace(self.trace, 'handoff.skipped', identifier, reason='prefix_exceeds_budget',
                           covered_through_sequence=previous)
                self._retry_at = self._completed + 3
                return
            emit_trace(self.trace, 'handoff.started', identifier, previous_sequence=previous,
                       through_sequence=through, estimated_input_tokens=estimated)
            text = await self.summarize(messages)
            task = asyncio.current_task()
            if self._closed or (task is not None and task.cancelling()):
                raise asyncio.CancelledError
            if not isinstance(text, str) or not text.strip() or self.context.budget.count(text) > RECAP_TOKENS:
                raise ValueError('Invalid recap length')
            committed = self.journal.commit_recap(self.character, previous, through, text.strip())
            emit_trace(self.trace, 'handoff.completed', identifier, through_sequence=through,
                       committed=committed)
        except Exception as error:
            self._retry_at = self._completed + 3
            emit_trace(self.trace, 'handoff.failed', identifier, reason=type(error).__name__)

    async def close(self) -> None:
        self._closed = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
