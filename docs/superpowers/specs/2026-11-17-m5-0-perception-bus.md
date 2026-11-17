# M5.0 – Perception Bus Specification

**Status:** PROPOSED design, not implemented. **Date:** 2026-11-17.

## Goal

Adapt ProjectBEA's perception intake and quiet-gap batching to Liac without importing Bea's single-Consciousness architecture. Deliver a useful first slice: several local text inputs can produce one Fast reply while preserving each source event. Ambient observations can be ingested without forcing Bolt to speak. Perception-to-context routing, VLM and game control belong to later milestones.

## Reference implementation

- ProjectBEA `src/core/perception/bus.py`, `types.py`, `attention/gate.py`, `tests/test_perception_bus.py` on `main` (reviewed 2026-11-17; main SHA `f2186fc647db3f9ae65e6463b9f82c882bdca68b`).
- Upstream license: MIT, copyright © 2026 Emanuele Faraci. If implementation copies substantial source text, retain the original copyright and license notices. A small independent adaptation of the documented behavior is preferred.
- Liac baseline: `codex/m4-8-context-handoff` based on M4.7. Verify actual HEAD and branch status at execution time. The main branch may differ.

## DECIDED boundaries

1. **Ownership:** Perception Bus owns transient intake, ordering and batching. Journal remains the only durable technical record. Runtime owns Fast cancellation, snapshots and committing user turns. Luna only preserves and organizes experience, never chooses Bolt's speech or reactions.
2. **No hidden prompt policy:** The bus does not write prompts, compile context, call models, or assign personalities. No `Consciousness`, `SkillRegistry`, attention score or behavior-beat port from Bea.
3. **Input:** Immutable `Perception` records with a stable ID, source, kind, conversation key, optional stable author ID, content, UTC timestamp and explicit trusted delivery class (`direct`, `ambient`, `noise`). Originating adapters own the IDs and delivery classification. Display names are not identity keys.
4. **Grouping:** For the same conversation key, a batch ends after a quiet gap measured from the *last arrival*, or a hard `max_window` measured from its *first arrival*. Different keys never combine; arrival order is monotonic ingress order rather than untrusted wall-clock timestamps. A live observation shortens, not lengthens, the gap in a mixed batch.
5. **Initial timing:** `live_gap=0.30 s`, `text_gap=0.75 s`, `max_window=2.0 s`; bounded `max_pending=256`. These are configurable experimental defaults, not performance guarantees.
6. **Backpressure:** Accepted meaningful perceptions must not be silently discarded. When the queue is full, explicitly reject new meaningful input with a named overload error; the adapter may retry. Duplicated IDs are idempotent. Repeated `noise`/state heartbeats may be coalesced or discarded, with diagnostic counts. Queue acceptance alone does **not** promise durability before Journal commit.
7. **M5.0 vertical slice:** Trusted local chat perceptions for one conversation key are rendered into **one** `UserMessage` per batch, joined with newlines, after preserving individual raw events. The original Runtime `submit(UserMessage)` entrypoint remains unchanged. Cross-channel or multi-author conversational rendering is future work, not a reason to pollute Bolt's minimal identity with routing metadata.
8. **Atomic ingestion:** The raw events and one synthesized `user.message.completed` input are written together transactionally. Stable batch-derived IDs make retries idempotent; a conflict rolls back the entire ingestion. Existing restart logic closes an unfinished Fast turn without claiming it completed. Raw event text must never be lost when building the grouped text.
9. **Ambient vs direct:** Ambient meaningful observations may be persisted, but cannot start or cancel Fast. In M5.0 they are **not yet projected to Bolt or semantically processed by Luna**. M5.1 introduces canonical perception routing and active Live State. Noise never triggers Fast or Luna.
10. **M4.8 compatibility:** Do not change ContextCompiler, Hot/Cold cutoff, Epoch, tokenizer, Nemotron, Deep schema v3 or fallback behavior. A synthesized chat group is one completed turn with one terminal reply; individual raw `perception.received` events do not open user/character turns.
11. **No scope creep:** No external Discord/voice/game/VLM adapters, idle-triggered monologue, autonomous speech, game actions, new dependency, database schema change, background worker, model instruction or PR in M5.0. Initiative remains disabled.
12. **Private data and process:** Runtime data stays in ignored `.data/`; English application UI and code comments. Each implementation commit has `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. No GPT-6 Astra subagents.

## Success criteria

- Three near-consecutive local messages become one Fast response, yet each original perception is inspectable in SQLite alongside one synthesized canonical dialogue turn.
- A continuous stream closes at `max_window`; another conversation key never leaks into its batch.
- Mixed chat and live event arrival uses the faster quiet gap; repeated noise does not postpone delivery or cause speech.
- Full queue explicitly rejects meaningful input; duplicate replay is idempotent; conflicting duplicates are transactional failures.
- Ambient-only input has no Fast call and does not change frozen Fast snapshots.
- Existing deep cursor, Hot/Cold cutoff, Luna compaction/recovery and restart tests continue to pass; no new inference loop appears.

## Next milestones (not M5.0 acceptance)

- **M5.1:** route meaningful perceptions to Bolt's bounded current context and Luna's semantic memory, maintain a distinct volatile Live State, avoid screenshot/heartbeat spam.
- **Later:** speech/Discord/VLM adapters; Neuro-SDK-like or Cyberpunk-mod-like structured observations and action choices owned by Bolt, enforced by Runtime permission checks.
