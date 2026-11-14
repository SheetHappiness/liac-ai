import json
import unittest
from dataclasses import replace

from vtuber.contracts.context import ContextEpoch, ContextItem
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

    def test_projection_retains_evidence_without_duplicates(self):
        def event(kind, payload, sequence):
            return replace(Event.create('primary', kind, payload, event_id=f'id{sequence}',
                occurred_at=f'2026-11-14T12:00:{sequence:02d}+00:00'), sequence=sequence,
                recorded_at='database timestamp')
        old = event('user.message.completed', {'text': '  old 🐈\n'}, 1)
        reply = event('character.reply.completed', {'text': 'Exact reply'}, 2)
        user = event('user.message.completed', {'text': 'new'}, 3)
        cancelled = event('character.reply.cancelled', {'reason': 'preempted'}, 4)
        started = event('character.initiative.started', {'intent': 'A thought', 'proposal_id': 'secret'}, 5)
        failed = event('character.reply.failed', {'reason': 'error'}, 6)
        pending = event('initiative.proposed', {'intent': 'Next thought', 'ready_at': '2026-11-14T13:00:00+00:00'}, 7)
        epoch = ContextEpoch(1, 0, (ContextItem('Current epoch', ()),))
        prior = ContextEpoch(2, 0, (ContextItem('Recovered epoch', ()),))
        request = DeepRequest('private-id', FastSnapshot(CharacterState('primary', 3, 'Context'), 6,
            (old, reply, user), epoch), 2, (user, cancelled, started, failed),
            CompactionInput(4, (old, reply, user)), 2048, False, pending, prior)
        data = json.loads(render_request(request))
        self.assertEqual(data['working_context'], 'Context')
        self.assertEqual(data['epoch'], ['Current epoch'])
        self.assertEqual(data['compaction']['prior_epoch'], ['Recovered epoch'])
        self.assertEqual(data['compaction']['through'], {'history': 2, 'new': 2})
        self.assertEqual([x.get('text') for x in data['history']], ['  old 🐈\n', 'Exact reply'])
        self.assertEqual([x.get('status') for x in data['new']], [None, 'cancelled', 'started', 'failed'])
        self.assertEqual(data['new'][2]['intent'], 'A thought')
        self.assertEqual(data['new'][3]['reason'], 'error')
        self.assertEqual(data['new'][0]['occurred_at'], user.occurred_at)
        self.assertEqual(data['initiative']['pending'], {'intent': 'Next thought', 'ready_at': pending.payload['ready_at']})
        self.assertFalse(data['initiative']['allowed'])
        self.assertIn('current_time', data)
        self.assertIn('timezone', data)
        self.assertNotIn('database timestamp', json.dumps(data))
        self.assertNotIn('private-id', json.dumps(data))
        self.assertNotIn('secret', json.dumps(data))
        self.assertEqual(request.events[0], user)

    def test_ordinary_prompt_has_no_compaction(self):
        request = replace(self.request, compaction=None)
        data = json.loads(render_request(request))
        self.assertIsNone(data['compaction'])
        self.assertEqual(data['history'], [])
        self.assertEqual(data['new'][0]['text'], 'green hat')
        self.assertEqual(data['new'][0]['speaker'], 'user')


class FakeDeepTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_uses_new_request(self):
        from vtuber.minds.fake import FakeDeep
        event = Event.create('primary', 'user.message.completed', {'text': 'green'}, event_id='source')
        request = DeepRequest('id', FastSnapshot(CharacterState('primary'), 1, (event,)), 0, (event,))
        result = await FakeDeep(0).propose(request)
        self.assertEqual(result.request_id, 'id')
        self.assertEqual(result.note, 'Last user message: green')
