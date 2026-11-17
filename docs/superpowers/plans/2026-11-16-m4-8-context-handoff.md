# M4.8 Asynchronous Context Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve approximately 1024 tokens of whole raw recent turns while Luna asynchronously summarizes older history.

**Architecture:** Add pure semantic-cutoff selection to the existing ContextCompiler and inject it into Journal request construction through the existing DeepWorker. Keep immutable Fast snapshots, atomic Epoch application, canonical SQLite history and durable fallback recovery; retain the current Luna request's `compaction.through` boundary representation.

**Tech Stack:** Python 3.12+, stdlib unittest/asyncio/SQLite, existing pinned Nemotron tokenizer, HTTPX and OMP RPC.

**Spec:** [M4.8 specification](../specs/2026-11-16-m4-8-context-handoff.md). Read both documents. During execution copy these reviewed files to the same repository-relative paths.

## Global Constraints

- Context window: 16,384 tokens including generation reserve; Hot suffix target: 1024 tokens.
- Preserve the 75% preparation trigger, existing emergency fallback and prefix order.
- Summary is authored only by Luna. Hot is raw and unchanged.
- Frozen active Fast snapshots cannot change. No inference occurs inside SQLite transactions and Bolt never waits for Luna.
- Preserve M4.7 Bolt/Luna roles, Nemotron template and schema-v3 result envelope.
- No new memory store, worker, persistence format, Perception Bus, VLM or Neuro SDK.
- English application UI and code comments; no GPT-6 Astra subagents.
- Every commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`; credit the same contributor in any explicitly requested PR.
- Execution uses `codex/m4-8-context-handoff` based on verified M4.7. Exactly two milestone commits; no automatic push or PR.

## Review Focus

1. Interleaved turns and cancellation/failure: cutoff must close every earlier opened turn (Task 1).
2. Empty history, all-Hot history and a single oversized turn: no empty-Cold request or split turn (Task 1).
3. Fallback overtakes Luna, including an equal cutoff: reject rewind but permit meaningful same-cutoff recovery (Task 1).
4. Restart with pending recovery and a batch behind fallback: recover canonical Cold without an invalid watermark or inference loop (Task 1).
5. Unicode/newlines and Markdown changes: preserve Hot UTF-8 bytes and rendered prefix boundaries (Tasks 1 and 2).

---

## Source map and execution setup

Inspected base: clean `codex/m4-7-bolt-luna-roles`, `ad88108`, at `C:/Users/shtvl/.codex/worktrees/m4-7-bolt-luna-roles/liac-ai`. Recheck before implementation; the main checkout is on an older M1 branch and has unrelated untracked plans.

Read root and nearest AGENTS.md plus `docs/PROJECT_BLUEPRINT.md` §9.1, `docs/M4_7_BOLT_LUNA_ROLES.md` and `docs/M4_6_LUNA_PROMPT_SERIALIZATION.md`.

| File | Responsibility/change |
| --- | --- |
| `src/vtuber/context.py` | Pure token-counted Hot/Cold selection; leave budget fallback policy intact |
| `src/vtuber/contracts/protocols.py` | Add selector method to existing ContextPolicy |
| `src/vtuber/runtime/journal.py` | Build immutable request with selected cutoff and recovery floor |
| `src/vtuber/runtime/deep.py` | Pass selector; keep worker lifecycle/application unchanged |
| `src/vtuber/minds/deep.md` | State exact Cold-only summary boundary and untouched Hot |
| `tests/test_context.py`, `tests/test_deep.py` | Boundary, race, restart and raw/prefix regressions; update direct callers and policy doubles |
| `scripts/verify_m2_luna.py` | Small controlled live phase using existing provider/evidence helpers |
| `docs/M4_8_CONTEXT_HANDOFF.md`, blueprint §9.1 | Actual acceptance evidence and revised lifecycle description |

`contracts/deep.py` and `minds/luna.py` need no planned schema change: `CompactionInput(cutoff, events)` and rendered `compaction.through = {history, new}` already support a partial boundary. Tests must prove this with Hot present in both arrays. Do not expose internal IDs just to mark Cold.

### Task 1: Deliver token-counted cutoff and safe asynchronous handoff

**Files:** Modify the first six source/test rows above; create no runtime modules. Include the reviewed spec and plan in this first commit.

**Interfaces:**
- Consume existing `FastSnapshot`, `ContextCompiler.count(messages)`, `terminal_turns`, `CompactionInput`, `DeepRequest.recovery_epoch`, `Journal.epoch_recovery()` and `render_request(request)`.
- Produce `ContextCompiler.semantic_cutoff(self, snapshot: FastSnapshot) -> int | None` and the matching ContextPolicy method. Return a closed Cold cutoff strictly newer than the active Epoch cutoff, or None when no Cold exists.
- Add keyword `cutoff_selector: Callable[[FastSnapshot], int | None] | None = None` to `Journal.deep_request(...) -> DeepRequest | None`. DeepWorker passes `self.context_policy.semantic_cutoff` when a policy exists.
- Explicit compact=True without a selector raises ValueError naming cutoff_selector; pending fallback recovery without a selector still covers its durable floor. Update direct compaction test callers to pass a real compiler selector. App production wiring already supplies ContextCompiler; no new configuration flag.

- [ ] **Step 1: Prepare isolated execution and baseline.** Use using-git-worktrees at execution time. Confirm the actual M4.7 HEAD, clean state and branch ownership; create the M4.8 worktree from it. Copy the reviewed planning documents there. Set `$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'`; use the existing project `.venv/Scripts/python.exe` after verifying it is available. Run `python -m unittest discover -s tests -v`. Record failures; M4.7's report mentions a desktop error, which must be verified rather than assumed current.

