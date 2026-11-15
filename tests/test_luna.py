import json
import unittest
from dataclasses import replace

from vtuber.contracts.deep import CompactionInput, DeepRequest, DeepResult, InitiativeCancel, InitiativeSpeak
from vtuber.contracts.events import Event
from vtuber.contracts.state import CharacterState, FastSnapshot
from vtuber.minds.luna import parse_result, render_request


class LunaParserTests(unittest.TestCase):
    def setUp(self):
        self.event = replace(Event.create('primary', 'user.message.completed', {'text': 'green hat'}, event_id='source'), sequence=1)
        self.request = DeepRequest('request', FastSnapshot(CharacterState('primary', 2), 1,
            (self.event,)), 0, (self.event,), CompactionInput(1, (self.event,)))

    def parse(self, **changes):
        data = dict(schema_version=3, note=None, compaction=None, initiative=None)
        return parse_result(json.dumps({**data, **changes}, ensure_ascii=False), self.request)

    def test_parse_note_and_summary(self):
        result = self.parse(note='Remember green.', compaction='Hat is green.')
        self.assertEqual(result.note, 'Remember green.')
        self.assertEqual(result.compaction, 'Hat is green.')

    def test_markdown_replace_clear_and_utf8_limit(self):
        for text in ('', '  # Custom\n' + 'x'*1100 + '\n ', '\U0001f642'*8192):
            self.assertEqual(self.parse(note=text).note, text)
        with self.assertRaises(ValueError):
            self.parse(note='\U0001f642'*8193)

    def test_explicit_noop(self):
        self.assertEqual(self.parse(), DeepResult(3, 'request'))

    def test_initiative_actions_and_boundaries(self):
        self.assertEqual(self.parse(initiative=dict(action='speak', intent='A hat joke')).initiative,
                         InitiativeSpeak('A hat joke'))
        self.assertIsNone(self.parse(initiative=dict(action='none')).initiative)
        self.assertEqual(self.parse(initiative=dict(action='cancel')).initiative, InitiativeCancel())
        for delay in (True, -1, float('inf')):
            with self.assertRaises(ValueError):
                self.parse(initiative=dict(action='speak', intent='hat', delay_seconds=delay))

    def test_reject_untrusted_json(self):
        for changes in (dict(schema_version=True), dict(schema_version=1), dict(note=True),
                        dict(note={'text':'old envelope'}), dict(note='x'*32769),
                        dict(compaction='x'*8001), dict(tools=[]),
                        dict(initiative=dict(action='speak', intent='hat', source_event_ids=['x']))):
            with self.subTest(changes=str(changes)[:100]), self.assertRaises(ValueError):
                self.parse(**changes)
        for text in ('{} trailing', '```json\n{}\n```', ' '*65537,
                     '{"schema_version":3,"schema_version":3,"note":null,"compaction":null,"initiative":null}'):
            with self.assertRaises(ValueError):
                parse_result(text, self.request)

    def test_prompt_quotes_evidence(self):
        text = render_request(self.request)
        self.assertIn('green hat', text)
        self.assertEqual(json.loads(text)['request_id'], 'request')


class FakeDeepTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_uses_new_request(self):
        from vtuber.minds.fake import FakeDeep
        event = Event.create('primary', 'user.message.completed', {'text': 'green'}, event_id='source')
        request = DeepRequest('id', FastSnapshot(CharacterState('primary'), 1, (event,)), 0, (event,))
        result = await FakeDeep(0).propose(request)
        self.assertEqual(result.request_id, 'id')
        self.assertEqual(result.note, 'Last user message: green')
