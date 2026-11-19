"""Project committed text dialogue into the Single Mind request."""

from collections.abc import Callable, Iterable
from datetime import datetime

from vtuber.contracts.context import ContextBudgetExceeded
from vtuber.contracts.events import Event, canonical_json


PERCEPTION_FRAME = '[PERCEPTIONS]\n'


OPERATING_PROMPT = (
    'Choose exactly one tool: speak or stay_silent. '
    'When the user appears to be mid-thought, use stay_silent and let them continue. '
    'If the latest input continues an earlier fragment, interpret them together. '
    'Use speak for a short reply when a response fits the conversation, '
    'especially after a complete question or request. '
    'You may choose stay_silent on consecutive turns.'
)


def build_m6_messages(identity: str, newest_first: Iterable[Event], *,
                      lookup: Callable[[str], Event | None] | None = None) -> tuple[dict[str, object], ...]:
    system = {'role': 'system', 'content': f'{identity.strip()}\n\n{OPERATING_PROMPT}'}
    # Leave room in the 64 KiB bridge frame for the JSONL envelope.
    remaining = 63 * 1024 - len(canonical_json(system).encode('utf-8'))
    history = []
    for event in newest_first:
        if event.kind not in ('user.message.completed', 'character.reply.completed'):
            continue
        group = _project(event, lookup)
        remaining -= len(canonical_json(group).encode('utf-8'))
        if remaining < 0:
            if not history and event.kind == 'user.message.completed':
                raise ContextBudgetExceeded('Latest user message exceeds the M6 context budget')
            break
        history.append(group)
    return (system, *(message for group in reversed(history) for message in group))


def _project(event: Event, lookup: Callable[[str], Event | None] | None) -> tuple[dict[str, object], ...]:
    timestamp = int(datetime.fromisoformat(event.recorded_at or event.occurred_at).timestamp() * 1000)
    payload = event.payload
    text = payload['text']
    if event.kind == 'user.message.completed':
        if lookup is not None and (ids := payload.get('perception_ids')):
            perceptions = []
            for identifier in ids:
                raw = lookup(identifier)
                if raw is None or raw.character_id != event.character_id or raw.kind != 'perception.received':
                    raise ValueError('Grouped user input has invalid perception references')
                item = raw.payload
                perceptions.append({key: item[key] for key in ('perception_id', 'kind', 'source',
                    'conversation_key', 'author_id', 'occurred_at', 'delivery', 'content')})
            text = PERCEPTION_FRAME + canonical_json(perceptions)
        return ({'role': 'user', 'content': text, 'timestamp': timestamp},)

    action = payload.get('action')
    counts = dict.fromkeys(('input', 'output', 'cacheRead', 'cacheWrite'), 0)
    assistant = {'role': 'assistant', 'api': 'openai-codex-responses', 'provider': 'openai-codex',
                 'model': 'gpt-6-luna', 'timestamp': timestamp,
                 'usage': {**counts, 'totalTokens': 0, 'cost': {**counts, 'total': 0}}}
    if action is None:
        return (dict(assistant, content=[{'type': 'text', 'text': text}], stopReason='stop'),)

    call_id = payload['tool_call_id']
    tool_call = {'type': 'toolCall', 'id': call_id, 'name': action,
                 'arguments': {'message': text} if action == 'speak' else {}}
    result = {'role': 'toolResult', 'toolCallId': call_id, 'toolName': action,
              'content': [{'type': 'text', 'text': 'Text reply completed.' if action == 'speak'
                           else 'Turn completed silently.'}], 'isError': False, 'timestamp': timestamp}
    return (dict(assistant, content=[tool_call], stopReason='toolUse'), result)
