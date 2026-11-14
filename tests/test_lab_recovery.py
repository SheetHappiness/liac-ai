import asyncio
import tempfile
import unittest
from pathlib import Path

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.lab.archive import RunArchive, RunReader
from vtuber.tracing import TraceRecorder


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_payload_and_omissions_are_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            for missing in (True, False):
                with self.subTest(missing_payload=missing):
                    archive = RunArchive.create(Path(folder), Config())
                    archive.trace('runtime.status', 'primary',
                        {'journal_sequence': 1, 'deep_cursor': 1} if missing else
                        {'omitted': True, 'reason': 'too large'})
                    await archive.close('completed')
                    if missing:
                        (archive.path/'00000001.json').unlink()
                    reader = RunReader(archive.path)
                    self.assertTrue(reader.summary()['partial'])
                    self.assertTrue(reader.summary()['capture_error'])
                    self.assertEqual(len(reader.rows), 1)

    async def test_resume_preserves_loss_and_does_not_recapture_events(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = RunArchive.create(Path(folder), Config(), scenario={'id': 'test'})
            async with open_runtime(Config(db=archive.db, fast_delay=0, deep_delay=0),
                                    archive.observe_output, trace=archive.trace) as runtime:
                await (await runtime.submit(UserMessage('hello')))
                await runtime.close()
                await archive.capture(runtime)
            archive.trace._error = 'previous loss'
            archive.trace.dropped = 3
            await archive.close('stopped')
            resumed = RunArchive.resume(archive.path)
            async with open_runtime(Config(db=resumed.db, fast_delay=0, deep_delay=0),
                                    resumed.observe_output, trace=resumed.trace) as runtime:
                await resumed.capture(runtime)
                await (await runtime.submit(UserMessage('new message')))
                await runtime.close()
                await resumed.capture(runtime)
            await resumed.close('completed')
            reader = RunReader(archive.path)
            events = [reader.load(r)['data']['event']['event_id'] for r in reader.rows
                      if r['kind'] == 'runtime.journal']
            self.assertEqual(len(events), len(set(events)))
            self.assertEqual(reader.manifest['omitted_records'], 3)
            self.assertIn('previous loss', reader.manifest['capture_error'])

    async def test_crash_partial_and_recovered_cancellation_remain_visible(self):
        from dataclasses import asdict
        from vtuber.contracts.events import Event
        from vtuber.runtime.journal import Journal
        with tempfile.TemporaryDirectory() as folder:
            archive = RunArchive.create(Path(folder), Config(), scenario={'id': 'test'})
            message = UserMessage('hi')
            journal = Journal(archive.db)
            journal.append(message.as_event())
            journal.append(Event.create('primary', 'character.reply.started', {'snapshot_revision': 0},
                event_id='reply_started_'+message.event_id, turn_id=message.turn_id))
            archive.trace('fast.started', message.turn_id, {'message': asdict(message)})
            archive.trace('fast.progress', message.turn_id, {'partial': 'hel'})
            # A crash leaves durable input and captured partial text without a terminal event.
            journal.close()
            await archive.close('stopped')
            before = RunReader(archive.path)
            self.assertEqual(before.conversation[-1]['status'], 'interrupted')
            resumed = RunArchive.resume(archive.path)
            async with open_runtime(Config(db=resumed.db), resumed.observe_output,
                                    trace=resumed.trace) as runtime:
                await resumed.capture(runtime)
            await resumed.close('stopped')
            reader = RunReader(archive.path)
            reply = next(r for r in reader.conversation if r['role'] == 'assistant')
            self.assertEqual(reply['status'], 'interrupted')
            self.assertEqual(reply['text'], 'hel')
            self.assertEqual(reply['reason'], 'process_restarted')
            self.assertEqual(sum(r['role'] == 'assistant' for r in reader.conversation), 1)

    async def test_simulator_call_and_message_share_correlation(self):
        from unittest.mock import patch
        from vtuber.lab.simulation import SimulationController
        from vtuber.lab.simulator import OMPUserSimulator
        from vtuber.minds.omp import OMPSettings
        records = []
        class Transport:
            def __init__(self, *args, **kwargs):
                pass
            async def request(self, prompt, *, request_id):
                records.append(('simulator.omp.context', request_id, {}))
                return '{"kind":"message","text":"hello"}'
            async def close(self):
                pass
        async def submit(message):
            pass
        sink = lambda kind, rid, data: records.append((kind, rid, data))
        controller = SimulationController(OMPUserSimulator(OMPSettings(), {}, trace=sink),
            submit, character_id='primary', trace=sink,
            wait=lambda seconds: asyncio.sleep(0))
        with patch('vtuber.lab.simulator.OMPTransport', Transport):
            await controller.run(turns=1, duration_seconds=2)
        action = next(r for r in records if r[0] == 'simulator.action')
        prompt = next(r for r in records if r[0] == 'simulator.prompt')
        self.assertEqual(action[1], prompt[1])
        self.assertEqual({rid for kind, rid, data in records if kind in
            ('simulator.prompt', 'simulator.response', 'simulator.action', 'simulator.omp.context')}, {prompt[1]})
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            for record in records:
                trace(*record)
            turn = controller.history[0].turn_id
            self.assertIn('simulator.prompt', [r['kind'] for r in RunReader(trace.path).related(turn)])
