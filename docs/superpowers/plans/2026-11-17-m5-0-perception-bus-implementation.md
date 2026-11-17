# M5.0 Perception Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt ProjectBEA's quiet-gap perception batching so Liac can absorb observations without forced speech and answer a burst of local chat messages in one Fast turn without losing canonical events.

**Architecture:** Introduce immutable perception input and a bounded asyncio intake queue. Add one narrow atomic batch-ingestion path to the existing Journal/Runtime, preserving the existing single visible Fast stream and independent Luna worker. Keep perception-to-prompt routing, dedicated Attention scoring and external sensors outside M5.0.

**Tech Stack:** Python 3.12+, stdlib asyncio/dataclasses/unittest, existing SQLite Journal and fake Fast/Deep. No new dependencies.

**Spec:** [M5.0 Perception Bus specification](../specs/2026-11-17-m5-0-perception-bus.md). Executor must read both documents; create both at these repository-relative paths before implementation.

## Global Constraints

- Base: verified `codex/m4-8-context-handoff`, not an assumed `main`; inspect actual branch HEAD and status first.
- Preserve M4.7 roles, M4.8 Hot/Cold cutoff, schema-v3, SQLite schema, Nemotron prompt/template and existing `Runtime.submit` behavior.
- Initiative remains disabled. No separate model, worker, Memory Store, Attention scoring, idle monologue, external adapter or game-action support.
- Default batching: live gap `0.30s`, text gap `0.75s`, hard ceiling `2.0s`, maximum pending inputs `256`; configurable and explicitly experimental.
- A meaningful source event is never silently dropped. Duplicate IDs are idempotent; under pressure return a named error. Noise may coalesce/drop with diagnostics.
- New ingress awaits on the owning asyncio event loop; cross-thread adapters must marshal calls into that loop until a tested thread-safe API is designed.
- English only in application interface text and code comments; private inputs and traces remain under ignored `.data/`.
- Every implementation commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`.
- No GPT-6 Astra subagents, no automatic push/merge/PR, and no changes to Loonyball.

## Review Focus

1. **Burst vs long stream:** Three text lines from one key create one batch, but a continuously active source closes at the hard ceiling – Task 2 tests.
2. **Cross-conversation safety:** Two concurrent conversation keys never combine or silently steal one another's queued events – Task 2 tests.
3. **Pressure, noise and cancellation:** A full queue rejects meaningful input explicitly; repeated heartbeat noise cannot block an urgent direct input; cancellation/shutdown does not leak tasks – Task 2 tests.
4. **Atomic retry and crash:** Duplicate perception IDs cannot cause duplicate speech or half-written batches; a process restart handles a committed input without a completed reply – Task 3 tests.
5. **M4.8/Deep integrity:** A combined chat turn closes normally for `Journal.deep_request`, while ambient events do not trigger Fast or pollute semantic compaction – Task 3 and Task 4 tests.

## Source map

| File | Responsibility |
| --- | --- |
| `src/vtuber/contracts/perception.py` | Frozen input/batch types and validation; no provider/runtime imports |
| `src/vtuber/runtime/perception_bus.py` | Async queue, quiet-gap/max-window, per-conversation batching, overload/dedup/noise |
| `src/vtuber/runtime/journal.py` | Add short atomic `append_many`, keep existing DB schema |
| `src/vtuber/runtime/orchestrator.py` | Narrow `submit_perceptions(batch)` path; delegate Fast scheduling to existing private methods |
| `tests/test_perception.py` | Data contract tests |
| `tests/test_perception_bus.py` | Timing, ordering, capacity, cancellation, mixed sources |
| `tests/test_perception_runtime.py` | Journal/Runtime/Deep integration and recovery |
| `docs/PROJECT_BLUEPRINT.md`, `README.md` | M5.0 boundary and precise implemented/pending status |
| `docs/M5_0_PERCEPTION_BUS.md` | Implementation verification, limitations and tested commands |

The upstream reference is ProjectBEA `src/core/perception/{bus.py,types.py}` and `tests/test_perception_bus.py` at commit `f2186fc647db3f9ae65e6463b9f82c882bdca68b`. Copy behavioral ideas, not the entire single-Consciousness stack. Preserve MIT notices if substantial source is copied.

### Task 1: Frozen perception contract

**Files:** Create `src/vtuber/contracts/perception.py`, `tests/test_perception.py`. Include reviewed spec and this plan in the first task commit.

**Interfaces:**

- `type PerceptionKind = Literal['chat', 'voice', 'observation', 'state']`
- `type Delivery = Literal['direct', 'ambient', 'noise']`
- `@dataclass(frozen=True) class Perception`: fields `perception_id: str`, `kind: PerceptionKind`, `source: str`, `conversation_key: str`, `content: str`, `occurred_at: str`, `delivery: Delivery = 'ambient'`, `author_id: str | None = None`, `dedupe_key: str | None = None`. IDs, source and key nonempty; the caller provides a stable source ID and trusted delivery class.
- `@dataclass(frozen=True) class PerceptionBatch`: fields `conversation_key: str`, `items: tuple[Perception, ...]`, `closed_by: Literal['quiet', 'max_window', 'immediate']`. Nonempty; all items share the key; maintain ingress order.
- No new SQLite columns, domain event schema version or routing metadata in Bolt's identity.

- [ ] **Step 1: Add failing contract tests** for valid frozen construction, empty IDs, unsupported kinds/delivery, mismatching batch keys invalid/missing UTC timestamps and distinct `author_id` vs display name. Tests must assert invalid data raises `ValueError`.
- [ ] **Step 2: Run RED**: `python -m unittest test_perception -v`; expect import/type failures.
- [ ] **Step 3: Implement exactly the two immutable dataclasses and type aliases** with explicit field validation and no external dependencies.
- [ ] **Step 4: Run GREEN**: `python -m unittest test_perception -v`; assert all contract cases pass.
- [ ] **Step 5: Commit** the contract/tests and reviewed spec/plan as `feat: define typed Liac perceptions` with the required coauthor trailer.

### Task 2: Bounded quiet-gap Perception Bus

**Files:** Create `src/vtuber/runtime/perception_bus.py`, `tests/test_perception_bus.py`.

**Interfaces:**

- `PerceptionBus(*, live_gap: float = 0.30, text_gap: float = 0.75, max_window: float = 2.0, max_pending: int = 256)`; reject invalid/nonfinite/negative timing or queue bounds.
- `async def publish(self, item: Perception) -> bool`: true if queued, false for duplicate/noise coalesced or discarded. A meaningful full-queue insert raises `PerceptionQueueFull` without dropping previously accepted input.
- `async def drain(self) -> PerceptionBatch | None`: wait for first pending event; choose the oldest conversation key; collect same-key arrivals until the quiet gap or hard ceiling from the **first ingress arrival**. Other keys remain pending in arrival order. Return `None` only for a fully closed and empty bus.
- `async def close(self) -> None`: unblock consumers and forbid new input; previously accepted meaningful inputs remain drainable until queue exhaustion.
- `stats` exposes counts for `published`, `duplicate`, `noise_dropped`, `overflow`, `batches` without input contents.

- [ ] **Step 1: Add failing async tests** (`unittest.IsolatedAsyncioTestCase`) named `test_text_burst_resets_quiet_gap`, `test_stream_closes_at_first_arrival_ceiling`, `test_keys_never_mix`, `test_mixed_live_shortens_gap`, `test_idle_backlog_does_not_wait_extra_gap`, `test_duplicate_idempotent`, `test_noise_does_not_starve_direct`, `test_full_queue_rejects_meaningful`, `test_close_drains_then_unblocks`, `test_cancelled_drain_keeps_pending`. Use short configured delays and bounded `asyncio.timeout`; avoid fragile exact wall-time equalities.
- [ ] **Step 2: Run RED**: `python -m unittest test_perception_bus -v`; expect import/method failures.
- [ ] **Step 3: Implement the queue** using asyncio primitives, monotonic ingress timestamps and per-key grouping. Quiet gap resets on every same-key arrival; a non-chat event can shorten the gap. Deduplicate pending IDs; coalesce/drop noise before consuming queue capacity. Preserve FIFO order within each key. On cancellation, requeue in-flight items at the front without exceeding bounded capacity or losing order. No Fast/Luna/Journal dependency or wall-clock timestamp sorting.
- [ ] **Step 4: Run GREEN**: `python -m unittest test_perception_bus -v`; confirm all cases, including shutdown and overload, pass.
- [ ] **Step 5: Commit** as `feat: batch perceptions by quiet gap` with the required coauthor trailer.

### Task 3: Atomic local-chat delivery to existing Runtime

**Files:** Modify `src/vtuber/runtime/journal.py`, `src/vtuber/runtime/orchestrator.py`; create `tests/test_perception_runtime.py`.

**Interfaces:**

- `Journal.append_many(events: tuple[Event, ...]) -> tuple[Event, ...]` uses one `_transaction()` and existing `_append()` for all events. A conflicting duplicate rolls back the whole batch.
- `Runtime.submit_perceptions(batch: PerceptionBatch) -> asyncio.Task[None] | None` is a second intake entrypoint, not a replacement for `Runtime.submit(UserMessage)`.
- For each newly accepted non-noise perception, persist one existing schema-v1 `Event` with `kind='perception.received'`, original `event_id=perception_id`, `source`, `occurred_at` and a JSON payload of its explicit metadata and text. No `turn_id` for this raw event.
- For a batch of newly accepted **trusted local chat** direct perceptions, build one human-readable `UserMessage` from the texts in ingress order separated by newlines. Derive one stable synthetic event ID and turn ID from the ordered source IDs (e.g. SHA-256 hex digest of length-prefixed IDs). Atomically append raw events **and** `message.as_event()` before starting exactly one Fast task. Preserve existing input lock, cancellation, `_start_fast`, output and Deep notification logic; do not call `Runtime.submit()` after pre-inserting its message, because its existing idempotency branch would suppress generation.
- If the batch contains only ambient/noise inputs, append meaningful ambient raw events without any Fast start or cancellation. Non-local direct input is explicitly unsupported in M5.0 rather than silently routed into the wrong conversation. Do not synthesize fake speech to fill an empty batch.
- Replayed already-persisted perception IDs do not create new synthesized dialogue, even when retried in a different batch; conflicting duplicate IDs raise `EventConflict`. Handle pending unfinished synthetic inputs after process restart using existing Runtime recovery.

- [ ] **Step 1: Add failing Journal tests**: `test_append_many_is_atomic_on_conflict`, `test_append_many_preserves_sequence_and_idempotency`. Assert zero partial writes on conflict.
- [ ] **Step 2: Run RED**: `python -m unittest test_perception_runtime -v`; expect missing APIs.
- [ ] **Step 3: Implement `Journal.append_many`** without a schema migration. Run the Journal tests GREEN.
- [ ] **Step 4: Add failing Runtime tests**: `test_three_local_messages_one_fast_reply`, `test_each_raw_event_has_provenance`, `test_replay_does_not_speak_twice`, `test_ambient_only_never_starts_fast`, `test_active_fast_snapshot_unchanged_by_ambient`, `test_other_conversation_not_merged`, `test_incomplete_group_recovered_after_restart`, `test_deep_sees_one_completed_group`, `test_group_does_not_change_hot_cold_selector`. Use existing fake models and short SQLite fixtures.
- [ ] **Step 5: Implement `Runtime.submit_perceptions`** under the current input lock. Keep one actual canonical user turn for grouped local chat; raw perception events are audit input, not separate open turns. Ensure no new Luna calls for ambient-only input in M5.0.
- [ ] **Step 6: Run GREEN**: `python -m unittest test_perception_runtime test_runtime_lifecycle test_deep test_context -v`. Verify normal `Runtime.submit` and M4.8 invariants still pass.
- [ ] **Step 7: Commit** as `feat: accept perception batches without duplicate speech` with the required coauthor trailer.

### Task 4: Milestone verification and documentation

**Files:** Create `docs/M5_0_PERCEPTION_BUS.md`; modify `docs/PROJECT_BLUEPRINT.md`, `README.md` only where necessary. Do not modify or overwrite M4.7/M4.8 historical reports.

**Interfaces:** Reuse the public bus `publish`/`drain` and Runtime `submit_perceptions`; no new CLI flags, provider dependencies, Runner or generic plugin framework.

- [ ] **Step 1: Add one bounded async integration test** named `test_live_like_burst_full_pipeline` in `tests/test_perception_runtime.py`: publish three close local chat lines through the real Bus, drain one batch, invoke Runtime with fake Fast/Deep, then assert three raw source IDs, one canonical user message, one terminal Fast reply, no duplicate Luna/Deep loop, and exactly one compaction-safe completed turn. In a second part, publish ambient/noise after the reply and assert no additional Fast task.
- [ ] **Step 2: Run GREEN**: `python -m unittest test_perception test_perception_bus test_perception_runtime -v`, then `python -m unittest discover -s tests -v` with `PYTHONPATH=src;tests;vendor/omp-rpc/src`; compare to the *measured* pre-change baseline (M4.8 reported 129 tests / 128 passes / one existing `MainWindow.context` desktop error; verify it still applies).
- [ ] **Step 3: Inspect correctness**: `git diff --check`, `git status --short` and `git diff --stat`. Ensure no private `.data/` records, source tokens, prompts or credentials are staged.
- [ ] **Step 4: Write documentation**: document external reference and MIT attribution policy, queue ACK vs durable commit, trusted input classification, supported local route, exact experimental timing values, normal/exception behavior, and explicit M5.1 deferments. In Blueprint mark M5.0 implemented only for acceptance criteria that have actually passed; separate any pending tests.
- [ ] **Step 5: Commit** as `docs: verify M5.0 perception batching` with the required coauthor trailer. Leave all commits local; do not push or create a PR without a separate request.

## Self-review / acceptance gate

- **No accidental M5.1:** Ambient observations are only auditable in M5.0; no VLM/game/Discord context projection or extra behavior instructions were added.
- **No double source of truth:** Journal remains canonical; the Bus is ephemeral and explicitly not crash-durable before commit.
- **One actual Fast turn:** A burst is represented by multiple raw perceptions and exactly one synthesized `user.message.completed` plus one terminal reply; existing SQLite/Deep and Hot/Cold invariants still apply.
- **Untrusted source metadata:** Source adapters cannot gain permission to call tools or override developer instructions through perception payloads. Future source integrations require explicit trust validation.
- **Precise evidence:** Tests distinguish queue batching from durable commit, model response from provenance and prefix stability from cache-hit measurements.

## Execution handoff

**Recommended: Native**, because Tasks 1–3 share a small sequential API boundary and the significant risk lies in Journal/Fast lifecycle correctness; one whole-branch review after integration is efficient. A separate reviewer must not use GPT-6 Astra. Review this specification and plan before implementation. No implementation or repository write was made as part of writing these documents.
