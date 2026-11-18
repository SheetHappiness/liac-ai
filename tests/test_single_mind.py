import asyncio
import tempfile
import unittest
from pathlib import Path

from test_perception import perception
from test_perception_runtime import batch
from vtuber.contracts.events import Event
from vtuber.contracts.mind import MindDecision
from vtuber.runtime.journal import Journal
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


class SingleMindRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'runtime.sqlite3'
        self.journal = Journal(self.path)
        self.addCleanup(lambda: self.journal.close())
        self.outputs = []

    async def start(self, mind):
        runtime = SingleMindRuntime('primary', self.journal, mind, self.outputs.append, identity='You are Liac.')
        await runtime.start()
        self.addAsyncCleanup(runtime.close)
        return runtime

    def events(self, kind):
        return tuple(event for event in self.journal.read('primary') if event.kind == kind)

    async def test_direct_burst_starts_one_luna_turn(self):
        async def speak(messages, preview):
            user, = self.events('user.message.completed')
            started, = self.events('character.reply.started')
            self.assertEqual(started.event_id, f'reply_started_{user.event_id}')
            self.assertEqual(started.causation_id, user.event_id)
            self.assertEqual([m['content'] for m in messages if m['role'] == 'user'], ['first\nsecond'])
            preview('Hel')
            self.assertFalse(self.events('character.reply.completed'))
            return MindDecision('speak', 'Hello!', 'speak-id')

        mind = ScriptedMind(speak)
        runtime = await self.start(mind)
        await (await runtime.submit_perceptions(batch(perception('one', content='first'),
                                                       perception('two', content='second'))))
        user, = self.events('user.message.completed')
        terminal, = self.events('character.reply.completed')
        self.assertEqual(terminal.event_id, f'reply_terminal_{user.event_id}')
        self.assertEqual(terminal.turn_id, user.turn_id)
        self.assertEqual(terminal.payload, {'text': 'Hello!', 'action': 'speak', 'tool_call_id': 'speak-id',
                                            'snapshot_revision': 0})
        self.assertEqual([(out.kind, out.text) for out in self.outputs],
                         [('reply.started', ''), ('reply.delta', 'Hel'), ('reply.completed', 'Hello!')])
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
        self.assertEqual(len(mind.calls), 1)

    async def test_ambient_only_no_inference(self):
        mind = ScriptedMind()
        runtime = await self.start(mind)
        self.assertIsNone(await runtime.submit_perceptions(batch(perception('ambient', delivery='ambient'),
                                                                  perception('noise', delivery='noise'))))
        ambient, = self.events('perception.received')
        self.assertEqual(ambient.event_id, 'ambient')
        self.assertEqual(mind.calls, [])
        self.assertEqual(self.outputs, [])

    async def test_replay_no_second_speech(self):
        mind = ScriptedMind(MindDecision('speak', 'Hi', 'once'))
        runtime = await self.start(mind)
        incoming = batch(perception('same'))
        await (await runtime.submit_perceptions(incoming))
        self.assertIsNone(await runtime.submit_perceptions(incoming))
        self.assertEqual(len(self.events('character.reply.completed')), 1)
        self.assertEqual(len(mind.calls), 1)

    async def test_silence_is_completed_without_text(self):
        runtime = await self.start(ScriptedMind(MindDecision('stay_silent', tool_call_id='quiet')))
        await (await runtime.submit_perceptions(batch(perception('quiet'))))
        terminal, = self.events('character.reply.completed')
        self.assertEqual(terminal.payload['action'], 'stay_silent')
        self.assertEqual(terminal.payload['text'], '')
        self.assertEqual([(out.kind, out.text) for out in self.outputs],
                         [('reply.started', ''), ('reply.completed', '')])

    async def test_superseded_turn_cannot_emit_late_text(self):
        entered = asyncio.Event()
        previous_callbacks = []

        async def old_turn(messages, preview):
            previous_callbacks.append(preview)
            preview('Provisional')
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                preview('Late')
                return MindDecision('speak', 'Stale result', 'stale')

        runtime = await self.start(ScriptedMind(old_turn, MindDecision('speak', 'Current', 'current')))
        old_task = await runtime.submit_perceptions(batch(perception('old')))
        await asyncio.wait_for(entered.wait(), 1)
        newest = await runtime.submit_perceptions(batch(perception('new')))
        await newest
        previous_callbacks[0]('Very late')
        self.assertTrue(old_task.done())
        old, = self.events('character.reply.cancelled')
        current, = self.events('character.reply.completed')
        self.assertEqual(old.payload, {'reason': 'superseded', 'snapshot_revision': 0})
        self.assertEqual(current.payload['text'], 'Current')
        self.assertEqual([out.text for out in self.outputs if out.kind == 'reply.delta'], ['Provisional'])

    async def test_restart_closes_unfinished_without_regeneration(self):
        before_start = self.journal.accept_local_perceptions('primary', batch(perception('accepted')))
        after_start = self.journal.accept_local_perceptions('primary', batch(perception('already-visible')))
        self.journal.append(Event.create('primary', 'character.reply.started', {'snapshot_revision': 7},
                            event_id=f'reply_started_{after_start.event_id}', turn_id=after_start.turn_id,
                            causation_id=after_start.event_id))
        self.journal.close()
        self.journal = Journal(self.path)
        mind = ScriptedMind()
        runtime = await self.start(mind)
        self.assertIsNone(await runtime.submit_perceptions(batch(perception('already-visible',
            occurred_at=after_start.occurred_at))))
        recovered = self.events('character.reply.cancelled')
        self.assertEqual([e.causation_id for e in recovered], [before_start.event_id, after_start.event_id])
        self.assertEqual([e.payload for e in recovered], [
            {'reason': 'process_restarted', 'snapshot_revision': revision} for revision in (0, 7)])
        self.assertFalse(mind.calls)
        self.assertFalse(self.outputs)
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())

    async def test_only_complete_tool_call_commits(self):
        async def interrupted(messages, preview):
            preview('Incomplete')
            raise RuntimeError('Private provider diagnostic')

        runtime = await self.start(ScriptedMind(interrupted, MindDecision('speak', 'Missing ID')))
        await (await runtime.submit_perceptions(batch(perception('interrupted'))))
        await (await runtime.submit_perceptions(batch(perception('missing-id'))))
        self.assertEqual(self.events('character.reply.completed'), ())
        failures = self.events('character.reply.failed')
        self.assertEqual(len(failures), 2)
        self.assertTrue(all('text' not in e.payload for e in failures))
        self.assertEqual(failures[0].payload['reason'], 'RuntimeError')

    async def test_close_before_generation_leaves_a_terminal(self):
        mind = ScriptedMind()
        runtime = await self.start(mind)
        task = await runtime.submit_perceptions(batch(perception('closing')))
        await runtime.close()
        self.assertTrue(task.cancelled())
        self.assertEqual(mind.calls, [])
        terminal, = self.events('character.reply.cancelled')
        self.assertEqual(terminal.payload['reason'], 'shutdown')
        self.assertEqual(self.journal.unfinished_inputs('primary'), ())
