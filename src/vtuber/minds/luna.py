"""Luna's bounded direct-context protocol over the existing OMP text transport."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vtuber.minds.omp import OMPTransport

import json

from vtuber.contracts.deep import DeepRequest, DeepResult, InitiativeSpeak, InitiativeCancel
from vtuber.contracts.events import canonical_json
from vtuber.contracts.trace import TraceSink, emit_trace


def _object(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() != keys:
        raise ValueError('Unexpected Deep fields')
    return value


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or len(value) > limit:
        raise ValueError('Invalid Deep text')
    return value


def parse_result(text: str, request: DeepRequest) -> DeepResult:
    if len(text.encode('utf-8')) > 65536:
        raise ValueError('Deep response too large')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate Deep field')
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('Nonfinite Deep value')

    data = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 3:
        raise ValueError('Unsupported Deep schema')
    _object(data, {'schema_version', 'note', 'compaction', 'initiative'})
    note, compaction = data['note'], data['compaction']
    if note is not None and (not isinstance(note, str) or len(note.encode('utf-8')) > 32768):
        raise ValueError('Invalid working context')
    if compaction is not None:
        if request.compaction is None:
            raise ValueError('Unrequested compaction')
        if not isinstance(compaction, str) or len(compaction) > 8000:
            raise ValueError('Invalid summary')
    initiative = None
    value = data['initiative']
    if value is not None:
        if not isinstance(value, dict):
            raise ValueError('Invalid initiative')
        action = value.get('action')
        if action == 'none':
            _object(value, {'action'})
        elif action == 'cancel':
            _object(value, {'action'})
            initiative = InitiativeCancel()
        elif action == 'speak':
            required = {'action', 'intent'}
            if not required <= value.keys() <= required | {'delay_seconds'}:
                raise ValueError('Unexpected initiative fields')
            initiative = InitiativeSpeak(_text(value['intent'], 1000), value.get('delay_seconds', 0))
        else:
            raise ValueError('Invalid initiative action')
    return DeepResult(3, request.request_id, note, compaction, initiative)


def render_request(request: DeepRequest) -> str:
    def project(event):
        payload = event.payload
        kind = event.kind
        if kind == 'user.message.completed':
            return {'speaker': 'user', 'text': payload['text'], 'occurred_at': event.occurred_at}
        if kind == 'character.reply.completed':
            return {'speaker': 'liac', 'text': payload['text'], 'occurred_at': event.occurred_at}
        if kind in ('character.reply.cancelled', 'character.reply.failed'):
            return {'speaker': 'liac', 'status': kind.rsplit('.', 1)[-1],
                    'reason': payload.get('reason', ''), 'occurred_at': event.occurred_at}
        if kind == 'character.initiative.started':
            return {'speaker': 'liac', 'status': 'started', 'intent': payload['intent'],
                    'occurred_at': event.occurred_at}
        if kind == 'initiative.proposed':
            return {'status': 'proposed', 'intent': payload['intent'],
                    'ready_at': payload['ready_at'], 'occurred_at': event.occurred_at}
        if kind == 'initiative.closed':
            return {'status': 'closed', 'reason': payload.get('reason', ''), 'occurred_at': event.occurred_at}
        return None

    events = {event.event_id: event for event in (*request.snapshot.recent_dialogue,
        *(request.compaction.events if request.compaction else ()), *request.events)}
    new_ids = {event.event_id for event in request.events}
    history, new = [], []
    covered = {'history': 0, 'new': 0}
    for event in sorted(events.values(), key=lambda item: item.sequence):
        item = project(event)
        if item is None:
            continue
        section = 'new' if event.event_id in new_ids else 'history'
        (new if section == 'new' else history).append(item)
        if request.compaction and event.sequence <= request.compaction.cutoff:
            covered[section] += 1
    compaction = None
    if request.compaction is not None:
        prior = request.recovery_epoch
        compaction = {'prior_epoch': ([item.text for item in prior.items]
                       if prior is not None and prior.items != request.snapshot.epoch.items else None),
                      'through': covered}
    pending = request.pending_initiative.payload if request.pending_initiative else None
    now = datetime.now().astimezone()
    return canonical_json({
        'current_time': now.isoformat(), 'timezone': now.tzname(),
        'working_context': request.snapshot.state.context_note,
        'epoch': [item.text for item in request.snapshot.epoch.items],
        'history': history, 'new': new, 'compaction': compaction,
        'initiative': {'allowed': request.initiative_allowed,
            'pending': {'intent': pending['intent'], 'ready_at': pending['ready_at']} if pending else None},
        'working_context_tokens': request.working_context_tokens,
    })


class LunaDeep:
    def __init__(self, transport: OMPTransport, identity: str, *, trace: TraceSink | None = None) -> None:
        self.transport = transport
        self.identity = identity
        self.trace = trace

    async def propose(self, request: DeepRequest) -> DeepResult:
        # Identity is authored separately from all untrusted canonical evidence.
        prompt = render_request(request)
        emit_trace(self.trace, 'deep.prompt', request.request_id, prompt=prompt)
        if self.trace is None:
            text = await self.transport.request(prompt)
        else:
            text = await self.transport.request(prompt, request_id=request.request_id)
        emit_trace(self.trace, 'deep.response', request.request_id, text=text)
        return parse_result(text, request)