- [ ] **Step 2: Write failing pure selection tests** in `ContextTests`. Use a deterministic role-aware counter with explicit framing cost and fixtures whose whole-turn dialogue costs are exactly stated below. Assert calls use the configured message counter; never substitute byte length for live tokenization.

```python
# Each row is a separate test, with snapshots built using real turn IDs
# and terminal sequence numbers. Counter fixture prices whole suffix renders.
def test_semantic_cutoff_keeps_shortest_suffix_reaching_1024(self):
    # oldest -> newest dialogue costs: 900, 600, 500
    self.assertEqual(compiler.semantic_cutoff(snapshot), first_terminal)
    self.assertEqual(retained_cost, 1100)

def test_semantic_cutoff_keeps_1400_token_last_turn_whole(self):
    self.assertEqual(compiler.semantic_cutoff(snapshot), penultimate_terminal)
    self.assertEqual(retained_cost, 1400)

def test_semantic_cutoff_keeps_exact_1024(self):
    self.assertEqual(compiler.semantic_cutoff(snapshot), penultimate_terminal)
    self.assertEqual(retained_cost, 1024)

def test_semantic_cutoff_without_cold(self):
    # subTest: empty; only 700; only 1400; two turns totaling 1023
    self.assertIsNone(compiler.semantic_cutoff(snapshot))

def test_semantic_cutoff_respects_globally_closed_boundaries(self):
    # subTest: interleaved, unfinished, cancelled, failed
    self.assertIn(cutoff, globally_closed_cutoffs)
    self.assertFalse(any(start <= cutoff < end for start, end in turn_ranges))
```

For these tests add only a small local fixture builder, not a general framework. Derive retained_cost from actual retained messages with the test counter. Include a nonadditive framing case so an implementation summing independent event counts fails.

- [ ] **Step 3: Run the failing tests.** `python -m unittest test_context -v`; expect missing `semantic_cutoff` errors in the new cases, with existing cases unchanged.

- [ ] **Step 4: Implement the selector and protocol method.** In `context.py`, use the existing dialogue rendering and `count` method to measure each whole suffix against empty dialogue with identical fixed framing. Scan suffixes from newest to oldest until cost reaches 1024. Select the newest globally closed boundary at or before the suffix start; retaining extra turns is allowed. Never select the final terminal and leave Hot empty. Return None if the preserved suffix consumes all raw history. Use `snapshot.terminal_turns` for cancelled/failed turns and enforce closure across interleaved users; do not count summaries or Markdown toward Hot. Add no target CLI option, dependency or new manager. Run Step 3 again; all context cases must pass.

- [ ] **Step 5: Write failing Journal/worker/renderer regressions.** Reuse `DeepJournalTests.user/finish`, temporary SQLite and `DeepWorkerTests` asyncio barriers. Extend helpers only to control reply text and turn sizes. Each named test below must assert the listed expressions with fixture-bound variables:

