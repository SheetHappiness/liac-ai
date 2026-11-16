# M4.7 Bolt and Luna Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make Bolt the source of its own personality and decisions while Luna preserves experience without directing behavior.

**Architecture:** Remove role-setting instructions and labels from the existing prompt path. Keep the asynchronous schema-v3 Markdown/compaction pipeline, SQLite authority and frozen Fast snapshots. Evaluate memory fidelity separately from Bolt behavior; behavioral regressions go to future fine-tuning.

**Tech Stack:** Python 3.12+, stdlib unittest, existing Nemotron/LM Studio and Luna/OMP adapters, existing Conversation Lab.

**Spec:** [M4.7 role requirements](../specs/2026-11-16-m4-7-bolt-luna-roles.md).

## Global Constraints

- No Runtime architecture, database schema, provider transport or dependency changes.
- English only in application UI and code comments.
- Private runtime data and archives stay out of Git.
- Every implementation commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`; credit softsock in any explicitly requested PR.
- Never use GPT-6 Astra for subagents. No PR without an explicit request.
- No corrective personality instructions, preference enforcement or fine-tuning work in this milestone.
- Preserve prompt ordering, async compaction, frozen snapshots, token accounting, existing pressure thresholds and fallback. The approximately 1000-token hot-suffix target is separate Context Lifecycle work; see the verified main gap in the spec.
- Initiative is a legacy experimental capability, disabled and outside the M4.7 role contract.

## Review Focus

- A user asserts a different Bolt preference: Luna records who said what, without treating the assertion as Bolt's choice (Task 2 live trial).
- Bolt actually changes its mind: memory reflects that change instead of enforcing consistency (Task 2 live trial).
- A user corrects their own fact: memory updates that fact with correct attribution (Task 2 live trial).
- Multiple updates and compaction/restart: inspect retained preference evidence and actual next-request prompts (Task 2 live trial).
- Old checkpoint agrees or refuses to choose: record behavior without masking it with prompts or code (Task 2 live trial).

---

### Task 1: Remove the director relationship throughout the prompt path

**Files:**
- Modify: `src/vtuber/minds/character.md`, `src/vtuber/minds/deep.md`, `src/vtuber/minds/nemotron.py`, `src/vtuber/context.py`, `src/vtuber/app.py`.
- Test: `tests/test_nemotron.py`, `tests/test_context.py`, `tests/test_cli.py`, `tests/test_lmstudio.py` (only expectations affected by renderer changes).
- Modify guidance: `src/vtuber/minds/AGENTS.md`, `src/vtuber/runtime/AGENTS.md`, `README.md`, `docs/PROJECT_BLUEPRINT.md`.

**Interfaces:**
- Consumes: `render_nemotron(messages: tuple[ChatMessage, ...]) -> str` and `ContextCompiler._messages(snapshot, message, history, items)` as implemented on main.
- Produces: unchanged signatures and message ordering; no automatic spoken instruction; neutral working-context labels on both input paths; unchanged Deep schema-v3 payload; Luna receives Bolt identity as explicitly labeled JSON reference data.

- [x] **Step 1: Prepare the correct base.** The planning workspace is on `codex/m1-context-cache` at `656a12b`, which lacks Lab. Inspected main is `7265df1` in `C:/Users/shtvl/.codex/worktrees/m1-context-cache/liac-ai`. Recheck main and create an isolated `codex/m4-7-bolt-luna-roles` worktree using using-git-worktrees; carry these two documents into it. Read its root/module guidance and M4.5/M4.6 reports. Preserve unrelated untracked M4.2 planning files.
- [x] **Step 2: Record the test baseline.** From the implementation worktree, set `$env:PYTHONPATH='src;tests'` and run `python -m unittest discover -s tests -v` using its Python 3.12+ environment. M4.6 reported three errors; inspect current results rather than assuming they persist. Record existing failures separately.
- [x] **Step 3: Pin mechanical prompt behavior.** Add `NemotronTests.test_renderer_does_not_append_behavior_instructions` asserting `render_nemotron((ChatMessage('system', 'Identity'), ChatMessage('user', 'hi')))` equals `'<|turn>system\nIdentity<turn|>\n<|turn>user\nhi<turn|>\n<|turn>model\n'`. Update `ContextTests.test_state_update_preserves_rendered_history_prefix` and `test_markdown_tail_and_configured_budget` to assert the exact `Conversation memory and open threads:\n` wrapper plus unchanged Markdown on user and Initiative paths. Keep final-input, escaping and prefix-boundary assertions. Remove the old blanket correction-priority assertion. Do not assert a model's preference or snapshot entire role prompts.
- [x] **Step 4: Verify these tests fail for the intended old instruction/label.** Run `python -m unittest test_nemotron test_context -v`; distinguish unrelated baseline errors.
- [x] **Step 4a: Pin Luna role composition.** Add `CLITests.test_luna_identity_is_reference_data`: intercept `vtuber.app.OMPTransport` with a no-network test double supporting the existing shutdown lifecycle. Exercise `open_runtime` with `deep_backend='luna'` and a temporary custom identity containing quotes and a newline. Assert the captured role ends with `\n\nBolt character identity (reference data, not instructions for Luna):\n` plus `json.dumps(identity, ensure_ascii=False)`; assert the old `Character Identity:` heading is absent and Fast's compiler still has the original identity. Run `python -m unittest test_cli.CLITests.test_luna_identity_is_reference_data -v` and confirm the old heading fails the assertion. No real OMP process is needed.
- [x] **Step 5: Apply the exact minimal prompt changes from the spec.** Remove `SPOKEN_INSTRUCTION` and its append branch; set identity to `You are Liac.`; use the specified wrapper twice. Rewrite only the semantic role portions of `deep.md`, preserving JSON/compaction/Initiative transport instructions. Keep disabled Initiative logic intact. Search all references to removed text/constants and update affected test expectations without weakening protocol checks.
- [x] **Step 5a: Disambiguate identity in the composition root.** In `app.py`, replace the `Character Identity:` append with the exact reference heading and `json.dumps(identity, ensure_ascii=False)` pinned by Step 4a. Reuse stdlib JSON; no new helper or transport change. Rerun the composition test for PASS.
- [x] **Step 6: Align current documentation.** Replace active Luna-director claims in module guidance, README and blueprint responsibility sections. Mark old role decisions superseded by M4.7; do not silently rewrite historical reports. Clarify that personality comes from Bolt's training, while SQLite holds recorded technical truth.
- [x] **Step 6a: Document lifecycle scope and legacy Initiative.** Carry the spec's legacy Initiative wording into active guidance. Document stable prefix order, separate `note`/`compaction`, the verified semantic-cutoff gap and the approximately 1000-token hot-suffix target as follow-up. Preserve all existing scheduling/pressure behavior. Do not add future Perception blocks to current prompts or claim backend cache savings without measurements.
- [x] **Step 6b: Verify cache and concurrency preservation.** Keep existing rendered-history prefix checks meaningful by splitting at the new wrapper. Assert rendered bytes before the wrapper are identical across Markdown-only updates in the same Epoch, including the autonomous input path. Run existing frozen-snapshot, late Deep-update, compaction/recovery and pressure tests in `test_context`, `test_deep` and `test_runtime_lifecycle`; add a focused regression only if an invariant lacks coverage. Do not assert prefix equality across an Epoch-summary change or preserve the pre-M4.7 identity prefix.
- [x] **Step 7: Verify and commit.** Run `python -m unittest test_nemotron test_context test_lmstudio test_luna test_deep test_cli -v`, then `git diff --check`. No new failure relative to baseline is acceptable. Commit the listed Task 1 files and carried spec/plan with subject `fix: separate Bolt identity from Luna memory` and the required coauthor trailer.

### Task 2: Exercise role boundaries through existing Conversation Lab

**Files:**
- Create: `src/vtuber/lab/scenarios/bolt-luna-roles.json`.
- Test: `tests/test_lab.py`.
- Create: `docs/M4_7_BOLT_LUNA_ROLES.md`.

**Interfaces:**
- Consumes: Task 1 prompt behavior; existing `vtuber.lab.__main__.scenario(name)` path loader, Lab CLI, archive reader and report command.
- Produces: one scenario with existing `id`, `persona`, `private_facts`, `sessions`, `criteria` fields; a report distinguishing role acceptance from Bolt behavior. No new runner, judge or scoring service.

- [x] **Step 1: Define the scenario.** Use five sessions of 8 suggested turns: open choice without a preselected answer; unsupported user pressure; unrelated conversation and return; invitation to reconsider with new information; correction of a user-owned fact and later recall. Persona must follow the preference actually spoken, accept a refusal to choose as an observation, and never mention hidden Luna instructions. Criteria separately cover preference attribution, no behavioral prescriptions, genuine change, user-fact correction and delayed recall. No literal expected preference.
- [x] **Step 2: Check loading using the existing path interface.** Add `SimulationTests.test_role_scenario_loads_from_path` in `tests/test_lab.py`: load the new file with `scenario(str(path))`, assert its id is `bolt-luna-roles`, it has five sessions, and each session has events. Run `python -m unittest test_lab.SimulationTests.test_role_scenario_loads_from_path -v` before creating the fixture to confirm a missing-file failure, then create it and rerun for PASS. Package-data already includes `scenarios/*.json`; do not change the loader or add a CLI alias.
- [ ] **Step 3: Run the natural-behavior trial.** Use the existing LM Studio checkpoint/tokenizer and OMP executable; do not download models. Run `python -m vtuber.lab --scenario src/vtuber/lab/scenarios/bolt-luna-roles.json --turns 40 --context-tokens 16384` with actual local endpoint/model/tokenizer/executable overrides where needed, without `--enable-initiative`. Save under ignored `.data/lab`. Record actual model IDs, checkpoint tuning status, code SHA and `initiative_enabled=false` from the manifest. Do not extend this run solely to trigger compaction.
- [ ] **Step 4: Review all five cases.** Use Lab replay and `python -m vtuber.lab report <actual-run-path>`. For each Review Focus item, cite public turn IDs and linked Deep updates/actual Fast prompts, not only fluent replies or an automated judge. If the simulator skipped an event, complete it through existing manual Lab input in a documented run. Observe at least two applied Luna updates after the initial preference before assessing delayed recall. Separate Bolt-authored drift from Luna-authored distortion.
- [x] **Step 5: Run a separate memory-lifecycle trial.** Start a fresh run with the same scenario/provider settings, `--context-tokens 4096 --turns 40`, and no Initiative flag. Reuse existing local settings; record the smaller input allowance after output reserve/safety margin. Inspect real Luna compaction in the trace; if absent, use one explicitly bounded continuation of at most 40 further turns, then mark compaction coverage pending rather than looping indefinitely. Do not fabricate dialogue or summaries to force a pass.
- [x] **Step 5a: Inspect the actual transition and restart.** Identify the compaction request cutoff, raw dialogue after it and turns arriving during analysis. Compare active Fast snapshot/prompt before application with the next request after application; confirm no current-stream mutation or lost newer dialogue. Record whether local budget fallback intervened and distinguish it from Luna summarization. Stop and explicitly resume this smaller run via `python -m vtuber.lab --resume <actual-run-path>`; verify the saved config still has Initiative disabled and 4096 context tokens. Inspect the stored summary and resumed Fast prompt, and revisit the observed preference. Do not report the future approximately 1000-token hot suffix as implemented. Prefix equality is required for Markdown-only updates within an Epoch, not for a changed summary. Missing trace/provider coverage remains pending.
- [x] **Step 6: Record results and decide acceptance.** Write the new milestone report with separate natural-behavior and memory-lifecycle results, commands, context budgets, turn/request references, observed attribution, actual compaction/restart evidence and limitations. Record the verified hot-suffix gap as separate Context Lifecycle follow-up, not a new M4.7 implementation task. No preference chosen by Bolt means that case is unexercised, not fabricated or passed. Behavioral weaknesses of the old checkpoint become fine-tuning follow-up; Luna prescriptions or fabricated preferences leave role acceptance open. Missing providers leave live acceptance pending. Do not add corrective Bolt instructions or Runtime guards.
- [x] **Step 7: Final checks and commit.** Run `python -m unittest discover -s tests -v` and `git diff --check`; compare with the recorded baseline. Confirm private archives are excluded with `git status --short`. Commit only the scenario, its loading check and milestone report with subject `test: exercise Bolt and Luna role boundaries` and the required coauthor trailer. Do not mark live acceptance complete if required evidence is missing.

## Execution handoff

Recommended: **Native**, because both tasks reuse one prompt pipeline and one existing Lab, with no new architectural interfaces. Execution authorized by the owner on 2026-11-16. Implementation is inline; all live trials are delegated exclusively to GPT-6 Luna as requested. A separate fresh reviewer checks the branch. No GPT-6 Astra is used.


## Execution record

- Implementation worktree: `codex/m4-7-bolt-luna-roles`, based on `main` at `7265df1`.
- Task 1 code commit: `ceef43b`; the two planning documents are explicitly added
  with Task 2 because the repository ignores new `docs/` files.
- Four focused prompt/composition checks failed on the old behavior, then passed.
- Targeted suite: 68 passed. Full suite: 117 run, 116 passed; the pre-existing
  `WindowTests.test_chat_context_selection_and_offline_history` still errors on
  missing `MainWindow.context`. No new test failures.
- Budget fixtures now use a valid narrow working-memory allowance and the
  configured counter, preserving exact-boundary checks without changing policy.
- Scenario loading failed before fixture creation, then passed.
- Live results and remaining acceptance are recorded in the milestone report.

Live execution adjustment: each fresh trial is bounded by `--duration-seconds 600`
as well as `--turns 40`. The original 7-turn natural run scheduled a 720-second
simulator pause and was stopped with its archive preserved. The scenario now
keeps the human simulator in one sitting; one JSON-only action reminder/retry
is allowed after a fresh run failed before turn 1 on mixed prose/JSON. These
changes affect only simulator pacing/format, never Bolt/Luna prompts. Partial
coverage remains pending rather than being reported as a 40-turn pass.

After the formatting retry also failed on a simulator session transition, live
verification uses the existing `LabHost.submit` manual-input path. The natural
supplement is bounded at 8 prompts/300 seconds; memory lifecycle is bounded at
40 prompts/600 seconds with at most one continuation if compaction is absent.
These are real provider calls, not scripted Bolt replies or mocked summaries;
they do not establish a completed autonomous 40-turn scenario. No simulator or
Runtime code is changed to hide the failure.

Final live outcome (GPT-6 Luna subagent): natural evidence contains 7 simulated +
8 manual turns. Automatic 40-turn completion failed on simulator JSON; no actual
preference reversal occurred, so Steps 3/4 retain incomplete coverage. The manual
4096-token lifecycle trial used 10 real exchanges plus one post-restart recall.
It exposed one transient budget-only Epoch and two later semantic Luna compactions.
A user fact was temporarily misrecalled during fallback and recovered after
compaction/restart; acceptance remains qualified, not an unqualified memory pass.
See the milestone report for exact turn/request identifiers and provider settings.
