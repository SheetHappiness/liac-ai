"""Immutable adapter inputs; delivery classification is assigned by trusted callers."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

type PerceptionKind = Literal['chat', 'voice', 'observation', 'state']
type Delivery = Literal['direct', 'ambient', 'noise']


@dataclass(frozen=True)
class Perception:
    perception_id: str
    kind: PerceptionKind
    source: str
    conversation_key: str
    content: str
    occurred_at: str
    delivery: Delivery = 'ambient'
    author_id: str | None = None
    dedupe_key: str | None = None

    def __post_init__(self) -> None:
        for value in (self.perception_id, self.source, self.conversation_key):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Perception identifiers and source must be nonempty strings')
        for value in (self.author_id, self.dedupe_key):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError('Optional identifiers must be nonempty strings')
        if self.kind not in ('chat', 'voice', 'observation', 'state'):
            raise ValueError('Unsupported perception kind')
        if self.delivery not in ('direct', 'ambient', 'noise'):
            raise ValueError('Unsupported perception delivery')
        if not isinstance(self.content, str) or (self.delivery != 'noise' and not self.content.strip()):
            raise ValueError('Meaningful perception content must be nonempty text')
        try:
            stamp = datetime.fromisoformat(self.occurred_at)
        except (TypeError, ValueError):
            raise ValueError('Perception timestamp must be a UTC datetime') from None
        if stamp.utcoffset() != timedelta(0):
            raise ValueError('Perception timestamp must be a UTC datetime')


@dataclass(frozen=True)
class PerceptionBatch:
    conversation_key: str
    items: tuple[Perception, ...]
    closed_by: Literal['quiet', 'max_window', 'immediate']

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_key, str) or not self.conversation_key.strip():
            raise ValueError('Batch conversation key must be nonempty')
        if not isinstance(self.items, tuple) or not self.items or any(
                not isinstance(item, Perception) or item.conversation_key != self.conversation_key
                for item in self.items):
            raise ValueError('Batch must contain immutable same-conversation perceptions')
        if self.closed_by not in ('quiet', 'max_window', 'immediate'):
            raise ValueError('Unsupported batch closing reason')