```python
def test_cold_request_preserves_hot_bytes(self):
    self.assertEqual(request.compaction.cutoff, cold_terminal.sequence)
    self.assertTrue(all(e.sequence <= request.compaction.cutoff
                        for e in request.compaction.events))
    self.assertEqual(after_hot_utf8, before_hot_utf8)
    self.assertEqual(rendered_cold_texts, expected_cold_texts)
    self.assertTrue(set(hot_texts).isdisjoint(rendered_cold_texts))

def test_fallback_supersedes_older_summary(self):
    self.assertEqual(application['epoch'], 'superseded')
    self.assertEqual(journal.context_epoch('primary'), fallback_epoch)
    self.assertTrue(journal.epoch_recovery('primary')['recovery_pending'])

def test_equal_cutoff_recovery_and_restart(self):
    self.assertEqual(recovery.compaction.cutoff, fallback_cutoff)
    self.assertEqual(recovery.recovery_epoch, meaningful_epoch)
    self.assertEqual(restarted_hot_utf8, original_hot_utf8)
    self.assertEqual(restarted_epoch.items[0].text, 'Cold continuity')
    self.assertFalse(journal.epoch_recovery('primary')['recovery_pending'])

async def test_delayed_summary_keeps_fast_snapshot_and_new_turns(self):
    self.assertFalse(luna_release.is_set())  # Fast completed before release
    self.assertEqual(captured_snapshot, original_snapshot)
    self.assertEqual(captured_prompt, original_prompt)
    self.assertTrue(set(hot_ids + newer_ids) <= set(retained_ids))
    self.assertEqual(after_note_prefix_bytes, before_note_prefix_bytes)
```

Add `test_recovery_defers_batch_behind_fallback` asserting no invalid-cutoff proposal and later recovery covers the durable floor. Add `test_null_summary_does_not_spin` asserting one attempted compaction at an unchanged request key and recovery remains pending; explicit retry is permitted. Extend the delayed test with `test_overflow_during_luna_uses_budget_fallback`: while Luna is held, submit an input beyond current capacity, assert a budget-only Epoch transition and completed Fast response, then verify supersession/recovery after release. An input whose required content alone is too large must raise `ContextBudgetExceeded` without deleting canonical events.

Renderer tests must cover a split inside history and a split inside new in separate ordered fixtures; a single chronological cutoff cannot split both arrays simultaneously. Resolve `through.history/new` by slicing each array, and assert those slices contain exactly Cold. Use Unicode, CRLF and whitespace in Hot. Pin restart both after successful semantic application and while fallback recovery is pending. Keep existing atomic rollback, replay, pressure and cancellation tests.

- [ ] **Step 6: Run new integration tests red.** `python -m unittest test_deep -v`; expect selector-keyword errors or explicit cutoff/retention assertion failures. Record the failing cases before editing production integration.

