import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_perception import batch, perception
from vtuber.contracts.events import Event
from vtuber.contracts.mind import MindDecision
from vtuber.minds.m6_context import PERCEPTION_FRAME
from vtuber.runtime.journal import EventConflict, Journal
from vtuber.runtime.perception_bus import PerceptionBus
from vtuber.runtime.single_mind import SingleMindRuntime


class ScriptedMind:
    def __init__(self, *scripts):
        self.calls = []
        self.scripts = iter(scripts)

    async def generate(self, messages, *, on_speak_delta=None):
        self.calls.append(messages)
        scripted = next(self.scripts)
        if isinstance(scripted, MindDecision):
            return scripted
        return await scripted(messages, on_speak_delta)


def frame(message):
    return json.loads(message['content'].removeprefix(PERCEPTION_FRAME))


class SingleMindRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'runtime.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())
        self.outputs = []
        self.traces = []
        self.changed = asyncio.Event()

    async def start(self, mind, *, bus=None, trace=None, run=True, model_metrics=None):
        def output(value):
            self.outputs.append(value)
            self.changed.set()

        def capture(kind, batch_id, data):
            self.traces.append((kind, batch_id, data))

        runtime = SingleMindRuntime('primary', self.journal, mind, output, identity='You are Liac.',
                                    bus=bus, trace=trace or capture, model_metrics=model_metrics)
        await runtime.start()
        self.addAsyncCleanup(runtime.close)
        if run:
            self.loop = asyncio.create_task(runtime.run())
        return runtime

    def events(self, kind):
        return tuple(event for event in self.journal.read('primary') if event.kind == kind)

    async def wait_for_event(self, kind, count=1):
        async with asyncio.timeout(5):
            while len(self.events(kind)) < count:
                self.changed.clear()
                await self.changed.wait()

    async def finish(self, runtime):
        await runtime.finish_input()
        await asyncio.wait_for(self.loop, 5)

    async def test_direct_burst_is_one_frame_turn_and_reply(self):
        async def speak(messages, preview):
            user, = self.events('user.message.completed')
            started, = self.events('character.reply.started')
            self.assertEqual(started.event_id, f'reply_started_{user.event_id}')
            self.assertEqual(started.causation_id, user.event_id)
            current, = [message for message in messages if message['role'] == 'user']
            perceptions = frame(current)
            self.assertEqual([item['content'] for item in perceptions], ['Hey', 'Wait', 'How are you?'])
            self.assertEqual([item['perception_id'] for item in perceptions], ['one', 'two', 'three'])
            self.assertEqual([item['author_id'] for item in perceptions], ['local'] * 3)
            self.assertTrue(all(item['source'] == item['conversation_key'] == 'local' for item in perceptions))
            preview('Hel')
            preview('lo!')
            self.assertFalse(self.events('character.reply.completed'))
            return MindDecision('speak', 'Hello!', 'speak-id')

        mind = ScriptedMind(speak)
        runtime = await self.start(mind)
        await runtime.publish(perception('one', content='Hey', author_id='local'))
        await asyncio.sleep(.4)
        await runtime.publish(perception('two', content='Wait', author_id='local'))
        await asyncio.sleep(.4)
        await runtime.publish(perception('three', content='How are you?', author_id='local'))
        await self.wait_for_event('character.reply.completed')
        await self.finish(runtime)
        user, = self.events('user.message.completed')
        terminal, = self.events('character.reply.completed')
        self.assertEqual(user.payload['text'], 'Hey\nWait\nHow are you?')
        self.assertEqual(user.payload['perception_ids'], [e.event_id for e in self.events('perception.received')])
        self.assertEqual(terminal.event_id, f'reply_terminal_{user.event_id}')
        self.assertEqual(terminal.turn_id, user.turn_id)
        self.assertEqual(terminal.payload, {'text': 'Hello!', 'action': 'speak', 'tool_call_id': 'speak-id'})
        self.assertEqual([(out.kind, out.text) for out in self.outputs], [
            ('reply.started', ''), ('reply.delta', 'Hel'), ('reply.delta', 'lo!'), ('reply.completed', 'Hello!')])
        self.assertEqual([out.delta_index for out in self.outputs if out.kind == 'reply.delta'], [1, 2])
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        self.assertEqual(len(mind.calls), 1)
        self.assertEqual([kind for kind, _, _ in self.traces],
                         ['perception.enqueued', 'batch.opened', 'perception.enqueued', 'perception.enqueued',
                          'batch.closed', 'admission.decided', 'turn.started', 'model.started',
                          'model.completed', 'turn.completed'])
        correlated = [batch_id for kind, batch_id, _ in self.traces if kind != 'perception.enqueued']
        self.assertEqual(set(correlated), {user.payload['batch_id']})
        self.assertNotIn('How are you?', json.dumps(self.traces))

    async def test_idle_quiet_gap_starts_two_turns(self):
        silence = MindDecision('stay_silent', tool_call_id='quiet')
        mind = ScriptedMind(silence, replace(silence, tool_call_id='quiet-2'))
        runtime = await self.start(mind)
        await runtime.publish(perception('first'))
        await asyncio.sleep(2)
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        await runtime.publish(perception('second'))
        await self.finish(runtime)
        groups = self.events('user.message.completed')
        self.assertEqual([group.payload['perception_ids'] for group in groups], [['first'], ['second']])
        self.assertEqual(len(mind.calls), 2)

    async def test_metrics_failure_cannot_discard_a_successful_reply(self):
        def unavailable():
            raise OSError('Private diagnostic')

        usage = {'input': 12, 'cacheRead': 8, 'cacheWrite': 5}
        mind = ScriptedMind(MindDecision('speak', 'Done', 'done-id', usage))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=0), model_metrics=unavailable)
        await runtime.publish(perception('metrics'))
        await self.finish(runtime)
        self.assertEqual(self.events('character.reply.completed')[0].payload['text'], 'Done')
        completed = next(data for kind, _, data in self.traces if kind == 'model.completed')
        self.assertEqual(completed['actual_input_tokens'], 25)
        self.assertNotIn('Private diagnostic', json.dumps(self.traces))

    async def test_busy_backlog_is_serial_and_does_not_settle_twice(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        first_callbacks = []
        bus = PerceptionBus(text_gap=.20)

        async def first(messages, preview):
            first_callbacks.append(preview)
            entered.set()
            await release.wait()
            return MindDecision('speak', 'First reply', 'first-id')

        async def second(messages, preview):
            first_callbacks[0]('Late')
            self.assertEqual(len(self.events('character.reply.completed')), 1)
            self.assertEqual([item['perception_id'] for item in frame(messages[-1])], ['busy-1', 'busy-2'])
            self.assertEqual([item['author_id'] for item in frame(messages[-1])], ['alex', 'sam'])
            self.assertEqual([item['perception_id'] for item in frame(messages[1])], ['first'])
            return MindDecision('stay_silent', tool_call_id='second-id')

        mind = ScriptedMind(first, second)
        runtime = await self.start(mind, bus=bus)
        await runtime.publish(perception('first'))
        await asyncio.wait_for(entered.wait(), 1)
        await runtime.publish(perception('busy-1', author_id='alex'))
        await asyncio.sleep(.23)
        await runtime.publish(perception('busy-2', author_id='sam'))
        await asyncio.sleep(.23)
        self.assertEqual(len(mind.calls), 1)
        self.assertIsNone(self.journal.get('busy-1'))
        release.set()
        await asyncio.wait_for(self.wait_for_event('character.reply.completed', 2), .16)
        await self.finish(runtime)
        self.assertEqual(len(mind.calls), 2)
        self.assertEqual(self.events('character.reply.cancelled'), ())
        self.assertFalse(any(out.kind == 'reply.delta' for out in self.outputs))

    async def test_cap_leaves_later_input_for_the_next_turn(self):
        closes = []
        first_close = asyncio.Event()

        def trace(kind, batch_id, data):
            if kind == 'batch.closed':
                closes.append(data)
                first_close.set()

        decision = MindDecision('stay_silent', tool_call_id='first')
        mind = ScriptedMind(decision, replace(decision, tool_call_id='second'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=1, max_window=.15, trace=trace))
        await runtime.publish(perception('first'))
        await asyncio.sleep(.03)
        await runtime.publish(perception('second'))
        await asyncio.wait_for(first_close.wait(), .6)
        await runtime.publish(perception('after-cap'))
        await self.finish(runtime)
        self.assertEqual(closes[0]['reason'], 'max_window')
        self.assertEqual([data['perception_ids'] for data in closes], [['first', 'second'], ['after-cap']])
        self.assertEqual(len(mind.calls), 2)

    async def test_context_keeps_more_than_forty_dialogue_events_within_budget(self):
        history = ['PX7M-K4Q2', *(f'History {i}' for i in range(20))]
        for i, content in enumerate(history):
            message = self.journal.accept_local_perceptions('primary', batch(perception(f'prior-{i}', content=content)))
            self.journal.append(Event.create('primary', 'character.reply.completed',
                {'text': '', 'action': 'stay_silent', 'tool_call_id': f'quiet-{i}'},
                turn_id=message.turn_id, causation_id=message.event_id))

        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='probe'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=0))
        await runtime.publish(perception('probe', content='What was the first code?'))
        await self.finish(runtime)

        messages, = mind.calls
        self.assertEqual([message['role'] for message in messages],
                         ['system', *(['user', 'assistant', 'toolResult'] * len(history)), 'user'])
        self.assertEqual([frame(message)[0]['content'] for message in messages if message['role'] == 'user'],
                         [*history, 'What was the first code?'])
        self.assertLess(len(json.dumps(messages, ensure_ascii=False).encode()), 64 * 1024)

    async def test_oversized_frame_fails_only_its_turn(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='next'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=0))
        await runtime.publish(perception('oversized', content='x' * (64 * 1024)))
        await self.wait_for_event('character.reply.failed')
        await runtime.publish(perception('next'))
        await self.finish(runtime)
        self.assertEqual(len(mind.calls), 1)
        self.assertEqual([message['role'] for message in mind.calls[0]], ['system', 'user'])
        self.assertEqual(frame(mind.calls[0][-1])[0]['perception_id'], 'next')
        self.assertEqual(self.events('character.reply.failed')[0].payload['reason'], 'ContextBudgetExceeded')

    async def test_ambient_is_audited_and_only_same_batch_ambient_reaches_mind(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind, bus=PerceptionBus(live_gap=0))
        await runtime.publish(perception('ambient', delivery='ambient', kind='observation', conversation_key='other'))
        self.assertFalse(await runtime.publish(perception('noise', delivery='noise')))
        await runtime.publish(perception('nearby', delivery='ambient', kind='observation'))
        await runtime.publish(perception('direct'))
        await self.finish(runtime)
        self.assertEqual([e.event_id for e in self.events('perception.received')], ['ambient', 'nearby', 'direct'])
        self.assertEqual([(data['admitted'], data['reason']) for kind, _, data in self.traces
                          if kind == 'admission.decided'],
                         [(False, 'no_fresh_direct_input'), (True, 'fresh_direct_input')])
        self.assertEqual(len(mind.calls), 1)
        self.assertEqual([item['perception_id'] for item in frame(mind.calls[0][-1])], ['nearby', 'direct'])
        self.assertEqual(self.events('character.reply.completed')[0].payload['text'], '')
        self.assertEqual([(out.kind, out.text) for out in self.outputs], [('reply.started', ''), ('reply.completed', '')])

    async def test_replay_deduplicates_pending_and_committed_inputs(self):
        mind = ScriptedMind(MindDecision('speak', 'Hi', 'once'), MindDecision('stay_silent', tool_call_id='next'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=0))
        incoming = perception('same')
        self.assertTrue(await runtime.publish(incoming))
        self.assertFalse(await runtime.publish(incoming))
        await self.wait_for_event('character.reply.completed')
        self.assertTrue(await runtime.publish(perception('next')))
        self.assertFalse(await runtime.publish(incoming))
        with self.assertRaises(EventConflict):
            await runtime.publish(replace(incoming, content='conflict'))
        await self.finish(runtime)
        self.assertEqual([e.payload['action'] for e in self.events('character.reply.completed')], ['speak', 'stay_silent'])
        self.assertEqual([e.event_id for e in self.events('perception.received')], ['same', 'next'])
        self.assertEqual(len(mind.calls), 2)

    async def test_failure_does_not_block_the_next_batch_or_fabricate_a_reply(self):
        async def interrupted(messages, preview):
            preview('Incomplete')
            raise RuntimeError('Private provider diagnostic')

        mind = ScriptedMind(interrupted, MindDecision('speak', 'Missing ID'),
                            MindDecision('stay_silent', tool_call_id='next'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=0))
        for i, identifier in enumerate(('interrupted', 'missing-id'), 1):
            await runtime.publish(perception(identifier))
            await self.wait_for_event('character.reply.failed', i)
        await runtime.publish(perception('next'))
        await self.finish(runtime)
        failures = self.events('character.reply.failed')
        self.assertEqual([e.payload['reason'] for e in failures], ['RuntimeError', 'ValueError'])
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual([frame(m)[0]['perception_id'] for m in mind.calls[-1] if m['role'] == 'user'],
                         ['interrupted', 'missing-id', 'next'])
        self.assertNotIn('Private provider diagnostic', json.dumps(self.traces))
        self.assertEqual([data['status'] for kind, _, data in self.traces if kind == 'turn.failed'], ['failed'] * 2)

    async def test_shutdown_cancels_active_and_records_pending_without_running_them(self):
        entered = asyncio.Event()
        exited = asyncio.Event()
        callbacks = []

        async def held(messages, preview):
            callbacks.append(preview)
            preview('Provisional')
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                preview('Late')
                return MindDecision('speak', 'Stale result', 'stale')
            finally:
                exited.set()

        completed = perception('completed')
        mind = ScriptedMind(MindDecision('speak', 'Already committed', 'done'), held)
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=.02))
        await runtime.publish(completed)
        await self.wait_for_event('character.reply.completed')
        await runtime.publish(perception('active'))
        await asyncio.wait_for(entered.wait(), 1)
        await runtime.publish(perception('queued-1'))
        await runtime.publish(perception('queued-2'))
        await asyncio.wait_for(runtime.close(), 1)
        self.assertTrue(exited.is_set())
        self.assertTrue(self.loop.cancelled())
        callbacks[0]('Very late')
        self.assertEqual([out.text for out in self.outputs if out.kind == 'reply.delta'], ['Provisional'])
        cancelled = self.events('character.reply.cancelled')
        self.assertEqual([e.payload['reason'] for e in cancelled], ['shutdown', 'shutdown'])
        self.assertEqual([e.payload['perception_ids'] for e in self.events('user.message.completed')],
                         [['completed'], ['active'], ['queued-1', 'queued-2']])
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        self.assertEqual(len(mind.calls), 2)
        self.journal.close()
        self.journal = Journal(self.path)
        restarted_mind = ScriptedMind()
        restarted = await self.start(restarted_mind)
        self.assertFalse(await restarted.publish(completed))
        await self.finish(restarted)
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual(restarted_mind.calls, [])

    async def test_stop_wins_over_settle_timeout_cancellation(self):
        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='unexpected'))
        runtime = await self.start(mind, bus=PerceptionBus(text_gap=.03))
        stopped = asyncio.Event()
        original_timeout = asyncio.Timeout._on_timeout

        async def close():
            await runtime.close()
            stopped.set()

        def stop_at_timeout(timeout):
            asyncio.create_task(close())
            original_timeout(timeout)

        with patch.object(asyncio.Timeout, '_on_timeout', stop_at_timeout):
            await runtime.publish(perception('settling'))
            await asyncio.wait_for(stopped.wait(), .6)
        self.assertEqual(mind.calls, [])
        cancelled, = self.events('character.reply.cancelled')
        self.assertEqual(cancelled.payload['reason'], 'shutdown')
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_restart_closes_unfinished_without_regeneration(self):
        bus = PerceptionBus(text_gap=0)
        before, after = perception('accepted'), perception('already-visible')
        before_start = self.journal.accept_local_perceptions('primary', batch(before))
        after_start = self.journal.accept_local_perceptions('primary', batch(after))
        self.journal.append(Event.create('primary', 'character.reply.started', {'snapshot_revision': 7},
                            event_id=f'reply_started_{after_start.event_id}', turn_id=after_start.turn_id,
                            causation_id=after_start.event_id))
        self.journal.close()
        self.journal = Journal(self.path)
        mind = ScriptedMind()
        runtime = await self.start(mind, bus=bus)
        self.assertFalse(await runtime.publish(after))
        await self.finish(runtime)
        recovered = self.events('character.reply.cancelled')
        self.assertEqual([e.causation_id for e in recovered], [before_start.event_id, after_start.event_id])
        self.assertEqual([e.payload for e in recovered], [
            {'reason': 'process_restarted'}, {'reason': 'process_restarted'}])
        self.assertFalse(mind.calls)
        self.assertFalse(self.outputs)
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_close_before_loop_persists_accepted_queue(self):
        mind = ScriptedMind()
        runtime = await self.start(mind, run=False)
        await runtime.publish(perception('closing'))
        await runtime.close()
        self.assertEqual(mind.calls, [])
        terminal, = self.events('character.reply.cancelled')
        self.assertEqual(terminal.payload['reason'], 'shutdown')
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_trace_failure_never_blocks_settling_or_inference(self):
        def broken(kind, correlation, data):
            raise RuntimeError('Broken trace sink')

        mind = ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet'))
        runtime = await self.start(mind, bus=PerceptionBus(trace=broken), trace=broken)
        with self.assertLogs('vtuber.contracts.trace', level='WARNING') as logs:
            await runtime.publish(perception('direct'))
            await self.finish(runtime)
        self.assertTrue(all('Broken trace sink' not in entry for entry in logs.output))
        self.assertEqual(len(mind.calls), 1)
        self.assertEqual(len(self.events('character.reply.completed')), 1)
