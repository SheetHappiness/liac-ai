"""Own one perception-driven text turn at a time."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import closing
from typing import Literal

from vtuber.contracts.events import Event, RuntimeOutput, utc_now
from vtuber.contracts.mind import MindDecision, SingleMindPort
from vtuber.contracts.perception import Perception, PerceptionBatch
from vtuber.contracts.protocols import OutputSink
from vtuber.contracts.trace import TraceSink, emit_trace
from vtuber.minds.m6_context import SingleContext, TokenBudget, build_m6_messages
from vtuber.runtime.handoff import HandoffWorker
from vtuber.runtime.journal import Journal
from vtuber.runtime.perception_bus import PerceptionBus


logger = logging.getLogger(__name__)


class SingleMindRuntime:
    def __init__(self, character_id: str, journal: Journal, mind: SingleMindPort,
                 output: OutputSink, *, identity: str, bus: PerceptionBus | None = None,
                 trace: TraceSink | None = None, budget: TokenBudget | None = None,
                 summarize: Callable[[tuple[dict, ...]], Awaitable[str]] | None = None,
                 model_metrics: Callable[[], dict] | None = None) -> None:
        self.character_id = character_id
        self.journal = journal
        self.mind = mind
        self.output = output
        self.identity = identity
        self.trace = trace
        self.context = SingleContext(identity, budget) if budget is not None else None
        self.handoff = HandoffWorker(character_id, journal, self.context, summarize, trace) if (
            self.context is not None and summarize is not None) else None
        self.model_metrics = model_metrics
        self.bus = bus if bus is not None else PerceptionBus(trace=trace)
        self._owner: asyncio.Task[None] | None = None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._started or self._closed:
            raise RuntimeError('Single Mind cannot be started twice')
        for message in self.journal.unfinished_inputs(self.character_id):
            self._finish(message, 'reply.cancelled', {'reason': 'process_restarted'}, notify=False)
        self._started = True
        if self.handoff is not None:
            self.handoff.schedule()

    async def publish(self, item: Perception) -> bool:
        if not self._started or self._closed:
            raise RuntimeError('Single Mind is not accepting perceptions')
        if not isinstance(item, Perception):
            raise ValueError('Expected a Perception')
        if not self.journal.is_new_perception(self.character_id, item):
            return False
        return await self.bus.publish(item)

    async def finish_input(self) -> None:
        await self.bus.close()

    async def run(self) -> None:
        if not self._started or self._closed or self._owner is not None:
            raise RuntimeError('Single Mind cannot start another loop')
        self._owner = asyncio.current_task()
        try:
            while (batch := await self.bus.drain()) is not None:
                message = self.journal.accept_local_perceptions(self.character_id, batch)
                emit_trace(self.trace, 'admission.decided', batch.batch_id, batch_id=batch.batch_id,
                           turn_id=message.turn_id if message else None, admitted=message is not None,
                           reason='fresh_direct_input' if message else 'no_fresh_direct_input')
                if message is not None:
                    await self._run_turn(message, batch)
        except asyncio.CancelledError:
            await self._flush_shutdown()
            raise
        finally:
            self._owner = None

    async def _run_turn(self, message: Event, batch: PerceptionBatch) -> None:
        started = self.journal.append(Event.create(self.character_id, 'character.reply.started',
            {}, event_id=f'reply_started_{message.event_id}',
            turn_id=message.turn_id, causation_id=message.event_id))
        emit_trace(self.trace, 'turn.started', batch.batch_id, batch_id=batch.batch_id,
                   turn_id=message.turn_id, started_at=started.occurred_at)
        self._emit(RuntimeOutput('reply.started', self.character_id, message.turn_id))
        task = asyncio.create_task(self._turn(message, batch), name='single-mind-turn')
        try:
            decision = await asyncio.shield(task)
        except asyncio.CancelledError:
            owner = asyncio.current_task()
            assert owner is not None
            stopping = bool(owner.cancelling())
            if stopping:
                self._closed = True
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._finish(message, 'reply.cancelled', {'reason': 'shutdown' if stopping else 'cancelled'},
                         batch_id=batch.batch_id)
            if stopping:
                raise
        except Exception as error:
            self._finish(message, 'reply.failed', {'reason': type(error).__name__},
                         batch_id=batch.batch_id)
        else:
            self._finish(message, 'reply.completed', {'text': decision.message,
                'action': decision.action, 'tool_call_id': decision.tool_call_id}, batch_id=batch.batch_id)
            if self.handoff is not None:
                self.handoff.schedule(completed=True)

    async def _turn(self, message: Event, batch: PerceptionBatch) -> MindDecision:
        task = asyncio.current_task()
        assert task is not None
        index = 0
        streaming = True

        def preview(text: str) -> None:
            nonlocal index
            if streaming and not task.cancelling() and text:
                index += 1
                self._emit(RuntimeOutput('reply.delta', self.character_id, message.turn_id, text, index))

        context_data = {}
        if self.context is None:
            with closing(self.journal.iter_dialogue_newest_first(self.character_id)) as dialogue:
                messages = build_m6_messages(self.identity, dialogue, lookup=self.journal.get)
        else:
            through, recap = self.journal.read_recap(self.character_id)
            with closing(self.journal.iter_dialogue_newest_first(self.character_id, after=through)) as dialogue:
                projection = self.context.project(dialogue, recap, current=message, lookup=self.journal.get)
            messages = projection.messages
            context_data = {'estimated_input_tokens': projection.estimated_tokens,
                            'history_omitted': projection.omitted, 'covered_through_sequence': through}
        emit_trace(self.trace, 'model.started', batch.batch_id, batch_id=batch.batch_id,
                   turn_id=message.turn_id, started_at=utc_now(), **context_data)
        status = 'failed'
        action = None
        usage = None
        try:
            decision = await self.mind.generate(messages, on_speak_delta=preview)
            if task.cancelling():
                raise asyncio.CancelledError
            if not isinstance(decision, MindDecision) or not decision.tool_call_id.strip():
                raise ValueError('Expected one completed tool decision with an ID')
            status, action = 'completed', decision.action
            usage = decision.usage
            return decision
        except asyncio.CancelledError:
            status = 'cancelled'
            raise
        finally:
            streaming = False
            metrics = {}
            if self.model_metrics is not None:
                try:
                    metrics = self.model_metrics()
                except Exception as error:
                    logger.warning('Model metrics unavailable: %s', type(error).__name__)
            if usage is not None:
                metrics = {**metrics, 'usage': usage, 'actual_input_tokens': sum(
                    usage.get(key, 0) for key in ('input', 'cacheRead', 'cacheWrite'))}
            emit_trace(self.trace, 'model.completed', batch.batch_id, batch_id=batch.batch_id,
                       turn_id=message.turn_id, ended_at=utc_now(), status=status, action=action, **metrics)

    def _emit(self, output: RuntimeOutput) -> None:
        try:
            self.output(output)
        except Exception as error:
            logger.warning('Output sink failed: %s', type(error).__name__)

    def _finish(self, message: Event,
                kind: Literal['reply.completed', 'reply.cancelled', 'reply.failed'],
                payload: dict[str, str], *, batch_id: str | None = None, notify: bool = True) -> None:
        event_id = f'reply_terminal_{message.event_id}'
        if self.journal.get(event_id) is not None:
            return
        terminal = self.journal.append(Event.create(self.character_id, f'character.{kind}',
            payload, event_id=event_id,
            turn_id=message.turn_id, causation_id=message.event_id))
        status = kind.removeprefix('reply.')
        if batch_id is not None:
            emit_trace(self.trace, 'turn.completed' if status == 'completed' else 'turn.failed', batch_id,
                       batch_id=batch_id, turn_id=message.turn_id, ended_at=terminal.occurred_at,
                       status=status, action=payload.get('action'), reason=payload.get('reason'))
        if notify:
            self._emit(RuntimeOutput(kind, self.character_id, message.turn_id,
                                     payload['text'] if kind == 'reply.completed' else payload['reason']))

    async def _flush_shutdown(self) -> None:
        self._closed = True
        await self.bus.close()
        while (batch := self.bus.drain_nowait()) is not None:
            message = self.journal.accept_local_perceptions(self.character_id, batch)
            emit_trace(self.trace, 'admission.decided', batch.batch_id, batch_id=batch.batch_id,
                       turn_id=message.turn_id if message else None, admitted=False, reason='shutdown')
            if message is not None:
                self._finish(message, 'reply.cancelled', {'reason': 'shutdown'}, batch_id=batch.batch_id)

    async def close(self) -> None:
        stopping = not self._closed
        self._closed = True
        owner = self._owner
        if owner is not None:
            if stopping:
                owner.cancel()
            await asyncio.shield(asyncio.gather(owner, return_exceptions=True))
        if self.handoff is not None:
            await self.handoff.close()
        await self._flush_shutdown()
