import asyncio
import tempfile
import unittest
from pathlib import Path

from vtuber.app import Config, open_runtime
from vtuber.contracts.events import UserMessage
from vtuber.lab.archive import RunArchive, RunReader
from vtuber.tracing import TraceRecorder, read_trace


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_index_is_a_gap_but_empty_segment_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            for active in (True, False):
                with self.subTest(active=active):
                    archive = RunArchive.create(Path(folder), Config())
                    if active:
                        archive.trace('fast.started', 't', {'message': {'text': 'hello'}})
                        archive.trace('deep.started', 'd', {'request': {'events': []}})
                    await archive.close('completed')
                    if active:
                        (archive.path/'index.jsonl').unlink()
                        self.assertTrue(RunReader(archive.path).gaps)
                        self.assertEqual(read_trace(archive.path)[0]['kind'], 'capture.gap')
                        # Manifest evidence must survive loss of every payload too.
                        for payload in archive.path.glob('[0-9]*.json'):
                            payload.unlink()
                    reader = RunReader(archive.path)
                    self.assertEqual(reader.summary()['partial'], active)
                    self.assertEqual(bool(reader.gaps), active)
            archive = RunArchive.create(Path(folder), Config(), scenario={'id': 'test'})
            archive.db.touch()
            await archive.close('stopped')
            resumed = RunArchive.resume(archive.path)
            try:
                self.assertFalse(RunReader(archive.path).gaps)
            finally:
                await resumed.close('completed')

    async def test_journal_terminals_restore_results_without_inventing_metrics(self):
        from dataclasses import asdict
        from vtuber.contracts.events import Event
        with tempfile.TemporaryDirectory() as folder:
            for status in ('completed', 'cancelled', 'failed'):
                with self.subTest(status=status):
                    trace = TraceRecorder(Path(folder))
                    trace('fast.started', 't', {'message': {'text': 'hello'}})
                    trace('fast.progress', 't', {'partial': 'hel'})
                    payload = {'text': 'hello world'} if status == 'completed' else {'reason': 'test reason'}
                    event = Event.create('primary', 'character.reply.'+status, payload, turn_id='t')
                    trace('runtime.journal', 't', {'event': asdict(event)})
                    reader = RunReader(trace.path)
                    reply = next(r for r in reader.conversation if r['role'] == 'assistant')
                    self.assertEqual(reply['status'], status)
                    self.assertEqual(reply['text'], 'hello world' if status == 'completed' else 'hel')
                    self.assertEqual(reply['provenance'], 'journal_terminal')
                    self.assertIsNone(reader.summary()['fast']['output_tokens'])
                    trace('fast.finished', 't', {'status': status, 'text': payload.get('text', ''),
                        'partial': 'hel', 'metrics': {'generation': {'output_tokens': 2}}})
                    reader = RunReader(trace.path)
                    self.assertEqual(sum(r['role'] == 'assistant' for r in reader.conversation), 1)
                    self.assertEqual(reader.summary()['fast']['output_tokens'], 2)

    async def test_resume_keeps_incomplete_status_in_simulator_prompt(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from vtuber.lab.host import LabHost
        from vtuber.lab.simulator import render_simulator_prompt
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            trace('fast.started', 't', {'message': {'text': 'hi'}})
            trace('fast.progress', 't', {'partial': 'Well, I think...'})
            host = LabHost(Config(), Path(folder), simulation={'scenario': {}, 'turns': 1}, resume=trace.path)
            host.archive = SimpleNamespace(path=trace.path, manifest={}, trace=None)
            host.runtime = SimpleNamespace(submit=AsyncMock())
            with patch('vtuber.lab.host.SimulationController.run', new=AsyncMock()):
                await host._start_controller()
                await host.simulation_task
            prompt = render_simulator_prompt(tuple(host.controller.history), session=1, remaining_turns=1)
            import json
            reply = next(r for r in json.loads(prompt)['visible_conversation'] if r['role'] == 'assistant')
            self.assertEqual(reply['text'], 'Well, I think...')
            self.assertEqual(reply['status'], 'interrupted')

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
            self.assertEqual(reply['status'], 'cancelled')
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
