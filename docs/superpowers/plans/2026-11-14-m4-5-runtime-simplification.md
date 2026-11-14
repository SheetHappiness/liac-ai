# M4.5 Luna-Driven Runtime Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for Native execution, or superpowers:subagent-driven-development if selected. Steps use checkbox (`- [x]`) syntax. The user's plan review overrides default TDD: implement first, then perform only the short technical checks below.

**Goal:** Give Luna direct control over Markdown and autonomous intentions while retaining asynchronous Fast, durable history and Conversation Lab.

**Architecture:** Complete direct Luna → Markdown first and verify the stable prompt prefix before changing initiative or UI. Keep one serialized Deep worker, existing SQLite storage and frozen Fast snapshots. Remove approval from active execution paths without requiring wholesale removal of historical classes.

**Tech Stack:** Python 3.12+, asyncio, SQLite, existing HTTPX/Nemotron, confined OMP SDK and optional PySide6. No new dependencies or frameworks.

**Spec:** [Original requirements](../specs/2026-11-14-m4-5-runtime-simplification-requirements.md), amended by the user's review: minimal post-implementation checks, temporary degraded Epoch recovery, visible pending intent and staged scope.

## Global Constraints

- **Luna owns cognition. Runtime owns execution.** Fast never waits for Luna inference.
- Prompt order: stable identity → immutable Epoch → exact history → Markdown → current input. Preserve renderer, tokenizer, BOS handling, streaming and frozen snapshots.
- Keep Journal, short atomic transactions, context.md projection, local budgets, cancellation/restart and OMP confinement.
- No per-task RED/GREEN cycles, mandatory full-suite run, behavioral evals, new test frameworks, long simulation or cache benchmark. Adapt existing checks only where affected interfaces require it; do not expand tests as a separate workstream.
- English application text/code comments. No scheduler framework, new database, abstraction layer or model filesystem/shell access.
- One meaningful implementation commit after verification; include `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. No push or PR.
- Execution authorized by the user in a separate branch. Implemented on `codex/m4-5-runtime-simplification`; see the implementation report for actual checks and limits.

## Review Focus

1. Delayed Luna result: newer dialogue/Epoch does not veto Markdown, mutate active Fast or acknowledge unseen events.
2. Offline compaction: omitting an oversized Epoch is temporary degradation of Fast's projection, never deletion of Journal or irreversible forgetting.
3. Topic changes: Luna sees pending intent and can cancel/replace it; Runtime does not judge relevance.
4. Persistence/delivery: preserve atomic commits, consume-once initiative, user priority and owned-task cancellation.
5. Old archives: preserve read-only replay, historical links, capture gaps and interrupted-speech provenance with local fallbacks.

These guide code inspection; they do not require five new regression suites. The user explicitly limits verification to the four short checks below.

---

## Starting point and change map

Initial planning verified local HEAD and fetched M4.4 at `ed3bc8646c9e4df214d6330b4e9eadbc5ace17ba`. Recheck the actual M4.4 tip when executing. Create `codex/m4-5-runtime-simplification` from that tip, not main, preserving unrelated work and planning documents.

| Area | Keep | Change only where necessary |
|---|---|---|
| `contracts/deep.py`, `minds/luna.py` | Frozen envelopes, correlation, bounded decoding | Direct text instead of Markdown evidence/authority metadata |
| `runtime/journal.py`, `runtime/deep.py` | Serialized worker, atomic state/cursor commit, bounded retry, projection | Bypass proposal approval/dependencies/fingerprints for the new flow |
| `context.py`, `contracts/context.py` | Epoch storage, local budgets, terminal boundaries, prompt order | Luna-authored summary and temporary budget-only fallback |
| `runtime/orchestrator.py`, `app.py`, `cli.py` | One stream, input lock, cancellation/restart, initiative opt-in | Remove content eligibility, anchor, TTL/cooldown and revision expiry |
| `lab/{host,archive,report}.py`, `desktop/window.py` | Existing readers, timeline and archive format | Minimal new-result display and old-data fallback |
| `minds/{omp,nemotron,lmstudio}.py`, `runtime/context_file.py`, `tracing.py` | Existing mechanisms | No planned rewrite |

`NoteProposal`, `DeepDecision`, `UpdateResult`, `runtime/state.py` and internal compaction classes may remain for unaffected callers or legacy data. Do not route new Markdown through behavioral approval. Remove a helper only when bypassing it leaves it unused and deletion is local. Eradicating every historical class is not a completion criterion.

## Target interfaces

Keep the existing OMP text transport and `DeepMind.propose(request)` port. New inference uses this small schema-v3 envelope:

```json
{"schema_version":3,"note":null,"compaction":null,"initiative":null}
```

- `note`: whole Markdown string/null. Null preserves; empty clears; identical text preserves revision. Keep 32768 UTF-8 bytes and configured token budget (2048 default).
- `compaction`: summary string/null when requested; empty deliberately retains no summary. Keep 8000-character item ceiling and existing scaled 2048-token epoch-block budget. Store new text in one existing `ContextItem(text, (), 'summary')`; no per-fact evidence checks. Read old items unchanged.
- `initiative`: null or `{action:"none"}` preserves; `{action:"cancel"}` withdraws; `{action:"speak",intent:"...",delay_seconds:0}` replaces. Delay defaults to zero from durable application, finite/nonnegative/non-boolean. Keep 1000-character intent ceiling; no required reason, sources, TTL or cooldown.
- Final frozen contracts: `InitiativeSpeak(intent: str, delay_seconds: float = 0.0)`, fieldless `InitiativeCancel`, and `DeepResult(schema_version: int, request_id: str, note: str | None = None, compaction: str | None = None, initiative: InitiativeSpeak | InitiativeCancel | None = None)`. Implement lifecycle changes only in their owning task; do not expand Task 1 to finish initiative early.
- `DeepRequest` retains correlation, snapshot, cursor, events, optional compaction and budget. Task 3 adds `pending_initiative: Event | None = None`; `initiative_allowed` means owner opt-in only. Remove timing fields alongside their callers.
- `Journal.apply_deep(request: DeepRequest, result: DeepResult) -> dict[str, object]` returns execution facts: `context` changed/unchanged, `revision`, `epoch` changed/unchanged/superseded, `epoch_version`, `initiative` scheduled/cancelled/unchanged/disabled, and `through`. No new approval class.
- Keep one `deep.batch.completed` event with result, application facts and observed range. Compare stored result/range directly for replay/conflicting IDs; no proposal fingerprints or repeated execution.
- Emit `deep.applied` containing result/application/before/after/metrics; technical failure remains `deep.failed`. Keep historical `deep.decision` readable and existing epoch/initiative event names for correlation.

### Task 1: Complete direct Luna → Markdown and verify the Fast boundary

**Files:** `docs/PROJECT_BLUEPRINT.md`; relevant `AGENTS.md`; `contracts/deep.py`; `minds/{luna.py,fake.py,deep.md,character.md}`; `runtime/{journal,deep}.py`; `context.py`. Touch state/protocol/orchestrator interfaces only where a real caller requires it.

**Interfaces:** Implement `parse_result(text: str, request: DeepRequest) -> DeepResult` and the direct-note part of `Journal.apply_deep(...)` above. Reuse the existing file projection and Fast ports.

- [x] **Step 1: Prepare the branch.** Use `superpowers:using-git-worktrees`; fetch M4.4, inspect intervening changes and create the M4.5 branch without resetting unrelated work.
- [x] **Step 2: Update the architecture before code.** Rewrite Blueprint D-06/D-07, Ownership and Model Roles, I-05 and Luna → Fast protocol. Luna owns content; Runtime persists/executes it. Align module guidance for the path being changed. Update compaction/initiative sections as those tasks land; keep immutable identity and tool isolation.
- [x] **Step 3: Implement direct Markdown.** Parse string/null without source IDs or NoteProposal construction. Keep technical decoding/size/token limits. Atomically replace changed text, increment revision only for a change, record execution and acknowledge only the captured range. New dialogue or a local Epoch switch does not veto Markdown. Technical failure preserves the cursor; reuse startup/post-change context.md projection. Leave unaffected historical APIs alone.
- [x] **Step 4: Wire the worker and roles.** Adapt FakeDeep and worker result consumption. Make Luna's Markdown the current behavioral perspective and Nemotron its natural wording. Keep identity short; change only the Markdown tail wrapper, not renderer/tokenizer/transport. Preserve frozen snapshots and raw capture; defer presentation cleanup to Task 4.
- [x] **Step 5: Run checks A–C below before proceeding.** Confirm Fast independence, next-request Markdown propagation and identical stable-prefix bytes. This is the first working deliverable. Fix a failed check before touching initiative/UI; no test-first stage or broad suite.

### Task 2: Simplify compaction with temporary degradation and recovery

**Files:** `context.py`; `contracts/context.py`; `runtime/{journal,deep,orchestrator}.py`. Adapt an existing compaction verifier caller only if necessary.

**Interfaces:** Keep `ContextCompiler.prepare_epoch(snapshot: FastSnapshot, message: FastInput) -> CompactionProposal | None` and `validate_compaction(snapshot: FastSnapshot, proposal: CompactionProposal) -> None` as internal technical ports. `CompactionInput(cutoff: int, events: tuple[Event, ...])` supplies canonical dialogue; prior Epoch is captured separately.

- [x] **Step 1: Apply Luna's compacted content.** Translate non-null text to zero/one summary items at the captured cutoff. Remove source/extract-content approval for new summaries. Keep terminal boundaries, epoch ordering and actual combined Markdown/summary capacity. A superseded summary cannot rewind the cutoff and does not veto Markdown. Do not rewrite historical Epoch rows.
- [x] **Step 2: Remove Runtime memory ranking.** Keep local counting and current 75% asynchronous/90% local pressure thresholds. Fit a suffix of whole terminal turns within the existing three-turn/2048-token overlap cap. Keep the previous Epoch whole when it fits; omit it from the new Fast projection only when necessary. Never rank snippets or retain an oldest-user anchor as meaningful memory. Current input/Markdown remain whole, or fail explicitly if required content cannot fit.
- [x] **Step 3: Persist temporary degradation in existing events.** Budget-only epoch transitions include `mode='budget_only'`, `recovery_pending=true`, the previous meaningful Epoch version and affected canonical range in their existing event payload. Preserve that meaningful reference across repeated fallbacks. Keep old Epoch rows and all Journal events. Surface degraded context in current diagnostics/traces; never describe it as Luna-authorized forgetting.
- [x] **Step 4: Recover even after pressure falls.** Reconstruct pending recovery from persisted epoch/application events on restart and when preparing the next ordinary or explicitly retried Deep cycle. While pending, include compaction input even when the current Fast projection is now below pressure thresholds. Supply the previous meaningful Epoch and canonical history needed to rebuild the affected range, including history omitted from Fast. Only a successfully applied Luna Epoch clears recovery; null, superseded output or technical failure leaves it pending. Reuse bounded retry and `/retry`, with no polling service. Request-size overflow remains an explicit continuing degradation, not silent forgetting.

### Task 3: Simplify initiative after the direct flow works

**Files:** `contracts/deep.py`; `runtime/{journal,deep,orchestrator}.py`; `app.py`; `cli.py`; `minds/{luna.py,deep.md}`.

**Interfaces:** `Journal.claim_initiative(proposal_id: str, snapshot: FastSnapshot) -> CharacterInitiative | None` atomically consumes pending work with character input/reply.started. `_wait_initiative(proposal_id: str) -> None` uses the current delay helper/input lock; `_on_deep_applied(self) -> None` synchronizes the waiter. Preserve legacy CharacterInitiative shape with an empty reason for new commands.

- [x] **Step 1: Show pending intent to Luna.** Populate `DeepRequest.pending_initiative` using the existing event's intent, ID and ready time. The next ordinary analysis also sees new dialogue and delivery/cancellation outcomes. Explain in deep.md that Luna should reconsider pending work when the topic changes; none preserves it. No timer-triggered Luna calls.
- [x] **Step 2: Remove behavioral eligibility.** Speak replaces one pending command, cancel withdraws, none preserves its original deadline. Remove evidence, anchor, one-attempt-per-user, semantic duplicate keys, revision/Epoch invalidation and Runtime TTL/cooldown. Keep owner opt-in, deterministic execution IDs and atomic consume-once. Remove old Config/CLI timing fields when adapting their callers, without unrelated cleanup.
- [x] **Step 3: Keep delivery technical.** After Luna's delay, wait for idle Fast, yield to queued user input and claim under the input lock. User input preempts active autonomous speech but does not automatically cancel waiting work. Luna can replace/cancel it at the next analysis. Explicit Cancel Fast, shutdown and restart withdraw pending speech. Cancelling a waiter must not cancel another user stream. No eligibility evaluator or scheduler framework.
- [x] **Step 4: Run check D below.** Confirm preemption, stream closure and owned-task shutdown. Inspect retained claim/restart paths; do not create a new lifecycle-test campaign.

### Task 4: Adapt Lab consumers, record limits and commit once

**Files:** `lab/{host,archive,report}.py`; `desktop/window.py`; `README.md`; create `docs/M4_5_RUNTIME_SIMPLIFICATION.md`. Existing tests/scripts change only for broken active callers or intentionally retired assertions.

**Interfaces:** Preserve `RunReader.related(turn_id)`, `context_at(sequence)` and paging. Existing consumers read `deep.applied.application` with a small fallback for historical `deep.decision.decision`. `config_from_dict(data: dict) -> Config` discards only the three known retired initiative timing fields.

- [x] **Step 1: Adapt existing views.** Show Luna result, context changed/unchanged and technical error without approval wording. Preserve captured prompts/results, historical Markdown, Epoch/degradation, initiative, timing and process relationships. Keep old archives provider-free/read-only, with gaps and interrupted-speech provenance. No new debugger/normalization layer or unrelated report redesign.
- [x] **Step 2: Resolve necessary callers.** Search touched APIs in app/scripts/existing checks. Adapt only affected callers and retire obsolete policy assertions. Historical classes may stay where useful. Do not rewrite all tests/reports to eradicate old terminology; historical provider measurements remain historical.
- [x] **Step 3: Finish bounded verification.** Reuse checks A–C unless subsequent edits affect them; repeat only affected checks. Run `git diff --check`. No mandatory full suite, added fault-injection harness, behavioral evaluation, provider simulation, native UI automation or cache benchmark.
- [x] **Step 4: Write the report.** Record actual direct flow, removed constraints, technical Runtime duties, temporary Epoch degradation/recovery, initiative semantics, files actually retired and checks actually performed. State that pending speech may become stale until Luna cancels it and semantic recall is reduced during degradation. Prompt-byte equality does not prove backend KV reuse; fake checks do not establish live provider compatibility.
- [x] **Step 5: Review and commit once.** Stage only intended changes and plan/spec/report. `/docs` is ignored: force-add exact new document paths, not the directory. Commit `Simplify Runtime around Luna-owned context and initiative` with the required co-author trailer. No push or PR.

## Four short post-implementation checks

Reuse current runtime/compiler and lightweight controllable fakes or existing checks. No new persistent suite is required. Keep temporary evidence ignored/private.

| Check | Action | Passing evidence |
|---|---|---|
| A — Fast independence | Hold Deep, submit user input and consume Fast before releasing Deep | Fast produces text while Deep remains held |
| B — Markdown propagation | Release changed Markdown during that stream, then submit another input | Active snapshot stays old; next request has exact new Markdown; null/identical preserves revision, empty clears |
| C — Stable KV prefix | Render the same identity/Epoch/history/input with two Markdown versions | Bytes before the Markdown block are identical; only variable tail changes |
| D — Cancellation | Start autonomous streaming, submit user input, then close Runtime | Old stream closes, user takes priority, partial is not completed history, no owned tasks remain |

Report actual environment/results. Fix a demonstrated fault and repeat that check, without expanding this into a testing workstream. These checks establish technical behavior, not naturalness, semantic recall or measured backend cache reuse.

## Self-review and handoff

Coverage: direct Markdown/architecture → Task 1; compaction → Task 2; initiative → Task 3; Lab/docs/local commit → Task 4. Direct Markdown and stable-prefix verification precede initiative/UI. Temporary fallback cannot delete canonical memory; durable pending recovery survives restart and reduced pressure. Luna sees pending intentions; Runtime relevance checks stay removed. Historical class deletion is optional local cleanup.

Recommend Native execution because these tasks share worker/Journal interfaces and benefit from sequential changes. Executed inline after user authorization; one final independent review informed the bounded fix pass.