- [ ] **Step 7: Wire cutoff selection and Cold-only instruction.** Build Journal's immutable snapshot before constructing CompactionInput. For `compact=True`, invoke the injected selector; use its cutoff for ordinary preparation. For recovery use the later of that cutoff and active fallback cutoff, sourcing events after the meaningful Epoch cutoff. Defer a recovery floor outside the safe observed range. Keep selection synchronous with request construction; no await or provider call inside the transaction. Preserve cursor acknowledgement, attempted-key deduplication, latest-turn batching and existing late-result `< active cutoff` supersession. Equal cutoff remains eligible for meaningful recovery. Pass the selector from DeepWorker and update every policy double/direct caller found by `rg -n 'deep_request\(|class Policy|context_policy=' src tests scripts`.

In `deep.md`, clarify that only the initial counts designated by `compaction.through` and the previous Epoch belong to summary; later history/new items are raw Hot for understanding and must not be summarized again. Change no Bolt instructions. Preserve JSON field names, M4.7 role wording and Nemotron ordering.

- [ ] **Step 8: Run verification green.** `python -m unittest test_context test_deep test_journal test_luna test_runtime_lifecycle -v`, then `python -m unittest discover -s tests -v`, then `git diff --check`. New tests must pass and no baseline regression may remain. Run with the same interpreter/import paths as Step 1; do not hide pre-existing failures behind a green subset.

- [ ] **Step 9: Commit the complete implementation.** Stage only the Task 1 files and reviewed planning documents. `git commit -m "feat: preserve raw hot turns during asynchronous compaction" -m "Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>"`.

### Task 2: Verify real handoff, restart and short-history prefix caching

**Files:** Modify `scripts/verify_m2_luna.py`, `docs/PROJECT_BLUEPRINT.md` §9.1; create `docs/M4_8_CONTEXT_HANDOFF.md`. Keep private evidence under ignored `.data/`.

**Interfaces:** Consume Task 1's selector, existing Config/Runtime/Luna adapters, trace evidence, `render_request`, and Nemotron renderer. Add one verifier phase `--phase handoff` dispatched to `async def context_handoff(evidence) -> None`. Preserve all existing phases and defaults. Use existing evidence writers and provider setup; no new worker or memory format.

- [ ] **Step 1: Add the controlled verifier with a small self-check.** Extend existing `--self-check` to assert Cold/Hot evidence classification: a forged row with Hot text inside the Cold slice fails, and a valid boundary row passes. Add no new general evidence framework. The handoff phase uses the configured real tokenizer/provider, explicit 4096/16384 windows, bounded waits and owned-resource cleanup. Reuse the existing manual Runtime path to avoid the known simulator formatting issue. It must save request cutoff/counts, Hot IDs/text bytes, actual provider summary, Epoch transitions, actual compiled Fast prompts and restart recall responses. Use one local generation of uniquely identifiable Cold facts and distinct Hot facts; never fabricate provider replies or summaries.

- [ ] **Step 2: Verify the harness.** `python scripts/verify_m2_luna.py --self-check`; expected PASS without provider inference. `python scripts/verify_m2_luna.py --help` must expose `handoff` and preserve existing choices.

- [ ] **Step 3: Preflight real providers without changing unrelated sessions.** Locate the existing ignored pinned tokenizer and verify fingerprint, Python environment, loaded Bolt checkpoint/context capacity and available OMP Luna model. Reuse existing assets; never assume another checkout contains them. Record actual model IDs, backend settings and baseline resource ownership. Use the verified English minimal identity and Initiative disabled. If providers/assets are unavailable, report the exact blocker and leave live acceptance incomplete.

- [ ] **Step 4: Run the bounded live phase.** From the M4.8 worktree, run the existing interpreter with `scripts/verify_m2_luna.py --phase handoff --endpoint http://127.0.0.1:1230 --model <verified-model-id> --tokenizer <verified-local-path> --omp-executable <verified-omp-path> --output .data/m4-8-results.jsonl`. Replace preflight placeholders with actual paths/IDs; do not install or download replacement models. Bound the entire phase to 600 seconds and 20 turns; stop once all evidence is captured. Failure to reach compaction within bounds is missing coverage, not a pass.

At 4096, add controlled real dialogue until the existing 75% trigger requests Cold compaction. Hold delivery of one actual Luna response with an asyncio barrier while Bolt completes another turn, then apply and inspect the real summary, byte-identical Hot and next Fast prompt. In the same bounded run, hold a later real response and submit a capacity-checked input causing emergency fallback; record this as an injected delay and budget-only degradation. Release, observe supersession/recovery, close Runtime/Journal, reopen the same database and ask for Cold and Hot facts. Assert persisted summary/Hot mechanically; report model recall verbatim as a separate outcome.

- [ ] **Step 5: Verify 16k prefix caching without filling history.** Use a fresh 16,384-token configuration and a few short real turns. Freeze the same Epoch/history/current input and render two prompts differing only in a valid Markdown update. Prime and submit through the existing adapter; compare exact prefix bytes and record local/provider token counts plus available prompt-evaluation/cache counters. Use any existing LM Studio log helpers as-is. A summary change is expected to change the prefix after identity. Do not run the existing synthetic `markdown-cache` phase unchanged: it manufactures 24 long history messages. Missing backend counters means prefix stability verified, cache reuse unproven.

- [ ] **Step 6: Write the evidence report and blueprint update.** Record actual commands/configuration, archive paths, boundaries, measured Hot cost, raw byte comparisons, next Fast prompt, restart answers and the fallback race. Separate automated assertions, real semantic assessment and unverified claims. Replace blueprint §9.1's statement that semantic cutoff always uses the latest terminal with the implemented Hot rule; preserve degraded-fallback language. Report any failed recall or unavailable cache counters. Stop only resources owned by this verification.

- [ ] **Step 7: Verify and commit documentation/support.** Rerun the self-check, targeted context/deep tests and `git diff --check`; inspect the staged diff for private transcripts/credentials. `git commit -m "docs: verify asynchronous context handoff and restart" -m "Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>"`. If live checks remain blocked, use an accurate pending-verification subject/report and leave milestone acceptance open. Do not claim M4.8 complete until required live evidence exists.

## Self-review and handoff

Coverage checked: all seven technical acceptance requirements map to Task 1; both requested live windows and overflow map to Task 2. No persistence/schema/template rewrite is planned. The selector is pure; Journal owns the atomic request/application boundary. The target is a minimum whole-turn suffix, and fallback's recovery floor explicitly takes precedence.

Recommended execution: **Native**, because this is one coupled lifecycle change with two commits and shared request/recovery interfaces. A fresh final reviewer may inspect the whole branch; GPT-6 Astra is excluded. Approved with minor changes on 2026-11-17: guarantee normal Hot using rendered count deltas; keep degraded fallback separate (888 tokens at 4096 with defaults); audit every deep_request caller and fail explicitly for missing selectors; preserve equal-cutoff recovery. Native execution selected by the implementer following the recommendation.
