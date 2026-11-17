# M4.8 — Asynchronous Context Handoff

Implemented and verified locally on 2026-11-17, based on M4.7 `ad88108`.
Branch: `codex/m4-8-context-handoff`.

## Behavior

Normal semantic compaction preserves the shortest suffix of whole terminal turns
whose rendered history cost reaches 1024 tokens. ContextCompiler uses its configured
`count()` on complete message renders with and without that suffix; it does not
sum independent message estimates. A final 1400-token turn stays whole. With no
Cold history, no ordinary semantic summary is requested.

Journal injects this selection into the existing immutable Deep request. Luna's
existing `compaction.through` counts mark Cold precisely; Hot remains visible but
is excluded from summary sources. Markdown and earlier OMP recollection are not
compaction sources because they may already contain Hot. No new worker, store,
SQLite format, result schema, Bolt instruction or Nemotron template was added.

All `deep_request()` call sites in `src`, `tests` and `scripts` were audited.
DeepWorker supplies ContextPolicy's selector; direct compaction fixtures supply a
compiler selector, and the pressure-policy double explicitly implements it.
Other direct callers only observe dialogue. Explicit `compact=True` without a
selector raises a named ValueError rather than silently disabling compaction.
Pending fallback recovery still works without a selector.

Emergency fallback remains separate budget-only degradation: with a 4096-token
window, 512 output tokens and 32 safety tokens, its overlap budget is 888 tokens.
It cannot promise the normal 1024-token Hot target. Recovery uses the last
meaningful Epoch and canonical history, at least through the active fallback
cutoff. Equal-cutoff semantic replacement is permitted; older cutoffs are
superseded. A batch behind the recovery floor advances safely before recovery.

## Offline verification

The existing project virtual environment uses Python 3.14. Commands ran from the
M4.8 worktree with `PYTHONPATH=src;tests;vendor/omp-rpc/src`.

```powershell
python -m unittest test_context test_deep test_journal test_luna test_runtime_lifecycle -v
python -m unittest discover -s tests -v
python scripts/verify_m2_luna.py --self-check
git diff --check
```

- 66 targeted tests passed.
- Full suite: 129 tests, 128 passed, one baseline error:
  `test_desktop.WindowTests.test_chat_context_selection_and_offline_history`.
  `MainWindow.context` is absent. The clean M4.7 baseline reproduced the same error
  (117 tests, 116 passed); no desktop fix is included.
- New cutoff/request checks were observed failing before implementation and then
  passing. Coverage includes exact 1024, oversized/short/all-Hot histories,
  configured framing counts, interleaved/cancelled/failed turns, UTF-8/CRLF Hot,
  new turns, active Fast snapshots, delayed Luna, overflow, stale summaries,
  same-cutoff recovery, replay and restart. Existing rollback/cancellation/prefix
  checks remain in place.
- Verifier self-check rejects a fabricated boundary including Hot as Cold.
- Fresh independent review found a verifier prefix-rendering error; it was
  reproduced offline and fixed by comparing prefixes of complete valid prompts.
  Follow-up review found no remaining important issues.

## Live verification

The final complete run is `.data/m2-e95bb65308/`, with metrics in
`.data/m4-8-results.jsonl` and console output `.data/m4-8-live-final.log`.
Full private model requests, responses and actual Fast prompts are in
`handoff-traces.jsonl`; SQLite remains authoritative. No raw private evidence is
committed. The verifier phase is bounded to 600 seconds and 20 total turns; the
final run used 19 actual user turns, including the two short 16k cache turns.

