import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from test_perception import batch, perception
from vtuber.contracts.events import Event
from vtuber.minds.m6_context import build_m6_messages
from vtuber.runtime.journal import EventConflict, Journal


def reply(text, **payload):
    return Event.create('primary', 'character.reply.completed', {'text': text, **payload},
                        occurred_at='2026-11-18T00:00:00+00:00')


def user(text):
    return Event.create('primary', 'user.message.completed', {'text': text})


class M6ContextTests(unittest.TestCase):
    def test_m6_opens_existing_v2_journal_without_writing_legacy_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'm6.sqlite3'
            previous = reply('Earlier reply', action='speak', tool_call_id='earlier-call')
            with closing(Journal(path)) as journal:
                journal.append(previous)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS character_state (character_id TEXT PRIMARY KEY, "
                           "revision INTEGER, context_note TEXT, deep_cursor INTEGER)")
                db.execute("INSERT OR REPLACE INTO character_state VALUES ('primary', 7, 'Old note', 42)")
            with closing(Journal(path)) as journal:
                self.assertEqual(journal.get(previous.event_id).payload, previous.payload)
                message = journal.accept_local_perceptions('another', batch(perception('new')))
                self.assertEqual(journal.get(message.event_id).payload['perception_ids'], ['new'])
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT * FROM character_state').fetchall(),
                                 [('primary', 7, 'Old note', 42)])

    def test_ingestion_preserves_provenance_and_rolls_back_conflicts(self):
        first = perception('one', content='first')
        ambient = perception('ambient', delivery='ambient')
        second = perception('two', content='second')
        with closing(Journal(':memory:')) as journal:
            accept = journal.accept_local_perceptions
            first_message = accept('primary', batch(first, ambient, first))
            self.assertEqual(first_message.payload['perception_ids'], ['one', 'ambient'])
            self.assertEqual([e.event_id for e in journal.read('primary')],
                             ['one', 'ambient', first_message.event_id])
            self.assertEqual(journal.get('one').occurred_at, first.occurred_at)
            self.assertIsNone(accept('primary', batch(ambient, first)))
            with self.assertRaises(EventConflict):
                accept('primary', batch(second, replace(first, content='conflict')))
            with self.assertRaises(EventConflict):
                accept('primary', batch(second, replace(first, author_id='other')))
            self.assertIsNone(journal.get('two'))
            self.assertEqual(accept('primary', batch(first, second)).payload['perception_ids'], ['two'])

    def test_m6_tool_replay_uses_stable_call_id(self):
        event = reply('Hello!', action='speak', tool_call_id='call_real|fc_real')
        _, call, result = build_m6_messages('You are Liac.', (event,))
        self.assertEqual(call['content'], [{'type': 'toolCall', 'name': 'speak',
                                           'id': 'call_real|fc_real', 'arguments': {'message': 'Hello!'}}])
        self.assertEqual((call['role'], call['api'], call['provider'], call['model'], call['stopReason']),
                         ('assistant', 'openai-codex-responses', 'openai-codex', 'gpt-6-luna', 'toolUse'))
        self.assertEqual(result['role'], 'toolResult')
        self.assertEqual(result['toolCallId'], 'call_real|fc_real')
        self.assertEqual(result['toolName'], 'speak')
        self.assertFalse(result['isError'])
        self.assertEqual(build_m6_messages('You are Liac.', (event,))[1:], (call, result))

    def test_consecutive_silences_preserve_user_fragments(self):
        dialogue = (
            user('I wanted to ask...'),
            reply('', action='stay_silent', tool_call_id='quiet-1'),
            user('...about Warsaw, specifically...'),
            reply('', action='stay_silent', tool_call_id='quiet-2'),
            user('...how do I get from Chopin Airport to the city centre?'),
        )
        _, first, call1, result1, second, call2, result2, latest = build_m6_messages('Identity', dialogue)
        self.assertEqual([(message['role'], message['content']) for message in (first, second, latest)], [
            ('user', 'I wanted to ask...'),
            ('user', '...about Warsaw, specifically...'),
            ('user', '...how do I get from Chopin Airport to the city centre?'),
        ])
        for call, result, call_id in ((call1, result1, 'quiet-1'), (call2, result2, 'quiet-2')):
            self.assertEqual(call['role'], 'assistant')
            self.assertEqual(call['content'], [{'type': 'toolCall', 'name': 'stay_silent',
                                               'id': call_id, 'arguments': {}}])
            self.assertEqual((result['role'], result['toolCallId'], result['toolName']),
                             ('toolResult', call_id, 'stay_silent'))

    def test_legacy_reply_remains_plain_text(self):
        ended = ('character.reply.cancelled', 'character.reply.failed')
        events = (reply('Legacy'), *(Event.create('primary', kind, {'text': 'preview'}) for kind in ended))
        _, legacy = build_m6_messages('Identity', events)
        self.assertEqual(legacy['role'], 'assistant')
        self.assertEqual(legacy['content'], [{'type': 'text', 'text': 'Legacy'}])

    def test_current_user_message_only_once(self):
        current = user('Latest')
        system, message = build_m6_messages('You are Liac.', (current,))
        self.assertEqual(system['role'], 'system')
        self.assertTrue(system['content'].startswith('You are Liac.'))
        self.assertIn('stay_silent', system['content'])
        self.assertEqual((message['role'], message['content']), ('user', 'Latest'))

    def test_oversized_history_cannot_block_next_turn(self):
        oversized = '⚙"' * 20_000
        current = user('Latest')
        previous = reply('Short reply', action='speak', tool_call_id='call_previous')
        messages = build_m6_messages('Identity', (user(oversized), previous, current))
        self.assertEqual([message['role'] for message in messages], ['system', 'assistant', 'toolResult', 'user'])
        self.assertEqual(messages[-1]['content'], 'Latest')
        self.assertLess(len(json.dumps(messages, ensure_ascii=False).encode()), 64 * 1024)
        with self.assertRaises(ValueError):
            build_m6_messages('Identity', (user(oversized),))
