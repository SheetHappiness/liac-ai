# M4.5 — Luna-Driven Runtime Simplification

Status: **DECIDED** architecture; **PROVISIONAL** provider acceptance.
Base: `codex/m4-4-conversation-lab` at `ed3bc8646c9e4df214d6330b4e9eadbc5ace17ba`.
Implementation branch: `codex/m4-5-runtime-simplification`. No push or PR.

## Direct context flow

Luna observes complete canonical exchanges through one serialized worker. Strict
schema-v3 JSON carries `note` (whole Markdown string/null), `compaction` (summary
string/null) and optional initiative. Null preserves; empty text clears; identical
Markdown preserves revision. SQLite applies content, execution facts and the
captured cursor range in one transaction. Duplicate request IDs compare stored
result/range directly; conflicting reuse fails. Technical failures preserve the
cursor and use existing bounded retry. No database migration or dependency added.

No source IDs, evidence approval, note revision/Epoch dependencies, behavioral
validators, proposal fingerprints or per-operation approval audits are required
by new Luna results. Ordinary newer dialogue and local Epoch transitions cannot
veto Markdown. context.md remains the existing off-loop projection, repaired at
startup. The active Fast request retains its frozen snapshot; the next sees the
latest document. Stable identity remains owner-authored and OMP stays confined.

## Context pressure and recovery

Luna selects the content of compacted Epochs. Runtime enforces local token budgets,
whole terminal turns and monotonic cutoffs; a superseded summary cannot rewind
history and does not veto Markdown. New summaries occupy zero/one existing
ContextItems without source evidence. Old Epoch rows remain readable.

The 75% asynchronous / 90% local pressure thresholds and three-turn/2048-token
suffix cap remain. Local fallback retains the previous Epoch whole if it fits;
otherwise it omits that Epoch from Fast's projection. No extract ranking or
oldest-user anchor remains. Required Markdown/current input stay whole or fail
explicitly. The actual input is checked by prepare_epoch; summary/Markdown checks
do not count the current input again as historical text plus a synthetic input.

Budget-only transitions record `mode`, `recovery_pending`, the previous meaningful
Epoch version and canonical range in existing events. Repeated fallbacks preserve
that reference. Recovery survives restart and lower context pressure. The next
ordinary analysis, startup or explicit retry receives the meaningful Epoch and
canonical history omitted from Fast. Applied Luna summary clears recovery;
null, superseded output and technical failure do not. Existing request-size
limits can postpone recovery explicitly; no history is deleted or silently
replaced by a claimed semantic memory. No new recovery service or scheduler.
Autonomous-only tails cannot trigger another Luna cycle, including under pressure;
startup and explicit retry are the only deliberate exceptions.

## Initiative and roles

Luna sees pending intent, deadline and delivery/cancellation events on ordinary
analysis. `none`/null preserves; `cancel` withdraws; `speak` replaces one pending
intent, with finite nonnegative delay from durable application (default zero).
The owner still opts in. Runtime no longer imposes evidence, user anchor,
one-attempt-per-user, semantic duplicate keys, revision/Epoch expiry, TTL or
cooldown. Old archived timing options are discarded on resume.

One owned waiter yields to user inputs and idle Fast under the input lock.
Atomic claim consumes once and appends character input/reply.started together.
New input preempts active autonomous speech; it does not withdraw waiting intent.
Explicit Cancel Fast, shutdown and restart withdraw pending speech. Cancelling
a waiter does not cancel a user stream. Nemotron realizes Luna's perspective in
Liac's voice and chooses the actual words.

## Lab and retained code

New traces use `deep.applied` with result, application facts, before/after snapshots
and timing; technical errors use `deep.failed`. Lab/UI read those records and keep
a small fallback for historical `deep.decision`. Historical context, Fast/Luna
links, capture gaps, interrupted turns, raw prompts and initiative events remain.
The summary distinguishes changed/unchanged context; old proposal counts are
explicitly legacy. No capture format, provider transport or Qt lifecycle rewrite.

Removed: unused `DeepDecision`, evidence helper, old initiative proposal/timing
validation, Runtime relevance/deduplication helpers and excerpt-ranking code.
Retained for independent existing callers: NoteProposal, UpdateResult, state.py,
apply_note and internal CompactionProposal/CompactionResult. Historical milestone
reports remain historical. Existing checks/scripts were adapted only where their
active contracts changed; obsolete fingerprint/behavioral approval assertions
were retired. No new persistent test framework or behavioral evaluation suite.

## Actual verification

Windows, Python 3.14 from the existing project virtual environment, source imports
via `PYTHONPATH=src;tests`. No live model or network inference.

- A: held Luna while Fast produced a partial response — passed.
- B: changed Markdown during streaming; frozen old snapshot, exact next-request
  document, null/identical revision preservation and empty clear — passed.
- C: compared rendered Nemotron prefix bytes for Markdown-only changes — identical.
- D: autonomous stream preempted by user; stream closed, partial excluded from
  completed history, one user stream and no owned tasks after shutdown — passed.
- Two existing targeted compaction checks were adapted/run after final review:
  exact budget with accepted current input; durable recovery across SQLite reopen,
  canonical replay below pressure, no autonomous feedback and explicit recovery.
- Python source syntax, CLI help startup and git diff whitespace checks — passed.

Final read-only review found synthetic input double counting and recovery-triggered
autonomous feedback. Both paths were corrected and the focused checks repeated.
A recovery fixture initially selected an audit-event cutoff; the check correctly
rejected it. The fixture now uses the actual terminal boundary.

Not run: full test suite, native Qt window, real Luna/Nemotron compatibility,
behavioral evaluation, long simulation or backend KV benchmark. Prompt-byte
equality proves stable input structure, not measured backend cache reuse.
Pending intent may be stale until Luna reconsiders it; semantic recall is reduced
during budget-only degradation. The old bundled executable predates this work.
