# M5.0 — Perception Bus

Implemented and verified locally on 2026-11-17 from M4.8 `d3dfeda`.
Branch: `codex/m5-0-perception-bus`. Status: **DECIDED** internal API,
**EXPERIMENT** timing defaults; offline acceptance passed.

## Boundaries and usage

`contracts/perception.py` defines frozen validated `Perception`/`PerceptionBatch`.
Adapters supply stable IDs, UTC timestamps, conversation keys and trusted delivery
classification (`direct`, `ambient`, `noise`). Display names are content, not
identity. Source strings do not authenticate an adapter; this is a trusted
in-process API. Untrusted future adapters need their own validation and permissions.

`runtime/perception_bus.py` uses the owning asyncio loop's monotonic ingress time,
not source timestamps. It selects the oldest pending conversation and retains
FIFO order within that key. Quiet gaps reset on the latest included arrival; the
minimum gap across chat/live kinds applies to mixed batches. A hard ceiling runs
from the first ingress arrival. Expired backlog windows stay separate even when
draining starts late. No worker is created by the Bus.

| Setting | Experimental default |
| --- | ---: |
| `live_gap` | 0.30 seconds |
| `text_gap` | 0.75 seconds |
| `max_window` | 2.0 seconds |
| `max_pending` | 256 meaningful items |

Timing accepts finite nonnegative seconds; capacity is a positive integer.
`publish()` returns `True` for accepted meaningful input, `False` for exact pending
duplicates or discarded noise. `PerceptionQueueFull` explicitly rejects new
meaningful input without losing accepted input. Conflicting pending IDs raise
`ValueError`. All noise is discarded before it consumes capacity or resets timers.
`dedupe_key` is preserved metadata; M5.0 deduplicates by `perception_id`.
Content-free `stats` snapshots contain `published`, `duplicate`, `noise_dropped`,
`overflow`, and `batches` counts. Deduplication state is bounded to pending items.

`close()` forbids publishing and wakes drains. Accepted meaningful items remain
drainable, flushing without an extra delay; `None` means closed and empty.
Concurrent drains serialize. Cancellation leaves all pending items, their original
ingress times and capacity accounting intact. Cross-thread callers must marshal
all Bus/Runtime operations onto the owning event loop.

`Runtime.submit_perceptions(batch)` accepts ambient inputs for audit from any
source/key. Direct routing supports only `kind='chat', source='local',
conversation_key='local'`, with one `author_id` (or all `None`) per batch. Other
direct routes or multiple authors raise `ValueError` before any writes. A batch
is not a new character or separate conversation history. Cross-channel and
multi-author rendering require a later milestone.

Within an existing started Runtime, the caller can explicitly batch local text:

```python
from vtuber.contracts.events import utc_now
from vtuber.contracts.perception import Perception
from vtuber.runtime.perception_bus import PerceptionBus

bus = PerceptionBus()
for identifier, text in (("local-1", "hello"), ("local-2", "one more thought")):
    await bus.publish(Perception(identifier, "chat", "local", "local", text,
                                utc_now(), delivery="direct"))
group = await bus.drain()
task = await runtime.submit_perceptions(group)
if task is not None:
    await task
await bus.close()
```

IDs must identify actual source inputs and remain unchanged on retry. The example
assumes a fresh database for those two IDs. CLI/desktop retain `submit(UserMessage)`;
there are no new CLI flags or automatic background intake loop.

## Durability, replay and silence

Queue acceptance and `drain()` are ephemeral. A process crash before Journal
commit can lose queued input. Callers retain a drained batch until Runtime accepts
it and may retry it after an error. After successful drain the Bus no longer owns
that batch. Shutdown callers drain accepted inputs before discarding the Bus.

`Journal.append_many()` uses one existing transaction and `_append()` conflict
checks. Runtime writes each non-noise `perception.received` with its original ID,
source/time and complete metadata/text, plus one synthesized canonical
`user.message.completed` for newly accepted direct IDs. Raw events have no turn
ID. Raw text is preserved exactly; canonical direct texts join with newlines.
The canonical event/turn IDs derive from SHA-256 of the ordered IDs encoded as an
unambiguous JSON array. Duplicate IDs render only once. Existing IDs are still
validated transactionally: a conflicting replay rolls back new raw and canonical
events. Replays in another order or overlapping batch do not speak again for
already committed inputs; a partial replay speaks only the newly accepted inputs.