Providers: existing local `nvidia-nemotron-3.5-bolt-e4b-4gb`, loaded as
`m4-8-bolt` with backend context capacity 16,384; Runtime enforced 4096 for handoff
and 16,384 for short-cache checks. Luna used `openai-codex/gpt-6-luna` through OMP.
Initiative was disabled. Pinned tokenizer SHA-256:
`CC8D3A0CE36466CCC1278BF987DF5F71DB1719B9CA6B4118264F45CB627BFE0F`.

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
$env:PYTHONIOENCODING='utf-8'
& 'C:/Users/shtvl/Documents/GitHub/liac-ai/.venv/Scripts/python.exe' scripts/verify_m2_luna.py --phase handoff --endpoint http://127.0.0.1:1230 --model m4-8-bolt --tokenizer .data/tokenizers/nemotron.json --omp-executable C:/Users/shtvl/AppData/Local/omp/omp.exe --output .data/m4-8-results.jsonl
```

### Normal 4096-token handoff

Luna requested Cold cutoff **23**, rendered as `through={history:12,new:0}`.
The retained Hot cost was **1146 tokens**. Its event texts were compared as UTF-8
bytes before/after the switch and matched. While real Luna inference/delivery was
held, Bolt completed a new ticket-code turn on Epoch 0 with 2867 input tokens;
the full request took about 164 ms. The hold is test instrumentation, not a claim
about natural provider latency.

The real Luna summary covered the archive bridge Marigold, stone jade, expedition
scene and entries **1–5**, matching Cold. It did not extend the entry range into
the newer visible entries. The summary was atomically applied in Epoch 1. Actual
next Fast trace inspection confirmed the summary, every captured Hot event ID and
the newly completed ticket fact in the same 1621-token prompt. Bolt correctly
recalled `VIOLET-27`.

### Overflow while Luna is held, then restart

A later real request was held separately. A new input exceeding the full input
allowance caused budget-only fallback to **Epoch 3, cutoff 47**; Bolt completed
without waiting, with a 2411-token fallback prompt. The late Luna result was
`superseded`, preserving monotonic history. Canonical recovery then reached
**Epoch 4, cutoff 61**, clearing pending recovery. Same-cutoff recovery is covered
separately by SQLite regression tests, including a process-reopen fixture.

Runtime and Journal were closed and reopened on the same database. Summary and
raw dialogue matched the persisted snapshot. Asked for the four facts, actual
Bolt output was: “Bridge is Marigold, stone is jade, ticket code is VIOLET-27, and
the compass is copper.” This is one controlled recall trial, not a broad memory
quality evaluation.

### 16k prefix/cache measurement

A fresh 16,384-token configuration used only two short real turns (four history
messages). Complete rendered prefixes were byte-identical when only Markdown
changed; no artificial history filling was used.

| Measurement | Prime | Markdown changed |
| --- | ---: | ---: |
| Input tokens, local = provider | 91 | 96 |
| Runtime prompt-evaluated tokens | 91 | 96 |
| Prompt evaluation time | 157.83 ms | 41.73 ms |
| TTFT | 164.64 ms | 47.32 ms |
| Explicit cached-token count | unavailable | unavailable |

Each log window attributed exactly one serial task. These short requests were
fully reevaluated; this trial proves prefix stability, **not a backend cache hit**.
Lower latency alone is not cache evidence. Existing prompt ordering was preserved.

## Corrected trial failures and limits

The initial setup sent inputs faster than Luna completed observation and reached
fallback before normal compaction (920 Hot tokens in a recovery request). It is
not counted as normal semantic acceptance. Setup now waits for the existing
cursor between preparatory turns. A subsequent trial proved normal handoff but
waited for a second compaction when no new Cold existed; setup now adds one real
completed turn if needed before the deliberate fallback case.

A completed earlier trial (`m2-47095b5020`) exposed Luna mentioning entries 1–10
despite a Cold 1–5 boundary, apparently drawing on Markdown/session context.
The Luna-only source instruction was tightened, then the full final run above
was repeated successfully on a fresh database. Summary compliance remains model
behavior; Runtime guarantees source boundaries, raw preservation and ordering,
not arbitrary semantic correctness of generated text.

The local model/server were initially unloaded/stopped. Only the model/server
started for these checks were stopped afterward; owned OMP and log processes were
closed. No push, PR, merge or deployment was performed.
