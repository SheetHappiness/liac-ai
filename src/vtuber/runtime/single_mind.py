"""Own one text turn at a time on the caller's asyncio loop."""

import asyncio
import logging
from typing import Literal

from vtuber.contracts.events import Event, RuntimeOutput, UserMessage
from vtuber.contracts.mind import MindDecision, SingleMindPort
from vtuber.contracts.perception import Perception, PerceptionBatch
from vtuber.contracts.protocols import OutputSink
from vtuber.minds.m6_context import build_m6_messages
from vtuber.runtime.attention import LiveState, should_wake
from vtuber.runtime.journal import Journal


logger = logging.getLogger(__name__)


class SingleMindRuntime:
    def __init__(self, character_id: str, journal: Journal, mind: SingleMindPort,
                 output: OutputSink, *, identity: str) -> None:
        self.character_id = character_id
        self.journal = journal
        self.mind = mind
        self.output = output
        self.identity = identity
        self._input_lock = asyncio.Lock()
        self._live_state = LiveState()
        self._active: tuple[UserMessage, int, asyncio.Task[None]] | None = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started or self._closed:
            raise RuntimeError('Single Mind cannot be started twice')
        for message in self.journal.unfinished_inputs(self.character_id):
            if message.kind != 'user.message.completed':
                continue
            started = self.journal.get(f'reply_started_{message.event_id}')
            revision = (started.payload['snapshot_revision'] if started else
                        self.journal.snapshot(self.character_id).revision)
            self._finish(message, revision, 'reply.cancelled', {'reason': 'process_restarted'}, notify=False)
        self._started = True

    async def submit_perceptions(self, batch: PerceptionBatch) -> asyncio.Task[None] | None:
        async with self._input_lock:
            if not self._started or self._closed:
                raise RuntimeError('Single Mind is not accepting perceptions')
            fresh_state = tuple(item for item in batch.items
                                if item.delivery == 'ambient'
                                and item.kind in ('state', 'observation')
                                and self.journal.get(item.perception_id) is None)
            message = self.journal.accept_local_perceptions(self.character_id, batch)
            self._live_state.observe(fresh_state)
            if not should_wake(batch) or message is None:
                return None
            revision = self.journal.snapshot(self.character_id).revision
            try:
                await self._cancel_active('superseded')
            except asyncio.CancelledError:
                self._finish(message, revision, 'reply.cancelled', {'reason': 'submission_cancelled'})
                raise
            dialogue = self.journal.recent_dialogue(self.character_id, limit=40)
            observations = self._live_state.snapshot(batch.conversation_key)
            self.journal.append(Event.create(self.character_id, 'character.reply.started',
                {'snapshot_revision': revision}, event_id=f'reply_started_{message.event_id}',
                turn_id=message.turn_id, causation_id=message.event_id))
            task = asyncio.create_task(self._run(message, revision, dialogue, observations), name='single-mind-turn')
            self._active = message, revision, task
            return task

    def _emit(self, output: RuntimeOutput) -> None:
        try:
            self.output(output)
        except Exception as error:
            logger.warning('Output sink failed: %s', type(error).__name__)

    def _finish(self, message: UserMessage | Event, revision: int,
                kind: Literal['reply.completed', 'reply.cancelled', 'reply.failed'],
                payload: dict[str, str], *, notify: bool = True) -> None:
        event_id = f'reply_terminal_{message.event_id}'
        if self.journal.get(event_id) is not None:
            return
        self.journal.append(Event.create(self.character_id, f'character.{kind}',
            {**payload, 'snapshot_revision': revision}, event_id=event_id,
            turn_id=message.turn_id, causation_id=message.event_id))
        if notify:
            self._emit(RuntimeOutput(kind, self.character_id, revision, message.turn_id,
                                     payload['text'] if kind == 'reply.completed' else payload['reason']))

    async def _run(self, message: UserMessage, revision: int, dialogue: tuple[Event, ...],
                   observations: tuple[Perception, ...]) -> None:
        task = asyncio.current_task()
        assert task is not None
        index = 0
        streaming = True

        def is_current() -> bool:
            return self._active is not None and self._active[2] is task

        def preview(text: str) -> None:
            nonlocal index
            if streaming and is_current() and not task.cancelling() and text:
                index += 1
                self._emit(RuntimeOutput('reply.delta', self.character_id, revision, message.turn_id, text, index))

        self._emit(RuntimeOutput('reply.started', self.character_id, revision, message.turn_id))
        try:
            decision = await self.mind.generate(
                build_m6_messages(self.identity, dialogue, observations), on_speak_delta=preview)
            if not is_current() or task.cancelling():
                raise asyncio.CancelledError
            if not isinstance(decision, MindDecision) or not decision.tool_call_id.strip():
                raise ValueError('Expected one completed tool decision with an ID')
        except asyncio.CancelledError:
            if is_current():
                self._finish(message, revision, 'reply.cancelled', {'reason': 'cancelled'})
            raise
        except Exception as error:
            if is_current():
                self._finish(message, revision, 'reply.failed', {'reason': type(error).__name__})
        else:
            self._finish(message, revision, 'reply.completed', {'text': decision.message,
                'action': decision.action, 'tool_call_id': decision.tool_call_id})
        finally:
            streaming = False

    async def _cancel_active(self, reason: str) -> None:
        if self._active is None:
            return
        (message, revision, task), self._active = self._active, None
        task.cancel()
        try:
            self._finish(message, revision, 'reply.cancelled', {'reason': reason})
        finally:
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        async with self._input_lock:
            self._closed = True
            await self._cancel_active('shutdown')