After commit, Runtime reuses its existing input lock, Fast cancellation, snapshot,
output and Deep notification paths. A grouped input is one actual user turn with
one terminal reply. Restart closes an input committed before `reply.started` as
`character.reply.cancelled` with `process_restarted`; it does not invent a reply
or repeat generation. The existing single-Runtime database ownership applies.

Ambient-only batches neither start/cancel Fast nor notify Luna. They do not mutate
an in-flight Fast snapshot or appear in canonical dialogue. Raw perception events
are excluded from Deep semantic observations even when interleaved inside a chat
turn; existing cursor checks still acknowledge audit-only tails. The existing
Deep worker continues after a check that advances the audit cursor, so multiple
audit pages cannot strand later dialogue. A check with no cursor progress still
stops; audit input does not create an inference loop. Noise has no
durable event, speech or semantic processing. Initiative remains disabled by
default. No SQLite schema or Deep schema-v3 change was needed; ContextCompiler,
Hot/Cold selection, Epoch, tokenizer, Nemotron and fallback behavior are unchanged.

## Verification

Used the existing project Python 3.14 virtual environment and source imports:

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
python -m unittest test_perception test_perception_bus test_perception_runtime -v
python -m unittest test_perception_runtime test_runtime_lifecycle test_deep test_context -v
python -m unittest discover -s tests -v
@('/status', '/quit') | python -m vtuber --db .data/m5-0-cli.sqlite3
git diff --check
```

- Before changes: 129 tests, 128 passed, one existing desktop error.
- M5.0 targeted acceptance: 36 passed. The contract, Bus, Journal and Runtime
  API tests were observed failing before implementation and passing afterward.
- Cross-milestone targeted check before the final pipeline test: 63 passed;
  final contract/Bus/lifecycle/Deep/context checks passed 84 tests.
- Final full suite: 165 tests, 164 passed, the same baseline error:
  `test_desktop.WindowTests.test_chat_context_selection_and_offline_history`
  because `MainWindow.context` is absent. No new full-suite failures.
- The bounded `test_live_like_burst_full_pipeline` uses the actual Bus, Runtime
  and temporary on-disk SQLite with fake Fast/Deep. Three close local lines give
  three original raw IDs, one canonical user input, one terminal Fast reply,
  one closed compaction-safe turn and one Deep request. Subsequent ambient/noise
  input produces no extra Fast/Deep call.
- Other checks cover last-arrival gap resets, hard ceiling under continuous
  arrivals, key isolation, late backlog, mixed timing in both orders, capacity,
  noise flooding, pending duplicates/conflicts, concurrent/cancelled drains,
  shutdown, atomic rollback, partial replay, provenance, unsupported direct
  routes, active snapshots, supersession, restart and existing Hot/Cold boundaries.
- CLI `/status` and `/quit` completed with fake backends and closed storage.
  Private CLI storage stays in ignored `.data/`. Whitespace checks passed.
- A separate stdin Python smoke using only public APIs, default Bus timings,
  real ignored SQLite and fake backends produced three raw events, one canonical
  user input, one terminal reply and one Deep batch. Replay returned no new task;
  shutdown left no unfinished inputs.
- Fresh independent whole-branch review found one important backlog issue and
  no minor findings. More than two audit pages could strand subsequent completed
  dialogue because a `None` request was treated as exhaustion. The 250-ambient
  regression failed before the shared-worker cursor-progress fix and passed
  afterward; the final suite above includes that fix. No re-review was performed.

## Reference and limits

Behavioral reference: ProjectBEA perception bus/types and tests at
`f2186fc647db3f9ae65e6463b9f82c882bdca68b`, as recorded in the
[reviewed specification](superpowers/specs/2026-11-17-m5-0-perception-bus.md).
This is an independent stdlib implementation of the documented behavior; no
upstream source was copied. ProjectBEA is MIT, copyright © 2026 Emanuele Faraci.
Substantial future source reuse must retain the original copyright/license notices.

No live Nemotron/Luna run, provider cache/latency measurement, external adapter,
VLM/game control or large-load benchmark was performed. Offline fake-model checks
do not establish live compatibility. Queue timings are scheduling targets, not
latency guarantees. Ambient context projection, semantic perception routing and
volatile Live State remain **FUTURE (M5.1)**. External transport, autonomous speech,
new dependencies and Loonyball changes are outside M5.0. Commits stay local;
no push, merge, PR or deployment is part of this work.
