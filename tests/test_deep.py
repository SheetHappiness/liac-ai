import tempfile
import unittest
import asyncio
from unittest.mock import patch
from pathlib import Path

from vtuber.contracts.deep import DeepResult
from vtuber.contracts.events import Event, UserMessage
from vtuber.runtime.journal import EventConflict, Journal
from vtuber.runtime.deep import DeepWorker
from vtuber.minds.fake import FakeFast
from vtuber.runtime.orchestrator import Runtime


class DeepJournalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.journal = Journal(Path(self.folder.name) / 'deep.db')
        self.addCleanup(self.journal.close)

    def user(self, text='hello'):
        message = UserMessage(text)
        self.journal.append(message.as_event())
        return message

    def finish(self, message, kind='completed'):
        return self.journal.append(Event.create('primary', 'character.reply.'+kind,
            {'text': 'actual reply'} if kind == 'completed' else {'reason': 'test'},
            turn_id=message.turn_id, causation_id=message.event_id))

    def result(self, request, compact=False):
        return DeepResult(3, request.request_id, 'new note', 'summary' if compact else None)

    def test_markdown_replace_clear_and_no_change(self):
        from dataclasses import replace
        for index, (text, revision, reason) in enumerate([
                ('  # Custom\n' + 'x'*1100 + '\n ', 1, 'changed'),
                ('  # Custom\n' + 'x'*1100 + '\n ', 1, 'unchanged'),
                ('', 2, 'changed'), ('', 2, 'unchanged'), (None, 2, 'unchanged')]):
            self.finish(self.user())
            request = self.journal.deep_request('primary', request_id=f'markdown-{index}')
            result = self.result(request)
            result = replace(result, note=text)
            decision = self.journal.apply_deep(request, result)
            self.assertEqual(decision['context'], reason)
            self.journal.close()
            self.journal = Journal(Path(self.folder.name) / 'deep.db')
            self.addCleanup(self.journal.close)
            self.assertEqual(self.journal.snapshot('primary').revision, revision)
            self.assertEqual(self.journal.snapshot('primary').context_note, text or '')
            self.assertGreaterEqual(self.journal.cursor('primary'), request.snapshot.through_sequence)

    def test_new_dialogue_does_not_invalidate_document(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='late-document')
        newer = self.user('Stop joking about this project.')
        decision = self.journal.apply_deep(request, self.result(request))
        self.assertEqual(decision['through'], request.snapshot.through_sequence)
        self.assertEqual(self.journal.cursor('primary'), request.snapshot.through_sequence)
        snapshot = self.journal.fast_snapshot('primary')
        self.assertIn(newer.event_id, [e.event_id for e in snapshot.recent_dialogue])
        from vtuber.context import ContextCompiler
        compiled = ContextCompiler('Current corrections outrank old suggestions.').compile(snapshot, UserMessage('next'))
        self.assertIn('Stop joking about this project.', [m.content for m in compiled.messages])
        self.assertIn('current user corrections take precedence', compiled.messages[-2].content)

    def test_closed_prefix_batching(self):
        first = self.user()
        self.assertIsNone(self.journal.deep_request('primary', request_id='open'))
        second = self.user('second')
        self.finish(first, 'cancelled')
        self.assertIsNone(self.journal.deep_request('primary', request_id='interleaved'))
        terminal = self.finish(second)
        request = self.journal.deep_request('primary', request_id='closed', max_events=1)
        self.assertEqual(request.snapshot.through_sequence, terminal.sequence)
        self.assertEqual(len(request.events), 4)
        self.assertEqual(request.events[-1].payload['text'], 'actual reply')

    def test_deep_atomic_rollback(self):
        from dataclasses import replace
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='atomic', compact=True)
        self.journal._db.execute("CREATE TRIGGER fail_deep BEFORE INSERT ON events WHEN json_extract(NEW.content, '$.kind')='deep.batch.completed' BEGIN SELECT RAISE(FAIL,'test'); END")
        for text in ('# Context\n' + 'x'*1100, ''):
            result = self.result(request, True)
            result = replace(result, note=text)
            with self.assertRaises(Exception):
                self.journal.apply_deep(request, result)
        self.assertEqual(self.journal.snapshot('primary').revision, 0)
        self.assertEqual(self.journal.context_epoch('primary').version, 0)
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.assertEqual(self.journal._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_deep_replay(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='replay')
        result = self.result(request)
        decision = self.journal.apply_deep(request, result)
        self.assertEqual(self.journal.apply_deep(request, result), decision)
        with self.assertRaises(EventConflict):
            self.journal.apply_deep(request, DeepResult(3, 'replay'))

    def test_initiative_atomic_replay_and_restart(self):
        from dataclasses import replace
        from vtuber.contracts.deep import InitiativeSpeak, InitiativeCancel
        message = self.user()
        self.finish(message)
        request = self.journal.deep_request('primary', request_id='initiative', initiative_allowed=True)
        result = replace(self.result(request), initiative=InitiativeSpeak('Ask about the hat'))
        self.journal._db.execute("CREATE TRIGGER fail_deep BEFORE INSERT ON events WHEN json_extract(NEW.content, '$.kind')='deep.batch.completed' BEGIN SELECT RAISE(FAIL,'test'); END")
        with self.assertRaises(Exception):
            self.journal.apply_deep(request, result)
        self.assertIsNone(self.journal.pending_initiative('primary'))
        self.assertEqual(self.journal.cursor('primary'), 0)
        self.journal._db.execute('DROP TRIGGER fail_deep')
        decision = self.journal.apply_deep(request, result)
        self.assertEqual(decision['initiative'], 'scheduled')
        pending = self.journal.pending_initiative('primary')
        self.assertEqual(self.journal.apply_deep(request, result), decision)
        with self.assertRaises(EventConflict):
            self.journal.apply_deep(request, DeepResult(3, request.request_id))
        # A compaction-only observer returning none must preserve identity and deadlines.
        noop = self.journal.deep_request('primary', request_id='none', compact=True, initiative_allowed=True)
        self.journal.apply_deep(noop, DeepResult(3, noop.request_id))
        self.assertEqual(self.journal.pending_initiative('primary'), pending)
        snapshot = self.journal.fast_snapshot('primary')
        initiative = self.journal.claim_initiative(pending.event_id, snapshot)
        self.assertIsNotNone(initiative)
        self.assertIsNone(self.journal.claim_initiative(pending.event_id, snapshot))
        self.assertEqual(self.journal.get('reply_started_'+initiative.event_id).payload['through_sequence'], snapshot.through_sequence)
        self.assertIsNone(self.journal.deep_request('primary', request_id='unfinished'))
        self.finish(initiative)
        cursor = self.journal.cursor('primary')
        self.assertIsNone(self.journal.deep_request('primary', request_id='no-self-loop'))
        self.assertEqual(self.journal.cursor('primary'), cursor)
        newer = self.user('next topic')
        self.finish(newer)
        request = self.journal.deep_request('primary', request_id='observe', initiative_allowed=True)
        self.assertIn(initiative.event_id, [e.event_id for e in request.events])
        self.assertTrue(any(e.kind == 'character.reply.completed' and e.turn_id == initiative.turn_id for e in request.events))
        self.journal.apply_deep(request, DeepResult(3, request.request_id, initiative=InitiativeSpeak('New idea')))
        pending = self.journal.pending_initiative('primary')
        # Luna receives pending work and can cancel it explicitly without an anchor.
        cancel = self.journal.deep_request('primary', request_id='withdraw', compact=True)
        self.assertEqual(cancel.pending_initiative, pending)
        self.journal.apply_deep(cancel, DeepResult(3, cancel.request_id, initiative=InitiativeCancel()))
        self.assertIsNone(self.journal.pending_initiative('primary'))
        self.assertIsNone(self.journal.claim_initiative(pending.event_id, self.journal.fast_snapshot('primary')))
        self.assertEqual(self.journal._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_late_initiative_does_not_reject_markdown(self):
        from dataclasses import replace
        from vtuber.contracts.deep import InitiativeSpeak
        message = self.user()
        self.finish(message)
        request = self.journal.deep_request('primary', request_id='late-initiative', initiative_allowed=True)
        self.user('Stop joking')
        result = replace(self.result(request), initiative=InitiativeSpeak('A joke'))
        decision = self.journal.apply_deep(request, result)
        self.assertEqual(decision['through'], request.snapshot.through_sequence)
        self.assertEqual(decision['initiative'], 'scheduled')
        self.assertEqual(self.journal.snapshot('primary').context_note, 'new note')
        self.assertIsNotNone(self.journal.pending_initiative('primary'))

    def test_audit_tail_is_not_observation(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='no-op')
        self.journal.apply_deep(request, DeepResult(3, 'no-op'))
        self.assertIsNone(self.journal.deep_request('primary', request_id='tail'))
        self.assertEqual(self.journal.cursor('primary'), self.journal.high_watermark('primary'))

    def test_late_epoch_preserves_new_turns(self):
        self.finish(self.user())
        request = self.journal.deep_request('primary', request_id='late', compact=True)
        newer = self.user('green correction')
        terminal = self.finish(newer)
        decision = self.journal.apply_deep(request, self.result(request, True))
        self.assertEqual(decision['through'], request.snapshot.through_sequence)
        self.assertIn(newer.event_id, [e.event_id for e in self.journal.fast_snapshot('primary').recent_dialogue])
        self.assertEqual(self.journal.snapshot('primary').revision, 1)
        self.assertEqual(self.journal.context_epoch('primary').version, 1)

        from vtuber.contracts.context import CompactionProposal
        from vtuber.contracts.deep import InitiativeSpeak
        epoch = self.journal.context_epoch('primary')
        local = CompactionProposal('budget-only', 'primary', epoch.version, 1,
            self.journal.high_watermark('primary'), terminal.sequence, ())
        self.assertTrue(self.journal.apply_compaction(local).accepted)
        self.journal.close()
        self.journal = Journal(Path(self.folder.name) / 'deep.db')
        self.addCleanup(self.journal.close)
        recovery = self.journal.deep_request('primary', request_id='recover', initiative_allowed=True)
        self.assertEqual(recovery.recovery_epoch, epoch)
        self.assertIn(newer.event_id, [e.event_id for e in recovery.compaction.events])
        self.journal.apply_deep(recovery, DeepResult(3, recovery.request_id,
            initiative=InitiativeSpeak('still pending')))
        pending = self.journal.pending_initiative('primary')
        message = self.journal.claim_initiative(pending.event_id, self.journal.fast_snapshot('primary'))
        self.finish(message)
        self.assertIsNone(self.journal.deep_request('primary', request_id='no-loop'))
        self.assertIsNone(self.journal.deep_request('primary', request_id='no-pressure-loop', compact=True))
        retried = self.journal.deep_request('primary', request_id='explicit', recover=True)
        self.assertIsNotNone(retried.compaction)
        self.journal.apply_deep(retried, DeepResult(3, retried.request_id, compaction='Rebuilt continuity'))
        self.assertFalse(self.journal.epoch_recovery('primary')['recovery_pending'])


class DeepWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_does_not_apply_result_from_cancellation_swallowing_adapter(self):
        entered=asyncio.Event()
        class Deep:
            async def propose(self,request):
                entered.set()
                try:await asyncio.Event().wait()
                except asyncio.CancelledError:return DeepResult(3,request.request_id)
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/'runtime.db')
            try:
                runtime=Runtime('primary',journal,FakeFast(0),Deep(),lambda _:None)
                await runtime.start()
                await(await runtime.submit(UserMessage('before close')))
                await asyncio.wait_for(entered.wait(),1)
                await asyncio.wait_for(runtime.close(),.2)
                self.assertEqual(journal.cursor('primary'),0)
            finally:journal.close()

    async def test_restart_recovers_user_without_started_event(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'runtime.db'
            journal = Journal(path)
            orphan = UserMessage('accepted before crash')
            journal.append(orphan.as_event())
            journal.close()
            journal = Journal(path)
            class Deep:
                async def propose(self, request): return DeepResult(3,request.request_id)
            try:
                async with Runtime('primary',journal,FakeFast(0),Deep(),lambda _:None) as runtime:
                    await(await runtime.submit(UserMessage('after restart')))
                    for _ in range(100):
                        if journal.cursor('primary')>=journal.high_watermark('primary'):break
                        await asyncio.sleep(.001)
                    terminal=journal.get('reply_terminal_'+orphan.event_id)
                    self.assertIsNotNone(terminal)
                    self.assertEqual(terminal.kind,'character.reply.cancelled')
                    self.assertGreater(journal.cursor('primary'),0)
                    self.assertEqual(journal.unfinished_replies('primary'),())
            finally: journal.close()

    async def test_retry_interrupts_backoff(self):
        entered, again = asyncio.Event(), asyncio.Event()
        class Deep:
            calls = 0
            async def propose(self, request):
                self.calls += 1
                if self.calls > 1: again.set()
                raise ConnectionError()
        async def delay(seconds):
            entered.set()
            await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            message = UserMessage('one')
            journal.append(message.as_event())
            journal.append(Event.create('primary','character.reply.completed',{'text':'reply'},turn_id=message.turn_id))
            worker = DeepWorker('primary',journal,Deep(),lambda _:None,timeout=1,context_policy=None,diagnostics={})
            try:
                with patch('vtuber.runtime.deep.retry_delay',side_effect=delay):
                    worker.start()
                    await asyncio.wait_for(entered.wait(),1)
                    worker.retry()
                    await asyncio.wait_for(again.wait(),.2)
            finally:
                await worker.close()
                journal.close()

    async def test_one_worker_coalesces_pressure(self):
        class Policy:
            input_limit = 100
            working_context_tokens = 20
            def validate_working_context(self, text): pass
            def input_tokens(self, snapshot, message): return 75
            def prepare_epoch(self, snapshot, message): return None
            def validate_compaction(self, snapshot, proposal): pass
        class Deep:
            calls = 0
            compactions = []
            async def propose(self, request):
                self.calls += 1
                self.compactions.append(request.compaction)
                return DeepResult(3, request.request_id)
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            deep = Deep()
            try:
                async with Runtime('primary', journal, FakeFast(0), deep, lambda _:None,
                                   context_policy=Policy()) as runtime:
                    await (await runtime.submit(UserMessage('one')))
                    await asyncio.sleep(.05)
                    calls = deep.calls
                    self.assertGreater(calls, 0)
                    await asyncio.sleep(.05)
                    self.assertEqual(deep.calls, calls)
                    self.assertTrue(any(deep.compactions))
                    self.assertIsNone(runtime.deep_error)
            finally: journal.close()

    async def test_slow_luna_does_not_gate_fast(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []
        class Deep:
            async def propose(self, request):
                requests.append(request)
                entered.set()
                await release.wait()
                return DeepResult(3, request.request_id, '# Context\nA useful future angle.')
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            try:
                async with Runtime('primary', journal, FakeFast(0), Deep(), lambda _:None) as runtime:
                    await (await runtime.submit(UserMessage('one')))
                    await asyncio.wait_for(entered.wait(), 1)
                    self.assertEqual(requests[0].events[-1].kind, 'character.reply.completed')
                    await asyncio.wait_for(await runtime.submit(UserMessage('two')), 1)
                    self.assertEqual(journal.cursor('primary'), 0)
                    release.set()
                    async with asyncio.timeout(1):
                        while journal.snapshot('primary').revision == 0:
                            await asyncio.sleep(.001)
                    self.assertTrue(all(e.payload['application']['through'] <= journal.cursor('primary') for e in
                        journal.read('primary') if e.kind == 'deep.batch.completed'))
                    self.assertEqual(journal.snapshot('primary').context_note, '# Context\nA useful future angle.')
            finally: journal.close()

    async def test_offline_retry_is_bounded(self):
        class Deep:
            calls = 0
            async def propose(self, request):
                self.calls += 1
                raise ConnectionError()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder)/'runtime.db')
            message = UserMessage('one')
            journal.append(message.as_event())
            journal.append(Event.create('primary', 'character.reply.completed', {'text':'reply'}, turn_id=message.turn_id))
            diagnostics, delays = {}, []
            worker = DeepWorker('primary', journal, Deep(), lambda _:None, timeout=1,
                context_policy=None, diagnostics=diagnostics)
            async def delay(seconds): delays.append(seconds)
            try:
                with patch('vtuber.runtime.deep.retry_delay', side_effect=delay):
                    worker.start()
                    for _ in range(50):
                        await asyncio.sleep(0)
                        if diagnostics.get('degraded'): break
                    self.assertEqual(delays, [1,2,4,8,16])
                    self.assertEqual(worker.mind.calls, 6)
                    self.assertEqual(journal.cursor('primary'), 0)
            finally:
                await worker.close()
                journal.close()

    async def test_pressure_thresholds(self):
        from vtuber.context import ContextCompiler
        from vtuber.contracts.state import FastSnapshot, CharacterState
        compiler = ContextCompiler('identity', token_counter=lambda _:11880)
        snapshot = FastSnapshot(CharacterState('primary'),0,())
        self.assertEqual(compiler.input_tokens(snapshot, UserMessage('hi')), 11880)
        self.assertEqual(compiler.input_limit*3//4, 11880)
