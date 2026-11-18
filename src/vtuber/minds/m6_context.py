"""Project committed text dialogue into the Single Mind request."""

from datetime import datetime

from vtuber.contracts.context import ContextBudgetExceeded
from vtuber.contracts.events import Event, canonical_json


OPERATING_PROMPT = (
    'Choose exactly one tool for the latest user turn. '
    'Use speak with a short message when you want to reply, or stay_silent when you choose silence.'
)


def build_m6_messages(identity: str, dialogue: tuple[Event, ...]) -> tuple[dict[str, object], ...]:
    system = {'role': 'system', 'content': f'{identity.strip()}\n\n{OPERATING_PROMPT}'}
    # Leave room in the 64 KiB bridge frame for the JSONL envelope.
    remaining = 63 * 1024 - len(canonical_json(system).encode('utf-8'))
    history = []
    for event in reversed(dialogue):
        if event.kind not in ('user.message.completed', 'character.reply.completed'):
            continue
        group = _project(event)
        remaining -= len(canonical_json(group).encode('utf-8'))
        if remaining < 0:
            if not history and event.kind == 'user.message.completed':
                raise ContextBudgetExceeded('Latest user message exceeds the M6 context budget')
            break
        history.append(group)
    return (system, *(message for group in reversed(history) for message in group))


def _project(event: Event) -> tuple[dict[str, object], ...]:
    timestamp = int(datetime.fromisoformat(event.recorded_at or event.occurred_at).timestamp() * 1000)
    payload = event.payload
    text = payload['text']
    if event.kind == 'user.message.completed':
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
