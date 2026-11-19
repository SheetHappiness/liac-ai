import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from uuid import uuid4

from test_m62_context import add_turn
from vtuber.contracts.events import RuntimeOutput
from vtuber.contracts.perception import PerceptionBatch
from vtuber.hub import read_replay, resume_journal, send, transcript
from vtuber.runtime.journal import Journal


class HubTests(unittest.TestCase):
    def test_preview_preserves_runtime_output_kind(self):
        stream = StringIO()
        with redirect_stdout(stream):
            send('preview', **asdict(RuntimeOutput('reply.delta', 'primary', 'turn', 'Hi', 1)))
        frame = json.loads(stream.getvalue())
        self.assertEqual((frame['type'], frame['kind'], frame['text']), ('preview', 'reply.delta', 'Hi'))

    def test_transcript_routes_through_journal_and_replays_with_damaged_trace(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            identifier = str(uuid4())
            item = transcript({'id': identifier, 'text': '  Привіт  ', 'source': 'discord'})
            self.assertEqual((item.kind, item.source, item.delivery), ('voice', 'electron', 'direct'))
            with closing(Journal(path / 'journal.sqlite3')) as journal:
                event = journal.accept_local_perceptions('primary', PerceptionBatch('local', (item,), 'quiet'))
            (path / '00000001.json').write_text('{"data": {}}', encoding='utf-8')
            bad_time = dict(sequence=1, time='bad timestamp', kind='batch.closed',
                            request_id='batch', file='00000001.json')
            for index in ('invalid', json.dumps(bad_time)):
                with self.subTest(index=index):
                    (path / 'index.jsonl').write_text(index + '\n', encoding='utf-8')
                    frames = []
                    read_replay(path, lambda kind, **data: frames.append((kind, data)))
                    recorded = [frame['event'] for kind, frame in frames if kind == 'journal']
                    self.assertEqual(recorded[-1]['turn_id'], event.turn_id)
                    self.assertEqual(recorded[-1]['payload']['text'], 'Привіт')
                    self.assertTrue(any(kind == 'trace' and frame['row'].get('capture_gap')
                                        for kind, frame in frames))

    def test_invalid_transcript_rejected(self):
        for value in ('', '   ', 'x' * 8001, '\ud800'):
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                transcript({'id': str(uuid4()), 'text': value})

    def test_resume_copies_journal_and_recap_without_sharing_writes(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'previous'
            resumed = Path(root) / 'new'
            resumed.mkdir()
            with closing(Journal(source / 'journal.sqlite3')) as journal:
                _, reply = add_turn(journal, 'first', 'Previously agreed')
                journal.commit_recap('primary', 0, reply.sequence, 'An agreement')
                resume_journal(source, resumed / 'journal.sqlite3')
                with closing(Journal(resumed / 'journal.sqlite3')) as copy:
                    self.assertEqual(copy.read('primary'), journal.read('primary'))
                    self.assertEqual(copy.read_recap('primary'), journal.read_recap('primary'))
                    add_turn(copy, 'resumed', 'Continue here')
                self.assertEqual(journal.high_watermark('primary'), reply.sequence)
