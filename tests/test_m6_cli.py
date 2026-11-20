import asyncio
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_single_mind import ScriptedMind
from vtuber.contracts.mind import MindDecision
from vtuber.cli import FakeSingleMind, run_console
from vtuber.runtime.journal import Journal


class EntryPointTests(unittest.TestCase):
    def test_default_and_m6_alias_start_the_same_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            for module in ('vtuber', 'vtuber.m6'):
                with self.subTest(module=module):
                    db = Path(folder) / f'{module}.sqlite3'
                    result = subprocess.run(
                        (sys.executable, '-m', module, '--db', str(db)),
                        input='Hello\n/quit\n', capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Liac Single Mind', result.stdout)
                    self.assertIn('[Final] You said: Hello', result.stdout)
                    with closing(Journal(db)) as journal:
                        self.assertEqual([e.payload['action'] for e in journal.read('primary')
                                          if e.kind == 'character.reply.completed'], ['speak'])


class M6ConsoleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = Path(directory) / 'm6.sqlite3'
        self.output = self.enterContext(redirect_stdout(io.StringIO()))

    def events(self, kind):
        with closing(Journal(self.db)) as journal:
            return tuple(event for event in journal.read('primary') if event.kind == kind)

    async def test_fake_console_burst_one_reply(self):
        async def lines():
            for line in ('first', 'second', 'third', '/quit'):
                yield line

        mind = FakeSingleMind()
        with patch('vtuber.cli.input_lines', lines), patch.object(mind, 'generate', wraps=mind.generate) as generate:
            await run_console(self.db, mind)
        self.assertEqual(generate.await_count, 1)
        user, = self.events('user.message.completed')
        reply, = self.events('character.reply.completed')
        self.assertEqual(user.payload['text'], 'first\nsecond\nthird')
        self.assertEqual(reply.payload['action'], 'speak')
        rendered = self.output.getvalue()
        self.assertEqual(rendered.count('[Provisional] '), 1)
        self.assertEqual(rendered.count('[Final] '), 1)

    async def test_quit_drains_then_closes(self):
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def lines():
            for line in ('last', '/quit', 'ignored'):
                yield line

        async def silence(messages, preview):
            entered.set()
            await finish.wait()
            return MindDecision('stay_silent', tool_call_id='quiet')

        with patch('vtuber.cli.input_lines', lines):
            async with asyncio.TaskGroup() as group:
                console = group.create_task(run_console(self.db, ScriptedMind(silence)))
                await asyncio.wait_for(entered.wait(), 2)
                self.assertFalse(console.done())
                finish.set()
        user, = self.events('user.message.completed')
        reply, = self.events('character.reply.completed')
        self.assertEqual(user.payload['text'], 'last')
        self.assertEqual(reply.payload['action'], 'stay_silent')
        self.assertNotIn('[Final]', self.output.getvalue())

    async def test_stdin_keeps_reading_during_generation(self):
        entered = asyncio.Event()
        queued = asyncio.Event()

        async def lines():
            yield 'first'
            await asyncio.wait_for(entered.wait(), 3)
            yield 'second'
            yield 'third'
            queued.set()
            yield '/quit'

        async def held(messages, preview):
            entered.set()
            await asyncio.wait_for(queued.wait(), 1)
            return MindDecision('speak', 'First', 'first-id')

        mind = ScriptedMind(held, MindDecision('speak', 'Second', 'second-id'))
        with patch('vtuber.cli.input_lines', lines):
            await asyncio.wait_for(run_console(self.db, mind), 5)
        self.assertEqual(self.events('character.reply.cancelled'), ())
        self.assertEqual([event.payload['text'] for event in self.events('user.message.completed')],
                         ['first', 'second\nthird'])
        self.assertEqual([event.payload['text'] for event in self.events('character.reply.completed')],
                         ['First', 'Second'])
        self.assertEqual(len(mind.calls), 2)

    async def test_interrupted_console_cancels_active_and_drains_queue_to_journal(self):
        entered = asyncio.Event()
        queued = asyncio.Event()

        async def lines():
            yield 'active'
            await entered.wait()
            yield 'queued'
            queued.set()
            await asyncio.Future()

        async def held(messages, preview):
            entered.set()
            await asyncio.Future()

        mind = ScriptedMind(held)
        with patch('vtuber.cli.input_lines', lines):
            console = asyncio.create_task(run_console(self.db, mind))
            try:
                await asyncio.wait_for(queued.wait(), 4)
            finally:
                console.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(console, 2)
        self.assertEqual([event.payload['text'] for event in self.events('user.message.completed')],
                         ['active', 'queued'])
        self.assertEqual([event.payload['reason'] for event in self.events('character.reply.cancelled')],
                         ['shutdown', 'shutdown'])
        self.assertEqual(len(mind.calls), 1)
