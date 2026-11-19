import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from vtuber.contracts.events import Event
from vtuber.minds.m6_context import SingleContext, TokenBudget
from vtuber.runtime.journal import Journal
from vtuber.runtime.handoff import HandoffWorker


def add_turn(journal, name, text, action='speak'):
    message = journal.append(Event.create('primary', 'user.message.completed', {'text': text}, turn_id=name))
    reply = journal.append(Event.create('primary', 'character.reply.completed', {
        'text': 'Reply' if action == 'speak' else '', 'action': action, 'tool_call_id': f'call_{name}',
    }, turn_id=name, causation_id=message.event_id))
    return message, reply


class ContextTests(unittest.TestCase):
    def test_luna_estimates_multibyte_content_and_tool_schema(self):
        try:
            budget = TokenBudget.luna()
        except ImportError:
            self.skipTest('Luna tokenizer extra is unavailable')
        text = 'Привіт, світ! こんにちは'
        self.assertGreater(budget.count(text), 0)
        self.assertLess(budget.count(text), len(text.encode('utf-8')))
        self.assertGreater(budget.base(({'role': 'system', 'content': text},)), budget.count(text))

    def test_recap_and_whole_turns_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'conversation.sqlite3'
            with closing(Journal(path)) as journal:
                _, first = add_turn(journal, 'first', 'Original')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TABLE context_recap')
                db.execute('PRAGMA user_version=2')
            with closing(Journal(path)) as journal:
                self.assertEqual(journal.read_recap('primary'), (0, ''))
                self.assertTrue(journal.commit_recap('primary', 0, first.sequence, 'Early agreement'))
                self.assertFalse(journal.commit_recap('primary', 0, first.sequence, 'Stale'))
                add_turn(journal, 'second', 'Незавершена думка…', 'stay_silent')
            with closing(Journal(path)) as journal:
                context = SingleContext('Identity', TokenBudget(len, 5000))
                projection = context.project(journal.iter_dialogue_newest_first('primary', after=first.sequence),
                                             journal.read_recap('primary')[1], lookup=journal.get)
                self.assertEqual([message['role'] for message in projection.messages],
                                 ['system', 'user', 'user', 'assistant', 'toolResult'])
                self.assertIn('Early agreement', projection.messages[1]['content'])
                self.assertEqual(projection.messages[2]['content'], 'Незавершена думка…')
                self.assertEqual(projection.messages[4]['toolCallId'], 'call_second')
                self.assertFalse(projection.omitted)
                self.assertEqual(journal.get(first.event_id), first)

    def test_budget_discards_the_entire_old_turn(self):
        with closing(Journal(':memory:')) as journal:
            add_turn(journal, 'first', 'x' * 3000)
            current = journal.append(Event.create('primary', 'user.message.completed', {'text': 'Now'}, turn_id='now'))
            context = SingleContext('Identity', TokenBudget(len, 2500))
            projection = context.project(journal.iter_dialogue_newest_first('primary'), '', current=current)
            self.assertTrue(projection.omitted)
            self.assertEqual([m['role'] for m in projection.messages], ['system', 'user'])
            self.assertEqual(projection.messages[-1]['content'], 'Now')


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_handoff_snapshots_old_turns_and_cancels_before_commit(self):
        with closing(Journal(':memory:')) as journal:
            _, first = add_turn(journal, 'first', 'Early agreement ' * 75)
            add_turn(journal, 'second', 'Keep this exact ' * 50)
            add_turn(journal, 'quiet', 'An unfinished thought ' * 70, 'stay_silent')
            entered, release = asyncio.Event(), asyncio.Event()
            traces = []

            async def summarize(messages):
                self.assertIn('Early agreement', str(messages))
                self.assertNotIn('Keep this exact', str(messages))
                self.assertNotIn('An unfinished thought', str(messages))
                entered.set()
                await release.wait()
                return 'Early agreement'

            worker = HandoffWorker('primary', journal, SingleContext('Identity', TokenBudget(len, 3000)),
                                   summarize, lambda kind, _, data: traces.append((kind, data)))
            self.addAsyncCleanup(worker.close)
            worker.schedule()
            await asyncio.wait_for(entered.wait(), 1)
            new = journal.append(Event.create('primary', 'user.message.completed',
                                              {'text': 'Arrived while computing'}, turn_id='new'))
            self.assertEqual(journal.read_recap('primary'), (0, ''))
            await worker.close()
            self.assertEqual(journal.read_recap('primary'), (0, ''))
            entered.clear()
            worker = HandoffWorker('primary', journal, SingleContext('Identity', TokenBudget(len, 3000)),
                                   summarize, lambda kind, _, data: traces.append((kind, data)))
            self.addAsyncCleanup(worker.close)
            worker.schedule()
            await asyncio.wait_for(entered.wait(), 1)
            release.set()
            await asyncio.wait_for(worker.task, 1)
            self.assertEqual(journal.read_recap('primary'), (first.sequence, 'Early agreement'))
            self.assertEqual(journal.get(new.event_id), new)
            self.assertNotIn('Early agreement', str(traces))

    async def test_failed_handoff_retries_after_three_completed_turns(self):
        with closing(Journal(':memory:')) as journal:
            for i in range(4):
                add_turn(journal, f'old{i}', 'History ' * 100)
            attempts = 0

            async def summarize(_):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError('Provider failed')
                return 'Saved'

            worker = HandoffWorker('primary', journal, SingleContext('Identity', TokenBudget(len, 3000)),
                                   summarize)
            self.addAsyncCleanup(worker.close)
            worker.schedule()
            await asyncio.wait_for(worker.task, 1)
            self.assertEqual(journal.read_recap('primary'), (0, ''))
            for i in range(3):
                add_turn(journal, f'new{i}', 'New')
                worker.schedule(completed=True)
                await asyncio.wait_for(worker.task, 1)
                self.assertEqual(attempts, 1 if i < 2 else 2)
            self.assertEqual(journal.read_recap('primary')[1], 'Saved')
