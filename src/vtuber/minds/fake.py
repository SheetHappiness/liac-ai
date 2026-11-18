import json
from collections.abc import Callable

from vtuber.contracts.events import new_id
from vtuber.contracts.mind import MindDecision
from vtuber.minds.m6_context import PERCEPTION_FRAME


class FakeSingleMind:
    async def generate(self, messages: tuple[dict[str, object], ...], *,
                       on_speak_delta: Callable[[str], None] | None = None) -> MindDecision:
        message = next(item['content'] for item in reversed(messages) if item['role'] == 'user')
        if message.startswith(PERCEPTION_FRAME):
            items = json.loads(message.removeprefix(PERCEPTION_FRAME))
            message = '\n'.join(item['content'] for item in items if item['delivery'] == 'direct')
        text = f'You said: {message}'
        if on_speak_delta is not None:
            on_speak_delta(text)
        return MindDecision('speak', text, new_id('call'))
