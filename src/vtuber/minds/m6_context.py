"""Project committed text dialogue into the Single Mind request."""

from datetime import datetime

from vtuber.contracts.events import Event


OPERATING_PROMPT = (
    'Choose exactly one tool for the latest user turn. '
    'Use speak with a short message when you want to reply, or stay_silent when you choose silence.'
)


def build_m6_messages(identity: str, dialogue: tuple[Event, ...]) -> tuple[dict[str, object], ...]:
    messages: list[dict[str, object]] = [
        {'role': 'system', 'content': f'{identity.strip()}\n\n{OPERATING_PROMPT}'},
    ]
    for event in dialogue:
        if event.kind not in ('user.message.completed', 'character.reply.completed'):
            continue
        timestamp = int(datetime.fromisoformat(event.occurred_at).timestamp() * 1000)
        payload = event.payload
        text = payload['text']
        if event.kind == 'user.message.completed':
            messages.append({'role': 'user', 'content': text, 'timestamp': timestamp})
            continue
        action = payload.get('action')
        stop_reason = 'stop'
        if action is None:
            content = [{'type': 'text', 'text': text}]
        else:
            stop_reason = 'toolUse'
            call_id = payload['tool_call_id']
            content = [{'type': 'toolCall', 'id': call_id, 'name': action,
                        'arguments': {'message': text} if action == 'speak' else {}}]
        counts = dict.fromkeys(('input', 'output', 'cacheRead', 'cacheWrite'), 0)
        messages.append({'role': 'assistant', 'api': 'openai-codex-responses', 'provider': 'openai-codex',
                         'model': 'gpt-6-luna', 'content': content, 'stopReason': stop_reason,
                         'usage': {**counts, 'totalTokens': 0, 'cost': {**counts, 'total': 0}},
                         'timestamp': timestamp})
        if action is not None:
            messages.append({'role': 'toolResult', 'toolCallId': call_id, 'toolName': action,
                             'content': [{'type': 'text', 'text': 'Text reply completed.' if action == 'speak'
                                          else 'Turn completed silently.'}],
                             'isError': False, 'timestamp': timestamp})
    return tuple(messages)
