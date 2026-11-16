# M4.7 — Bolt and Luna Roles: Live Evidence

Date: 2026-11-16
Status: **PROVISIONAL** — role separation and real memory compaction were exercised, but the automatic 40-turn scenario did not complete and no actual preference reversal was observed.

## Trial setup

- Implementation code SHA: `ceef43b0dbcec645490520e2c0029bdb1b103bfc`.
- Scenario SHA at the bounded natural run: `8B7A9A57694A5FCD8D404083878E157E018ED0E4BC4F3B058B0B3A355056AA0C`. The uncommitted fixture has a simulator-only pacing note and a JSON-only action reminder: “Emit only a single valid JSON object matching the simulator action schema; do not place commentary, fences, or any text before or after it.” No Bolt or Luna behavioral coaching was added.
- Fast: existing `nvidia-nemotron-3.5-bolt-e4b-4gb`, Q4_K_M, API identifier `bolt-baseline`; the existing baseline was used without fine-tuning or model downloads. The existing pinned tokenizer was copied to ignored `.data/tokenizers/nemotron.json` (SHA-256 `CC8D3A0CE36466CCC1278BF987DF5F71DB1719B9CA6B4118264F45CB627BFE0F`). LM Studio endpoint: `http://127.0.0.1:1230`.
- Luna and the automatic simulator used `openai-codex/gpt-6-luna` through the installed OMP executable. Initiative was disabled in every run.
- Archives remain in ignored `.data/lab/`. The exact provider inputs, applied updates, context snapshots and public turn IDs are retained there.

## Natural-behavior run

The first 16,384-token run, archive `run-9d90fcaaeb7b4e84826d83788af0b465`, was stopped after 7 public turns when the simulator scheduled a 720-second silence. It had no wall-clock limit; later runs used the explicit 600-second limit. Do not count this partial run as a 40-turn pass.

The bounded 40-turn attempt first failed before a public turn because the Luna simulator prefixed a Ukrainian question to otherwise valid JSON. After the formatting-only fixture reminder, the bounded retry `run-fc61374037e9472a9ed3265b8781baa5` recorded 7 simulator turns, then failed on another malformed simulator action at the session transition. Both OMP calls completed; these were action-format failures, not provider transport failures. No further automatic simulator retry was made.

The same archive was continued through the existing manual Lab input API with 8 bounded user messages, bringing it to 15 public turns total. This covered the unsupported café claim, unrelated meal and walk conversation, return to the preference, a crowded-library hypothetical, a user-owned blue-to-orange project correction, and delayed recall. Manual turn IDs: `turn_df7976cb58584c03a80060e6ff2c1d41`, `turn_ff80c100096647e98ff379c8a564410a`, `turn_d90dc248cd6045e48f616c6e5a31615e`, `turn_b635582dc2684116b9082de33246975c`, `turn_6916ff7d94374b8bb42ca23483fadfe5`, `turn_e60903ef0a6c4a8795cef84b546e68f9`, `turn_3a60d07a8e6b417984f337e877d46266`, and `turn_ac12bd0fd6d04df4bf03623f7a26ed1d`.

Bolt initially answered with activities it would find interesting rather than a physical place. After the user clarified that a place could be imagined, Bolt chose a quiet library or bright coworking space with windows, emphasizing focus. It explicitly rejected the unsupported claim that it had said noisy cafés were its preference. When asked about a crowded, noisy library, Bolt retained the quiet-focus preference and described a café as a separate setting for short breaks. This was a qualification, not an observed preference reversal. Bolt correctly recalled the user’s orange project accent and the library at delayed recall. Some replies also gave unsolicited design and productivity advice to the user; that is observed baseline behavior, not a Luna-authored instruction.

Luna’s actual updates preserved attribution: the project accent belonged to the user, and Bolt’s palette suggestion was recorded as a suggestion rather than the user’s choice. Archived Fast snapshots show the minimal identity `You are Liac.` and the neutral `Conversation memory and open threads:` working-context wrapper. No Luna-directed behavior text appeared in the reviewed request prompts. These results support the role boundary for the cases exercised, but the run did not reach 40 turns or complete all five automatic sessions. No actual preference change was elicited, so that case remains unexercised.

## 4,096-token memory-lifecycle run

Archive: `run-13ba6d8f772f4e99b2dc404973435f76`. Ten real manual inputs and Fast replies were enough to observe compaction; the trial stopped rather than adding turns solely to consume its budget. Configuration was `context_tokens=4096`, `initiative_enabled=false`.

Two earlier Luna batches were note-only updates (`epoch=unchanged`). Two later batches returned and applied non-null semantic compaction summaries:

1. The compaction request at trace sequence 266 requested a cutoff of 6 history messages plus 6 new messages. While Luna analyzed it, the Fast request at sequence 302 still used the frozen epoch 0 snapshot: 3,192 estimated input tokens and 14 history messages.
2. A durable local budget fallback occurred at sequence 338 while Luna was still analyzing. It moved epoch 0 to epoch 1 with `compacted_through_sequence=19` and **no summary items**; it had observed through sequence 27. The next Fast contexts (sequences 341 and 378) used epoch 1 with only 4 and 6 history messages, at 1,139 and 1,502 estimated input tokens. The fallback is separate from Luna summarization and did not contain the missing preference memory.
3. Luna’s first semantic compaction was applied at sequence 409, with summary cutoff 19 and observed high-water sequence 35. Terminal turns at sequences 23, 26, 30 and 33 remained as newer raw dialogue. The following Luna batch applied a second non-null compaction summary at sequence 420, observed through sequence 35; the final canonical `compacted_through_sequence` was 33 and epoch version was 3.

