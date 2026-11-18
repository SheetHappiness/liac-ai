import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from vtuber.tracing import TraceRecorder, read_trace


class TraceTests(unittest.TestCase):
    def test_saved_payload_is_immutable_and_limit_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder), max_bytes=4096)
            payload = {'nested': ['green']}
            trace('test.capture', 'turn', payload)
            payload['nested'].append('blue')
            rows = read_trace(trace.path)
            self.assertEqual(json.loads((trace.path / rows[0]['file']).read_text(encoding='utf-8'))['data'],
                             {'nested': ['green']})
            trace('test.capture', 'too-large', {'text': 'x' * 4096})
            self.assertIn('limit', trace.error)
            self.assertEqual(len(read_trace(trace.path)), 1)

    def test_partial_index_line_is_not_a_completed_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'index.jsonl').write_text('{"kind":', encoding='utf-8')
            rows = read_trace(path)
            self.assertEqual(rows[0]['kind'], 'capture.gap')
            self.assertIn('Incomplete', rows[0]['capture_gap'])

    def test_trace_directory_failure_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'not-a-directory'
            root.write_text('occupied', encoding='utf-8')
            trace = TraceRecorder(root)
            trace('test.capture', 'turn', {'prompt': 'hello'})
            self.assertIn('capture stopped', trace.error)

    def test_history_rejects_paths_outside_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'run'
            path.mkdir()
            (root / 'private.json').write_text('{}', encoding='utf-8')
            (path / 'index.jsonl').write_text(json.dumps({'file': '../private.json', 'sequence': 1,
                'kind': 'test.capture', 'request_id': 'turn', 'time': 'today'}) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_trace(path)


class RuntimeTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_capture_is_immutable_bounded_and_off_loop(self):
        from threading import Event
        from vtuber.tracing import QueuedTraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = QueuedTraceRecorder(Path(folder))
            entered, release = Event(), Event()
            original = trace.recorder.__class__.__call__
            from unittest.mock import patch
            def held(writer, *args):
                entered.set()
                release.wait(5)
                original(writer, *args)
            try:
                with patch.object(type(trace.recorder), '__call__', held):
                    data = {'nested': ['green']}
                    trace('test', 'first', data)
                    data['nested'].append('blue')
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    for i in range(300):
                        trace('test', str(i), {})
                    self.assertIn('queue', trace.error)
                    release.set()
                    await trace.aclose()
            finally:
                release.set()
                await trace.aclose()
            self.assertFalse(trace.thread.is_alive())
            row = read_trace(trace.path)[0]
            self.assertEqual(json.loads((trace.path/row['file']).read_text())['data']['nested'], ['green'])
