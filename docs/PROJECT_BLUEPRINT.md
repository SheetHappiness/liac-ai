# PROJECT BLUEPRINT – Liac Single Mind

> **Status:** M6.0 is an implemented experimental Single Mind baseline on `codex/m6-0-single-mind`; M6.1 is being **redesigned**, not accepted. The `main` branch still contains the documented M0–M5.0 legacy baseline. Do not confuse an experimental branch or offline checks with a released/live-validated milestone.
> **Updated:** 2026-11-18. **Version:** 0.3.
> **Active repository:** [`SheetHappiness/liac-ai`](https://github.com/SheetHappiness/liac-ai). **Legacy backup:** [`softsock/liac-ai`](https://github.com/softsock/liac-ai).
> **Rewrite base:** `codex/m6-0-single-mind` (create a new isolated development branch). **Primary reference:** [ProjectBEA](https://github.com/emqnuele/projectBEA). **Secondary reference:** [LilavelStage](https://github.com/SheetHappiness/LilavelStage).

This is the **target architecture and staged migration plan**, not a claim that all components below have been implemented. Legacy Bolt/Fast + Luna/Deep decisions remain documented in milestone reports but are superseded as the target for M6. The previous `codex/m6-1-attention-live-state` and M6.1.5 Electron Hub are **rejected as implementation foundations**: do not cherry-pick their Perception scheduling, Wake/LiveState or UI pipelines into the rewrite.

**Status vocabulary:** `IMPLEMENTED` – present with stated evidence; `DECIDED` – approved target, not necessarily coded; `EXPERIMENT` – under evaluation; `FUTURE` – not part of the immediate task. Agents must read the relevant `AGENTS.md`, compare the actual upstream implementations and record source revisions before adapting them.

## 1. Purpose and character

**DECIDED:** Liac is a persistent, entertaining, character-first virtual person. The objective is believable continuity, contextual reactions, appropriate silence and eventual control of a limited set of permitted tools – not a general-purpose assistant.

- **One speaking mind.** GPT-6 Luna is Liac, owns character, speech, reactions, preferences and decisions. Bolt is not retained as a speech renderer or downstream personality model.
- **One shared cognitive context.** No hidden Luna director sending behavioral commands to another LLM.
- **Specialized VLM/STT/TTS are allowed.** They are senses and expression, not competing character minds.
- **Memory is experience, not a screenplay.** No `compose_beat` scheduler, forced jokes, artificial emotional directions or mandatory initiative engine.
- **Backend first.** Loonyball/avatar, Twitch, Discord, screen capture, speech and game integrations should be adapters, not dependencies of the cognitive core.

Quality must be demonstrated in live multi-turn behavior and real latency measurements. Attractive architecture alone is not acceptance.

## 2. Decisions

| ID | Decision | Status |
| --- | --- | --- |
| M6-01 | One GPT-6 Luna speaking/acting mind, retain M6.0 `SingleMindPort`, Bun/pi-ai bridge, `speak`/`stay_silent`, streaming output and Journal | **DECIDED** (M6.0 baseline implemented on branch) |
| M6-02 | Rewrite M6.1 **from `codex/m6-0-single-mind`**, never from M6.1/M6.1.5 | **DECIDED** |
| M6-03 | Adapt ProjectBEA PerceptionBus: one intake, last-arrival quiet-gap settle, text/live windows, ceiling, backlog handling | **DECIDED** |
| M6-04 | Adapt ProjectBEA single `Consciousness.run` ownership: one batch → one frame → one serialized turn | **DECIDED** |
| M6-05 | Input arriving while Luna is active **queues**, not unconditionally cancels/supersedes; controlled voice restart/steering requires separate proof | **DECIDED** |
| M6-06 | Distinguish BEA `Attention.annotate` (ranking, no cutoff) from LilavelStage `AdmissionPolicy` (whether inference is permitted) | **DECIDED** |
| M6-07 | Preserve one canonical SQLite Journal. Keep history, tools and derived memory projections separate from debug traces | **DECIDED** |
| M6-08 | Adapt BEA/LilavelStage action lifecycle and scoped `TurnAuthority` when real external tools exist | **DECIDED**, staged |
| M6-09 | Later adapt person/roster memory, Agenda, Open Threads, spontaneous presence/rhythm and bounded context handoff | **DECIDED**, staged |
| M6-10 | **Never port LilavelStage Shadow Memory**, shadow proposer/verifier, background reflection, shadow retrieval or its semantic index | **DECIDED** |
| M6-11 | Build structured trace using LilavelStage TraceBus and BEA EventManager/TurnLog; expose live timeline/replay/compiled context in **Electron**, not terminal TUI | **DECIDED**, later |
| M6-12 | Electron typed input is a simulator for finalized STT input, routed into the *same* PerceptionBus; never a parallel chat mind | **DECIDED**, later |
| M6-13 | Defer silent observation/LiveState, VLM, game telemetry and real STT until their adapters exist; do not invent sensor traffic now | **DECIDED** |
| M6-14 | Prove BEA-equivalent behavior with deterministic tests and a real Luna smoke run *before* modifying or optimizing upstream semantics | **DECIDED** |

### 2.1 Adaptation policy and engineering limits [DECIDED]

**Reference first, adapt second, improve third.** First write a mapping of ProjectBEA → Liac and enumerate deliberate differences. LilavelStage is a secondary reference for its separately implemented Admission, tools/authority and trace; it is not the new base and is not assumed to match upstream BEA.

Retain M6.0's smallest stable model/Journaling contracts, but do not use a blanket minimalism rule to strip out important BEA behavior. A central event loop, correct batching, steering seams, and observational traces are core product functionality.

Essential invariants: no lost/doubled input, correct ingress order and scope, bounded queues, idempotent canonical writes, no unauthorized tool effects, one owner of turns, no unsafe output on restart/shutdown. Prefer end-to-end tests for these properties over speculative abstractions.

Do not mix a full Electron rebuild, VLM, voice, unrelated memory experiments or latency tuning into the **first** Perception Loop PR. Each later module needs independent acceptance evidence. Any significant adapted upstream source must retain the appropriate MIT copyright and license notices.

## 3. Target architecture

```text
Electron typed (STT-final simulator), later STT / Discord / VLM / game adapters
                                |
                         PerceptionBus
          one intake → queue → settle(quiet gap) → bounded batch
                                |
                     Single Consciousness Loop
                 canonical intake → Attention → Admission
                               / \
                 no admission    admitted
                      |             |
                 trace only      frozen frame
                                    |
                         GPT-6 Luna Single Mind
                                    |
                         tool decisions / results
                                    |
                     validated actions + Journal
                                    |
                         output / future TTS
```

**One batch, one frame, one turn**, matching ProjectBEA's normal single-loop path. BEA `Attention` sorts relevance; LilavelStage-style `Admission` determines whether to make a model request. These are distinct from Luna's `stay_silent()`, which is an *inference result*, not an inference-skipping policy.

A separate **TraceBus** observes input, batch, attention, admission, model, tool and terminal transitions. It is not a second cognition path and must not change turn ordering. The later Electron Hub is a consumer of trace events *and* a trusted test adapter that publishes typed inputs to the same PerceptionBus.

Future ambient/silent LiveState can be added beside canonical intake when a real VLM/game/system adapter supplies observations. It is **not** a deliverable of the first rewrite.

## 4. Existing foundations and migration boundary

**IMPLEMENTED on `main` (M0–M5.0):** frozen Perception/Batch contracts, bounded same-key Perception Bus, transactional SQLite Journal, canonical input IDs and replay, M4.8 legacy context guarantees. See [M5.0 report](M5_0_PERCEPTION_BUS.md).

**IMPLEMENTED on `codex/m6-0-single-mind` (experimental baseline):** Luna through a Bun/pi-ai streaming bridge, `SingleMindPort` and `MindDecision`, `speak`/`stay_silent`, fake model, `RuntimeOutput`, a single-mind runtime, and SQLite Journal. Confirmed limitation in that branch: `SingleMindRuntime.submit_perceptions()` calls `_cancel_active('superseded')` on new direct input; the CLI drain loop does not wait for the prior turn. The rewrite MUST fix this rather than call M6.0's scheduling correct.

**REJECTED as foundation:** `codex/m6-1-attention-live-state` and its M6.1.5 Electron Hub. These prototypes may serve as observed failure cases only, not sources of code to transplant.

**Primary upstream:** [ProjectBEA](https://github.com/emqnuele/projectBEA), especially perception types/bus, `Consciousness.run`/`_run_turn`/`_turn`/`_steering`, attention rules/gate, tool lifecycle, memory and social rhythm.

**Secondary upstream:** [LilavelStage](https://github.com/SheetHappiness/LilavelStage), especially `attention/AdmissionPolicy`, scoped `TurnAuthority`, canonical effect rules, `trace.py`, `web_dashboard_assets/`, person/agenda/open threads. Its `bus.py` uses a fixed first-arrival window, **not** BEA's sliding quiet gap; do not import that behavior by mistake.

Before implementing, record exact reference revisions and a **source → target → deviation** mapping. Use new focused branches/PRs based on M6.0; leave legacy and old experiments intact.

## 5. Perception, batching and admission

### 5.1 ProjectBEA-compatible intake [FIRST M6.1 SLICE]

Adapt [BEA `perception/bus.py`](https://github.com/emqnuele/projectBEA/blob/main/src/core/perception/bus.py) and `types.py` as closely as practical:

- Every real input adapter publishes one individually identified Perception; adapters never spawn their own LLM turn.
- `drain()`/`settle()` close batches after a **quiet gap since the last arrival**, not a fixed duration after the first arrival. Each fresh message extends the deadline until a hard `max_window`.
- Text and live inputs have independently configurable gaps; mixed batches follow BEA's shorter applicable gap. Use monotonic ingress times; queued items must not be made to wait another full gap merely because Luna was busy.
- Preserve original IDs, source/author, timestamp, conversation scope and ingestion order. Never treat an unauthenticated source string as permission to cross private channels.
- Support bounded overload and explicit rejection/backpressure; preserve accepted messages under cancellation, shutdown and late backlog. Duplicate input must not create another canonical turn.
- Keep `drain_nowait()` and a future `steer()` seam, matching BEA's ability to observe mid-turn arrivals. The first accepted slice **queues** such inputs instead of cancelling the current reply.

Experimental starting points: `live_gap=0.30 s`, `text_gap=1.20 s`, `max_window=3.0 s`, `max_pending=256`. These are Liac test settings, not claims about upstream BEA defaults or measured latency. Send in Electron is a **finalized utterance**, not an instruction to close the entire quiet-gap batch immediately.

### 5.2 Attention [AFTER FIRST LOOP]

BEA [`attention/gate.py`](https://github.com/emqnuele/projectBEA/blob/main/src/core/attention/gate.py) **prioritizes** all meaningful perceptions; it does not perform an arbitrary threshold drop. Adapt its deterministic scoring, addressed-input, follow-up, activity and cooldown logic after the first loop works, initially with only actual supported local text input.

### 5.3 Admission [AFTER ATTENTION]

LilavelStage's separate `AdmissionPolicy` decides whether inference is allowed, with explicit decisions/reasons, conversation-scoped neighbors and safe defaults. A direct finalized local utterance is admitted in the first text-only slice. Do not silently discard user direct input or combine private conversation scopes. Preserve rejected input according to explicit data-retention rules; never conflate "not admitted to LLM" with "never received". Do not add Discord mention/fuzzy-name rules until a real multi-party adapter exists.

### 5.4 Future ambient/silent context [DEFERRED]

The future requirement remains: a real VLM/game/system observation may update bounded live context **without a Luna call**; unusual events may later trigger Admission. `stay_silent()` is different – it requires running Luna. Do **not** implement speculative `LiveState`, fake scene feeds, generic wake heuristics, or periodic cloud inference during the rewrite without a real producer. Preserve only a clean extension boundary.

## 6. Single Consciousness Loop and tools

**Replace M6.0's supersession-by-default scheduling with an adapted ProjectBEA loop.** Read `Consciousness.run()`, `_run_turn()`, `_turn()` and `_steering()` before implementing. Do not copy the entire ProjectBEA application or introduce a second model.

1. The one loop awaits a settled batch from the shared Bus. Accepted perceptions are committed with original provenance to the canonical Journal before an Admission decision.
2. Attention ranks; Admission either permits a cognitive turn or records why it did not. In the first slice all valid local direct text is admitted; no real ambient source exists yet.
3. Freeze a single coherent context frame from identity, canonical completed history and this batch. Call Luna using the M6.0 bridge/`SingleMindPort`.
4. Only explicit tool calls authorize effects. `speak(message)` or `stay_silent()` end the basic text turn. The model's free-form text is private, not public output. Stream provisional speech fragments via existing `RuntimeOutput` and commit only complete validated decisions.
5. Await the current turn before consuming the next settled batch. New inputs arriving during inference remain queued; they are **not lost and do not cancel** the active ordinary text turn.
6. On failure, interruption, shutdown or restart, settle or explicitly account for accepted inputs without fabricated success or duplicate speech.

### 6.1 Steering and voice restart [SECONDARY SLICE]

BEA `steer()`/mid-turn perceptions are part of the target adaptation. Study and implement them **after** the serialized normal loop passes acceptance. Text arriving during a single terminal `speak` is queued for a later turn; do not restart every request. A BEA-style restart is permitted only before outward speech/actions and only if all earlier perceptions are restored into the new frame. Multi-step tool results may justify another Luna step under a clear bound.

### 6.2 Tools and authority [LATER SLICE]

Retain the M6.0 `MindDecision`, `speak`/`stay_silent` and streaming contract. Adapt BEA's tool registry/lifecycle and LilavelStage `TurnAuthority` **when the first external effect is enabled**. Runtime alone validates exact destination, actor scope, arguments, execution result and acknowledgement. Confirmed outward effects become canonical history; private model prose, failed or unknown effects are not represented as delivered speech.

### 6.3 Tool-aware replay

Replay prior completed `speak` as `assistant → tool call → tool outcome` when the chosen Luna transport supports it. Derive stable IDs from committed events. A cancelled/provisional fragment must never be recorded as successfully delivered. This is a Journal-derived context projection, not a second canonical log.

## 7. Context, memory and experience

**One mind and one canonical event history.** Journal stores accepted input and confirmed actions. The model sees a bounded *projection* of history, not automatically every Journal row.

**Context assembly order:**

1. Stable character identity and concise tool instructions.
2. Complete replay of confirmed dialogue and tool outcomes.
3. Bounded optional context (person/roster, unresolved threads, due intentions and later real live state).
4. Ordered perceptions for the current batch, with source/provenance.

Adapt BEA's `SingleContext`/token-budget/handoff **behavior** and preserve M4.8's frozen frame, whole-turn Hot/Cold separation and recovery guarantees. Do not copy an unrelated SQLite or vector database wholesale. Any persisted domain records must have explicit ownership and must not compete with the Journal as the authoritative record of what actually occurred.

### 7.1 Person and social memory [FUTURE, REQUIRED SCOPE]

Adapt BEA roster/person-card mechanisms for stable identities, exact participant scopes and bounded prompt retrieval. LilavelStage's Person Memory is a secondary comparison. Introduce it only alongside real multi-user input or a proven need; keep separate records for user facts, character statements and uncertain observations.

### 7.2 Agenda and Open Threads [FUTURE, REQUIRED SCOPE]

Adapt BEA `social/agenda.py` and rhythm queueing, plus LilavelStage's explicit Open Threads lifecycle (`OPEN`, `RESOLVED`, `CANCELLED`). Due intentions enter the **same PerceptionBus** with trusted runtime provenance; they do not bypass the loop, grant arbitrary external authority or create another mind. Use bounded stores/queries, not automatic all-history injection.

### 7.3 Spontaneous presence [FUTURE, REQUIRED SCOPE]

Adapt BEA `mind/spontaneous.py` and `social/rhythm.py`, comparing LilavelStage's opt-in A0. Initiation requires explicit enabled policy, cooldown, activity and safe output scope. No separate monologue worker invoking a second cognitive engine.

### 7.4 Explicit exclusion: Shadow Memory [NEVER PORT]

Do not transplant LilavelStage's Shadow Memory, shadow `ExperiencePacket` proposer/verifier pipeline, background reflection, shadow retrieval/M3/M4 bridge or its semantic index. Person Memory, Agenda and Open Threads are **not** Shadow Memory and remain in scope for later dedicated stages. No automatic background model service is implied by this Blueprint.

Keep context/privacy scopes strict and consolidation off the speaking critical path. Character quality and continuity require live evaluation, not just schema checks.

## 8. GPT-6 Luna and transport

**M6.0 baseline:** the implemented experimental path uses a Bun/`pi-ai` bridge with Codex OAuth, `LunaStream`, `SingleMindPort` and streaming tool-call deltas. Reuse it in the Perception Loop rewrite; do not switch to direct API, OMP, or a second model as part of batching work.

The initial model/reasoning pair is GPT-6 Luna `low`. Validate provider-supported reasoning modes rather than assuming `off` is supported. Model plain text is not public speech; `speak` and `stay_silent` remain the decisions. Provisional `speak.message` fragments stream but do not authorize arbitrary side-effecting tools.

Measure separately: queue/settle time, context assembly, provider first event, first tool delta, first usable speech fragment, bridge completion and Runtime completion. An end-to-end 3-second completion is **not** first-token latency; report actual measured points only. Benchmark the rewritten loop and direct M6.0 bridge with equivalent prompts/tools and warm/cold conditions before claiming latency regressions.

Do not allow provider changes to obscure the first ProjectBEA-equivalence test.

## 9. Vision and real sensors [NEW M6.2]

Bea's Minecraft adapter shows the valuable pattern: **event vs. live state**. It uses structured mod data, not an out-of-the-box screen-VLM solution.

First Liac sensor:

- Explicit, user-controlled capture of a selected screen or window.
- On-demand or scene-change-triggered frames. No continuous 30-FPS cloud VLM loop.
- One measured VLM turns a frame into concise observations, preserving source, time, uncertainty and expiry.
- Send those observations to the existing Perception Bus; non-meaningful repeats update state or are dropped.
- Avoid storing raw screenshots or uploading them to cloud systems by default. Permission is explicit.
- Bound image work to prevent stale VLM observations, latency and GPU contention.

Choose the VLM **after comparing real implementations and measurements** on the target machine. A game adapter with native structured events may be more reliable than vision for some tasks.

## 10. Streaming TTS and avatar [NEW M6.3]

Build TTS **after** Perception, Wake/Attention and a minimal real VLM sensor, per the target experimental sequence. Start with **one** voice engine and one output route.

Borrow from Bea's `JsonFieldStream`, `SpeechChunker` and `LiveLine` mechanics:

- Decode usable fragments of an incomplete `speak.message` JSON string correctly, including escapes.
- Send complete pronounceable chunks to TTS before Luna finishes the entire call.
- Preserve speech order with a small bounded lookahead; don't build a general media pipeline.
- Cancellation and barge-in stop stale queued and playing sound. Never let a cancelled turn continue speaking.
- Store the **actually delivered/heard** part if that information is available, not the hypothetical complete sentence.
- Later mood/face tags may select existing avatar assets. Do not add complex affect/prosody layers during the first audio benchmark.

Measure the whole chain: settled input → first model/tool delta → first usable `speak` fragment → first audio chunk → **first audible sound**. Streaming does not remove any long reasoning pause before the first visible delta.

## 11. External actions, adapters and authority [FUTURE]

External capabilities must be explicit, actually available and scoped to the current turn. BEA's tool action lifecycle is the primary reference; LilavelStage's `TurnAuthority` is the safety reference for Discord/multi-channel actions.

- Validate actor, allowed destination, arguments and effect result before recording delivery.
- Do not derive permissions from user prompt content, traces, untrusted observation text or memory.
- Confirm only actually delivered effects in canonical history; preserve failed/unknown outcomes distinctly.
- A later tool result may enter the shared Bus as a perception or follow-up step; never create a separate model loop.
- Game/OBS/Loonyball/Discord remain separate adapters, added only when actually integrated; no unrestricted shell/desktop authority.

No speculative generic plugin framework is required.

## 12. Concurrency, failure and lifecycle

One asyncio owner controls the Bus, serialized cognitive loop, Journal and runtime state. Adapter I/O, slow sensors, trace sinks and future TTS must never block normal intake. Cross-thread producers marshal to this loop.

**Mandatory invariants:**

- Multiple quick direct messages can become **one batch/one Luna call**; a Send press or STT final is not an automatic batch flush.
- No new direct input mechanically cancels an ordinary active text turn. Backlogged messages are retained, with original arrival timestamps and bounded capacity.
- Queue acceptance is not Journal durability. After drain, runtime owns committing, retry/error settlement and no-double-speech recovery.
- Canonical event IDs and complete turn ordering are stable; shutdown and restart produce no fabricated deliveries.
- Only Runtime can authorize and execute external effects. Streaming provisional output is not a committed action.
- No observer, debug dashboard, trace subscriber or memory projection changes model decisions or outward actions.
- Untrusted source/channel text never crosses authorized conversation scopes.
- A real future ambient update does not change an already frozen model context.

When BEA safe restart/steering is later added, cancellation must be conditional on **no outward side effects** and must restore all unconsumed perceptions. Do not apply blanket `_cancel_active('superseded')` at intake.

## 13. Acceptance and measurement

**Phase 1 is not accepted until these deterministic fake-backed scenarios pass:**

| Scenario | Required result |
| --- | --- |
| A/B/C at 0.0/0.4/0.8s | One settled batch containing 3 inputs, one context, one Luna call |
| Quiet gap expires | Messages outside the gap become distinct batches |
| Continuous messages | Hard `max_window` closes batches rather than starving inference |
| A is generating; B/C arrive | A completes normally, B/C retained and grouped for next turn, no implicit supersession |
| Late drained backlog | Ingress timestamps respected; no extra full quiet-gap wait |
| Mixed authorized sources / multiple keys | Stable order, correct privacy scope, no silent cross-channel mixing |
| Duplicate/retry/overload/shutdown | No lost accepted input or duplicate confirmed response; explicit rejection and recovery |
| `speak`/`stay_silent`, partial streaming, provider error | Correct terminal settlement and canonical history |

After fake tests, run a real GPT-6 Luna LOW smoke test using the existing Codex bridge. State observed outputs, model calls and timings; do not call synthetic tests live evidence. Test later Attention/Admission (addressing, follow-up, rejected events), steering/restart, memory tools, spontaneous rhythm and Trace separately.

**Trace must show** input ID/source, arrival, queue size, batch membership/close reason, Attention score, Admission verdict, turn ID, provider timing, tool decision, terminal outcome and causal links when those components exist. Log bounded diagnostic information; never leak tokens, credentials, private prompt content or uncensored transcripts by default.

**Latency metrics:** provider first event vs first tool delta vs first usable speech vs complete runtime turn, with p50/p95 over enough comparable warmed trials. End-to-end voice work also measures first audible sound; do not claim an unmeasured result. Keep the pre-existing PySide6 `MainWindow.context` regression outside this architecture rewrite unless separately fixed.

## 14. Milestones and mandatory sequencing

| Phase | Scope | Exit evidence |
| --- | --- | --- |
| **M0–M5.0** | Legacy Fast/Deep implementation | Historical baseline, preserve unchanged |
| **M6.0** | Single Luna model port, bridge, explicit speech/silence, streaming and SQLite Journal | **IMPLEMENTED on isolated branch**, baseline for rewrite; not proof of correct scheduling |
| **M6.1a – BEA Perception Loop** | New branch from M6.0; BEA-like `put/drain/settle`, quiet-gap windows, one awaited `Consciousness` loop, queued mid-turn input | Burst/busy-turn/backlog/failure tests + Luna live smoke |
| **M6.1b – Attention + Admission** | BEA deterministic ranking/follow-up + separate LilavelStage Admission, with scoped and auditable decisions | Admitted/rejected text tests; no silent loss or extra calls |
| **M6.1c – Steering + tools** | BEA mid-turn steering and conditional safe restart; bounded multi-step tool lifecycle; scoped authority for real effects | Controlled restart only before effects; replay and permission tests |
| **M6.1d – Experience and rhythm** | BEA/Lilavel person memory, Agenda, Open Threads, spontaneous presence, context/handoff | Independent lifecycle/retrieval/permission tests; no Shadow Memory |
| **M6.1e – Observability + Electron** | LilavelStage-style TraceBus, BEA turn diagnostics, Electron Trace Explorer with live stream, filtering/replay and typed finalized-STT simulator | Exact turn trace, replay, context inspection and same-Bus chat tests |
| **M6.2** | One real screen/VLM or structured game adapter, then bounded silent LiveState | Verified real observations update next context without spurious inference |
| **M6.3** | Real STT and streaming TTS, interruption, avatar expression | Recorded real first-audio delay, transcript and barge-in behavior |
| **Later** | Discord/OBS/Loonyball/game integrations and measured refinement | Per-adapter evidence; nothing bypasses shared Bus/authority |

This table is a **roadmap**, not a demand to implement all phases in one PR. The first agent task is **M6.1a only**, with a mapping table `ProjectBEA source → Liac target → intentional deviation`. After a successful first slice, refine upstream behavior in *separate* measured PRs.

**No first-slice implementation** of synthetic ambient observations, LiveState, VLM, game events, STT, Electron, Shadow Memory or generic optimizations. Build only the real contracts necessary for correct text intake and model execution.

## 15. Code layout and boundaries

| Area | Ownership |
| --- | --- |
| `contracts/` | Immutable Perception, event, model and output contracts |
| `runtime/perception_bus.py` | Single bounded intake, BEA-compatible settling, dedupe and backpressure |
| New focused `runtime/` loop module | Only owner of batch admission and serialized Luna turns |
| `runtime/journal.py` | One canonical SQLite event history and transactional replay |
| `minds/`, `tools/luna-bridge/` | Existing M6.0 Luna and fake streaming adapters |
| Context projection | Stable frame, whole-turn history and tool-aware replay |
| Future `attention/` or focused runtime modules | BEA scoring, LilavelStage Admission; no second mind |
| Future `memory/` | Bounded person/roster, Agenda and Open Threads records; never Shadow Memory |
| Future `trace/` | Typed diagnostic TraceBus, ring buffers, subscriber isolation, optional private JSONL/replay |
| Future `hub/` | Electron React Trace Explorer and finalized-utterance test input; no parallel model path |
| Future `sensors/`, `expression/` | Real STT/VLM/game event input and TTS/avatar output |
| `tests/` | Deterministic edge/behavioral integration, with honest separate live evidence |

Keep Python as a modular monolith. In particular, **LilavelStage's TUI is not the planned interface**: borrow its TraceBus, structured events, SSE/observer semantics and browser Trace Explorer concepts, but display diagnostics in Electron.

The Electron Trace Explorer should offer Overview, Mind/Context, Trace Timeline, Models/latency, Memory and Runtime. Required trace interactions: filter/search, replay/pause/step, full event JSON, linked input→batch→turn→tool chain, exact compiled-frame inspection (local opt-in with privacy bounds), exportable private snapshot. Connect to typed runtime events, not parsed stdout; snapshots recover UI state, streaming events drive live updates. Its Chat composer must publish the same finalized speech perception future STT does.

Never give tracing or UI observers control over tool authority or canonical history merely by viewing events.

## 16. Open questions and references

Open empirical questions: ProjectBEA-equivalent quiet-gap performance with Luna, mid-turn text vs. voice semantics, safe steering/cancellation, upstream context-window handoff compatibility, Codex provider first-event latency, future voice first-audio delay, real VLM performance and bounded memory lifetime. No claims of complete live integration until measured.

### Primary: ProjectBEA

- [PerceptionBus](https://github.com/emqnuele/projectBEA/blob/main/src/core/perception/bus.py), [types](https://github.com/emqnuele/projectBEA/blob/main/src/core/perception/types.py) – queue, settle, backlog and text/live gap semantics.
- [Consciousness](https://github.com/emqnuele/projectBEA/blob/main/src/core/consciousness.py) – one loop, steering and tool effects.
- [Attention rules](https://github.com/emqnuele/projectBEA/blob/main/src/core/attention/rules.py), [gate](https://github.com/emqnuele/projectBEA/blob/main/src/core/attention/gate.py) – addressed/follow-up/priority **without a model admission threshold**.
- [SingleContext](https://github.com/emqnuele/projectBEA/blob/main/src/core/mind/single_context.py), [handoff](https://github.com/emqnuele/projectBEA/blob/main/src/core/mind/handoff.py), [turn logs](https://github.com/emqnuele/projectBEA/blob/main/src/core/mind/turnlog.py) – stable replay and diagnostics.
- [Tool lifecycle](https://github.com/emqnuele/projectBEA/blob/main/src/core/mind/tools.py), [memory store](https://github.com/emqnuele/projectBEA/blob/main/src/core/memory/store.py), [Agenda](https://github.com/emqnuele/projectBEA/blob/main/src/core/social/agenda.py), [SpontaneousPresence](https://github.com/emqnuele/projectBEA/blob/main/src/core/mind/spontaneous.py) and [Rhythm](https://github.com/emqnuele/projectBEA/blob/main/src/core/social/rhythm.py).
- [EventManager](https://github.com/emqnuele/projectBEA/blob/main/src/core/events.py), [streaming tool decoder](https://github.com/emqnuele/projectBEA/blob/main/src/core/agent/streaming.py), [LiveLine](https://github.com/emqnuele/projectBEA/blob/main/src/core/expression/live.py).

### Secondary: LilavelStage

- [PerceptionBus](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/bus.py) – historical fixed-window reference only.
- [StageLoop](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/stage_loop.py) and [behavioral contract](https://github.com/SheetHappiness/LilavelStage/blob/master/BEHAVIOR.md) – scoped admission, action/outcome history and steering comparisons; do not transplant the 2,100-line loop.
- [Attention/Admission](https://github.com/SheetHappiness/LilavelStage/tree/master/src/lilavel_stage/attention), [Open Threads](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/open_threads.py), [Agenda](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/agenda.py), [TurnAuthority](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/authority.py).
- [TraceBus](https://github.com/SheetHappiness/LilavelStage/blob/master/src/lilavel_stage/trace.py), [browser trace console](https://github.com/SheetHappiness/LilavelStage/tree/master/src/lilavel_stage/web_dashboard_assets) – target semantics for a new **Electron** inspector.
- [Third-party notices](https://github.com/SheetHappiness/LilavelStage/blob/master/THIRD_PARTY_NOTICES.md) – prior BEA attribution and MIT adaptation precedent.

Snapshot reference: old [ProjectBEA `f2186fc`](https://github.com/emqnuele/projectBEA/tree/f2186fc647db3f9ae65e6463b9f82c882bdca68b); pin the actual upstream SHA(s) read during the new adaptation. Historical local reports remain valid for their own branches, not for the M6.1 rewrite: [M5.0](M5_0_PERCEPTION_BUS.md), [M4.8](M4_8_CONTEXT_HANDOFF.md).

---

**Direction:** Give Luna one world, one coherent context and one serialized mind. Reproduce ProjectBEA's intake and cognition behavior first; then add LilavelStage-style admission, capabilities, memory and an **Electron Trace Explorer** in separately verified slices. **No Shadow Memory.**