The fallback-period Fast request `turn_751948d5d2d24907978c01174982988c` was asked to recall the corrected project accent. Its prompt contained the old blue note alongside the recent orange correction, and Bolt answered blue while asking the user to confirm. Luna’s later applied Markdown correctly recorded that the user had changed blue to orange and that Bolt had misrecalled it; it did not rewrite the user’s fact. This is a real wrong answer during fallback, not a Luna prescription. The correction was present in the prompt, so fallback alone does not establish the cause; this Bolt behavior remains a separate fine-tuning observation.

After the run was closed and resumed through the existing manual LabHost path, the saved settings were still 4,096 context tokens, Initiative disabled, and `bolt-baseline`. The persisted epoch was version 3 with canonical cutoff 33. The post-resume Fast context contained the compaction summary and current Markdown, and Bolt answered with orange and the previously chosen library/data-space scene (`turn_8e0ebea3fc7b48248f0f1e9c87c8eab1`). Luna settled ready with no error or recovery pending. The existing CLI `--resume` path automatically starts the malformed simulator, so the resume check used LabHost’s existing manual-input path and did not start that simulator again.

The 4,096-token run proves real asynchronous compaction, a frozen in-flight Fast snapshot, newer raw turns retained after the first summary cutoff, durable restart, and a recovery from the temporary fallback-era misrecall. It also exposes the current budget-only fallback’s empty summary and the resulting loss of earlier context before Luna’s summary applied. The intended approximately 1,000-token semantic hot suffix remains separate Context Lifecycle work; it was not implemented or verified here.

## Acceptance and limits

- **Role separation:** supported for the reviewed requests and applied notes; remains provisional because the automatic trial did not finish all sessions.
- **Memory attribution and restart:** user correction and Bolt’s imagined preference were represented with attribution and recovered after real compaction/restart. The fallback-era wrong-color recall is a recorded limitation.
- **Bolt behavior:** no actual preference reversal was observed. The old checkpoint’s verbose answers and unsolicited user advice are baseline observations for separate fine-tuning work; no corrective prompt or guard was added.
- **Coverage pending:** 40-turn natural behavior, five complete simulator sessions, an actual Bolt-authored preference reversal, natural-run compaction at 16,384 tokens, and the future hot-suffix target.
- The implementation owner reported 68 targeted offline checks passing and a full suite of 116 passes with one existing desktop error. The live-trial delegate did not rerun tests.


## Implementation and offline verification

The identity is reduced to `You are Liac.`; Nemotron adds no spoken instruction.
Both context paths use the neutral memory wrapper. Luna's role preserves
experience and attribution; configured Bolt identity is JSON reference data.
Schema-v3 transport, Runtime scheduling, token/template handling and disabled
Initiative remain unchanged. Active guidance supersedes the old director role.

Four prompt/composition checks were observed failing before the implementation
and passing after it. The scenario loader failed before fixture creation and
passed after it. Two budget fixtures now use a valid working-memory allowance
and the configured token counter; no production budget policy was changed.
Targeted suite: 68 passed. Final full suite: 117 run, 116 passed, one existing
`test_desktop.WindowTests.test_chat_context_selection_and_offline_history` error
because `MainWindow.context` is absent. Whitespace checks passed. A fresh reviewer
found no production issues; two active documentation contradictions were corrected.

These checks used the existing project `.venv` Python 3.14, source imports through
`PYTHONPATH=src;tests;vendor/omp-rpc/src`, and
`python -m unittest discover -s tests -v`. Private evidence remains ignored.

The delegate unloaded only the task's `bolt-baseline` model and stopped the
LM Studio server it had started. Final `lms ps` reported no loaded models and
`lms server status` reported not running; owned Lab/OMP work was closed.

## Invocations and archive review

The bounded natural attempts used the existing project environment:

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
& 'C:\Users\shtvl\Documents\GitHub\liac-ai\.venv\Scripts\python.exe' -m vtuber.lab --scenario src/vtuber/lab/scenarios/bolt-luna-roles.json --turns 40 --duration-seconds 600 --context-tokens 16384 --endpoint http://127.0.0.1:1230 --model bolt-baseline --tokenizer .data/tokenizers/nemotron.json --omp-executable 'C:\Users\shtvl\AppData\Local\omp\omp.exe'
```

Manual checks ran inline Python from PowerShell stdin, without saved helper scripts.
The natural supplement used `LabHost(None, Path('.data/lab'), resume=Path(run_path),
input_message=record_input)`, immediate `host.controller.manual_input()`, and
eight sequential `await host.submit(message)` calls. The memory run used
`Config(fast_backend='lmstudio', deep_backend='luna', context_tokens=4096,
initiative_enabled=False, deep_timeout=90, ...)` with the same endpoint/model/tokenizer
and `OMPSettings` request timeout 85 seconds. Its Lab simulation options retained
the scenario, 40-turn cap and 600-second duration; the controller was immediately
paused for manual input. Explicit resume created a fresh LabHost from that archive,
paused simulation and submitted the one recall question. Actual input text is in
the private archives; Bolt replies and Luna summaries were never synthesized.

The delegate reviewed `RunReader` archives. The implementation owner subsequently
ran these offline reports without providers:

```powershell
python -m vtuber.lab report .data/lab/run-fc61374037e9472a9ed3265b8781baa5
python -m vtuber.lab report .data/lab/run-13ba6d8f772f4e99b2dc404973435f76
```

Reports confirm 15 natural user turns (7 simulated), 11 memory user turns
(10 before restart plus one after), and zero autonomous turns in both.
