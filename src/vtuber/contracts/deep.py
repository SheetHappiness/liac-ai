"""Versioned immutable Luna work and direct execution results."""
from dataclasses import dataclass
import math

from vtuber.contracts.context import ContextEpoch
from vtuber.contracts.events import Event
from vtuber.contracts.state import FastSnapshot


class DeepUnavailable(RuntimeError):
    """Provider requires an external change; do not automatically retry this cycle."""


@dataclass(frozen=True)
class CompactionInput:
    cutoff: int
    events: tuple[Event, ...]


@dataclass(frozen=True)
class InitiativeSpeak:
    intent: str
    delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.intent, str) or not self.intent.strip() or len(self.intent) > 1000:
            raise ValueError('Invalid initiative text')
        if (type(self.delay_seconds) not in (int, float) or not math.isfinite(self.delay_seconds)
                or self.delay_seconds < 0):
            raise ValueError('Invalid initiative delay')


@dataclass(frozen=True)
class InitiativeCancel:
    pass


@dataclass(frozen=True)
class DeepRequest:
    request_id: str
    snapshot: FastSnapshot
    cursor_from: int
    events: tuple[Event, ...]
    compaction: CompactionInput | None = None
    working_context_tokens: int = 2048
    initiative_allowed: bool = False
    pending_initiative: Event | None = None
    recovery_epoch: ContextEpoch | None = None


@dataclass(frozen=True)
class DeepResult:
    schema_version: int
    request_id: str
    note: str | None = None
    compaction: str | None = None
    initiative: InitiativeSpeak | InitiativeCancel | None = None
