"""SQLite transactions own event ordering and perception provenance."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from hashlib import sha256
from collections.abc import Iterator

from vtuber.contracts.events import CharacterId, Event, canonical_json, utc_now
from vtuber.contracts.perception import Perception, PerceptionBatch


class EventConflict(ValueError):
    """An idempotency identifier was reused with different content."""


class Journal:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        if read_only:
            self._db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro',
                                       uri=True, isolation_level=None)
            self._db.row_factory = sqlite3.Row
            return
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError(f"Unsupported database version: {version}")
            with self._transaction():
                self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                    character_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE, content TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, PRIMARY KEY(character_id, sequence))""")
                self._db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS user_turn ON events
                    (character_id, json_extract(content, '$.turn_id'))
                    WHERE json_extract(content, '$.kind') = 'user.message.completed'""")
                self._db.execute("PRAGMA user_version=2")
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> Event:
        return Event(**json.loads(row["content"]), sequence=row["sequence"],
                     recorded_at=row["recorded_at"])

    def get(self, event_id: str) -> Event | None:
        row = self._db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return self._decode(row) if row else None

    def high_watermark(self, character_id: CharacterId) -> int:
        return self._db.execute("SELECT COALESCE(MAX(sequence), 0) FROM events WHERE character_id=?",
                                (character_id,)).fetchone()[0]

    def _append(self, event: Event) -> Event:
        content = asdict(event)
        del content["sequence"], content["recorded_at"]
        encoded = canonical_json(content)
        previous = self._db.execute("SELECT * FROM events WHERE event_id=?",
                                    (event.event_id,)).fetchone()
        if previous:
            if previous["content"] != encoded:
                raise EventConflict(f"event_id conflict: {event.event_id}")
            return self._decode(previous)
        stored = replace(event, sequence=self.high_watermark(event.character_id) + 1,
                         recorded_at=utc_now())
        self._db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                         (stored.character_id, stored.sequence, stored.event_id,
                          encoded, stored.recorded_at))
        return stored

    def append(self, event: Event) -> Event:
        with self._transaction():
            return self._append(event)

    @staticmethod
    def _raw_perception(character_id: str, item: Perception) -> Event:
        return Event.create(character_id, 'perception.received', asdict(item),
                            event_id=item.perception_id, source=item.source, occurred_at=item.occurred_at)

    @staticmethod
    def _check_direct_route(item: Perception) -> None:
        if item.delivery == 'direct' and (item.kind, item.source, item.conversation_key) not in (
                ('chat', 'local', 'local'), ('voice', 'electron', 'local')):
            raise ValueError('Direct perception requires a supported local route')

    def is_new_perception(self, character_id: str, item: Perception) -> bool:
        self._check_direct_route(item)
        previous = self.get(item.perception_id)
        if previous is None:
            return True
        # Reject conflicts at intake so unrelated inputs in the queue can still commit.
        if replace(previous, sequence=0, recorded_at=None) != self._raw_perception(character_id, item):
            raise EventConflict(f'event_id conflict: {item.perception_id}')
        return False

    def accept_local_perceptions(self, character_id: str, batch: PerceptionBatch) -> Event | None:
        direct = tuple(item for item in batch.items if item.delivery == 'direct')
        for item in direct:
            self._check_direct_route(item)
        raw = tuple(self._raw_perception(character_id, item)
                    for item in batch.items if item.delivery != 'noise')
        with self._transaction():
            # Check every raw event for conflicts, including replays that produce no dialogue.
            new_direct = {}
            for item in direct:
                if self.get(item.perception_id) is None:
                    new_direct.setdefault(item.perception_id, item)
            fresh_ids = dict.fromkeys(event.event_id for event in raw
                                      if self.get(event.event_id) is None)
            for event in raw:
                self._append(event)
            if not new_direct:
                return None
            digest = sha256(canonical_json(list(new_direct)).encode('utf-8')).hexdigest()
            event = Event.create(character_id, 'user.message.completed', {
                'text': '\n'.join(item.content for item in new_direct.values()),
                'batch_id': batch.batch_id,
                'perception_ids': list(fresh_ids),
            }, source='user', event_id='perception_group_' + digest, turn_id='perception_turn_' + digest,
                occurred_at=next(iter(new_direct.values())).occurred_at)
            return self._append(event)

    def read(self, character_id: CharacterId, *, after: int = 0,
             limit: int = 100) -> tuple[Event, ...]:
        if after < 0 or limit < 1:
            raise ValueError("after must be nonnegative and limit positive")
        rows = self._db.execute("""SELECT * FROM events WHERE character_id=? AND sequence>?
            ORDER BY sequence LIMIT ?""", (character_id, after, limit)).fetchall()
        return tuple(self._decode(row) for row in rows)

    def recent_dialogue(self, character_id: CharacterId, limit: int = 20) -> tuple[Event, ...]:
        rows = self._db.execute("""SELECT * FROM events WHERE character_id=? AND
            json_extract(content, '$.kind') IN ('user.message.completed', 'character.reply.completed')
            ORDER BY sequence DESC LIMIT ?""", (character_id, limit)).fetchall()
        return tuple(self._decode(row) for row in reversed(rows))

    def unfinished_inputs(self, character_id: CharacterId) -> tuple[Event, ...]:
        rows = self._db.execute("""SELECT * FROM events AS input WHERE character_id=?
            AND json_extract(content, '$.kind') = 'user.message.completed'
            AND NOT EXISTS (SELECT 1 FROM events AS ended
                WHERE ended.character_id=input.character_id
                AND json_extract(ended.content, '$.turn_id')=json_extract(input.content, '$.turn_id')
                AND json_extract(ended.content, '$.kind') IN
                    ('character.reply.completed', 'character.reply.cancelled', 'character.reply.failed'))
            ORDER BY sequence""", (character_id,)).fetchall()
        return tuple(self._decode(row) for row in rows)
