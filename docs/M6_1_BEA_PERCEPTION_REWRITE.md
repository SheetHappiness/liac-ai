# M6.1 ProjectBEA perception rewrite

Base: `codex/m6-0-single-mind` at `8f726498d7efe86f1e25e85f15543f442e08d9ea`.
Reference: [ProjectBEA at f2186fc](https://github.com/emqnuele/projectBEA/tree/f2186fc647db3f9ae65e6463b9f82c882bdca68b/src/core).

| ProjectBEA source | Mechanism | Liac and verification |
| --- | --- | --- |
| `perception/types.py` | Typed inputs carry author, provenance and metadata. | Preserve immutable Perception and raw Journal events, with stable IDs and ingress order. Check the batch frame and Journal together. |
| `perception/bus.py` | Settle queued backlog together, then use ingress time and the shortest applicable quiet gap. Cap from settle start. Holds can defer quiet closure up to the cap. | Extend the existing bounded asyncio bus. Test quiet closure, aged backlog, the cap, and both steering primitives. |
| `consciousness.py` | Remember before deciding whether to think. Await the owned turn, then drain again. Frame a batch together. | SingleMindRuntime owns the turn and Journal acceptance. Test intake during inference, failure, and shutdown. |
| `attention/gate.py` | Annotate the full batch and use tagged context for follow-up. The loop separately decides whether to run. | Journal acceptance is followed by a direct-input check. Frame projection is the insertion point for future ranking. |
| `attention/rules.py` | Score addressed and follow-up signals first, then other perceptions with activity and salience. | Preserve ingress order and test that all direct text reaches the model. |
| `mind/single_context.py` | Use a shared bounded window with tagged lines and replayed call/result pairs. | Project one conversation from SQLite with the existing byte budget and tool replay. |
| `mind/tools.py` | Run explicit actions through tool calls with the turn's routing context. | Keep the existing terminal speak/silence contract and provisional deltas. Test that incomplete and stale results cannot commit. |


## Behavior and choices

- The one-runtime Bus accepts input on the asyncio event loop during inference.
  Intake stays bounded at 256 pending entries with explicit backpressure and ID
  checks. Noise is dropped at intake. BEA uses an unbounded queue, supports
  thread producers and puts noisy events into its own filtering flow.
- A settled batch combines all pending entries for the head conversation key.
  It preserves ingress order, including historical backlog across old idle
  gaps. BEA can group multiple routes and sorts by source timestamp. Liac's
  `drain_nowait()` and `steer()` keep the same key boundary. The latter waits
  for typed input when requested and returns promptly if relevant live input arrives.
- The shortest applicable gap is 0.30s for live input and 1.20s for chat.
  The hard cap is 3.00s from settle start. BEA sweeps all waiting items at both
  the quiet deadline and the cap. Liac includes arrivals before the active
  cutoff and keeps later arrivals for the next drain, even if the loop wakes
  late. The quiet deadline is the existing point for a future STT hold, with
  the hard cap still taking precedence.
- Each batch with fresh direct local chat commits raw events and one canonical
  user event in the same transaction. The canonical record retains ordinary
  `text` and adds a batch ID and ordered fresh perception IDs. A frame reads
  and labels each record using its own kind, source, key, author, timestamp,
  delivery and ID. Same-key ambient input in that batch is included. Ambient-only
  batches are auditable and have zero model calls. The M6 local frame can
  represent several authors explicitly. The legacy Fast path retains its
  single-author check and existing user event shape.
- The sole turn owner awaits one model call and commits a terminal result before
  starting the next turn. Tool replay uses the original call ID. Provisional
  speech stays ephemeral. The two terminal tools and Bun/pi-ai transport remain
  the M6.0 ones. BEA has multi-step generation, mid-turn steering, safe voice
  restart and routed tools. This milestone exposes the Bus primitives for
  later steering and executes one model call per admitted batch.
- `/quit` and EOF finish queued work. An orderly interrupt stops intake, cancels
  and joins the active turn, and records pending direct batches as cancelled
  before exit. On restart, already-journaled unfinished inputs are cancelled
  without rerunning actions. Abrupt process death can lose the ephemeral queue
  ahead of the Journal. Use one process per conversation database.
- The legacy CLI and desktop continue submitting ordinary individual messages.
  Existing M5 callers that use the shared `PerceptionBus` pick up the new defaults
  and backlog semantics. Explicit timing arguments still work.

The design adapts ProjectBEA's behavior within Liac's existing implementation.
Upstream source is MIT-licensed. [ProjectBEA license, Emanuele Faraci](https://github.com/emqnuele/projectBEA/blob/f2186fc647db3f9ae65e6463b9f82c882bdca68b/LICENSE)

## Run and inspect

Use Python 3.12+ with the package installed, or set `PYTHONPATH=src`. For
real Luna install the lockfile with `npm ci --prefix tools/luna-bridge`, use
Bun on PATH or `--bun PATH`, and use the existing Codex login flow. [M6.0 bridge setup](M6_0_SINGLE_MIND.md)

```powershell
python -m vtuber.m6 --backend fake --trace --db .data/m6-fake.sqlite3
python -m vtuber.m6 --backend luna --reasoning low --trace --db .data/m6-live.sqlite3
```

Traces are optional and private under `.data/traces/`. They contain IDs, timing,
queue sizes, closing reasons and terminal statuses. The recorder receives no
message text, reply text, prompt or credentials. A shutdown that interrupts
settling can leave an open trace for the aborted attempt. The final shutdown
drain traces those inputs under its own batch ID. SQLite records the delivered
batch and outcome.

## Verification

Python 3.14.7 baseline at the specified M6.0 commit had 181 passing tests and one
skip. The rewrite had 188 passing tests and one skip with
`python -m unittest discover -s tests`. All 7 Node bridge tests passed. The
legacy CLI opened, returned `/state` and exited normally. The fake M6 console
rendered one provisional stream and one final reply from three piped inputs.

| Acceptance | Checked behavior |
| --- | --- |
| A, J | Three messages 0.4s apart reached one ordered frame, model call and terminal reply. A separate console test observed one call to the actual FakeSingleMind. |
| B | A two-second gap produced two batches while the loop was available. |
| C, D | A second burst queued during a held call. Even backlog spanning an old quiet gap ran together without a new full settle wait. |
| E | Continuous arrival hit the cap. Bus and Runtime both delivered later input in a subsequent batch. |
| F | Pending and committed duplicate IDs caused no duplicate raw event or speech. A conflicting ID was rejected without dropping unrelated queued input. |
| G | Provider failure, an incomplete decision and context overflow each left a failed turn and allowed the following turn to run. |
| H | Two ordered provisional deltas preceded committed speech. Silence produced no speech. Late fragments were ignored. |
| I | Explicit stop, interrupted console, stop during the settle timer race and restart left no unfinished inputs. Pending input was recorded without model execution and committed actions were not replayed. |

Other checks covered route isolation, ambient-only audit, mixed live/text
quiet gaps, steering, a trace sink failure and the existing transport and
legacy suites.

### Authenticated Luna smoke

Two short runs used the real `python -m vtuber.m6 --backend luna --reasoning low`
entry point on Windows, Python 3.14.7, Bun 1.4.4 and pi-ai 18.22.1. Each
run used fresh temporary conversation storage and the local ignored Codex
auth store. Both runs journaled five raw inputs as groups of three and two,
ran exactly two serial Luna calls and ended with two completed turns and zero
unfinished inputs. The second run produced one provisional stream, one
visible final reply and one intentional silent completion.

Actual second-run trace, relative to first input. Batch and turn IDs are
abbreviated here.

| Elapsed | Event |
| --- | --- |
| 0.000s, 0.406s, 0.819s | Three perceptions enqueued in batch `d00eba8c`. |
| 2.022s | Batch `d00eba8c` closed by quiet gap with 3 entries. |
| 2.025s | Luna started turn `45362b70`. |
| 2.056s, 2.170s | Two more inputs entered the queue while Luna was generating. |
| 3.504s | Turn `45362b70` committed `speak`. |
| 3.505s | Batch `1937e6aa` opened and immediately closed by the elapsed quiet gap, with 2 entries. |
| 3.507s | Luna started turn `ed1dfb50`. |
| 4.569s | Turn `ed1dfb50` committed `stay_silent`. |

Provider acceptance covers these short local runs. Cancellation and restart
were exercised with a deterministic fake, including the console task
cancellation path. Provider cancellation, hard process death and sustained
sessions were outside the smoke coverage. Attention, live state, other
sensors and automatic steering or voice restart remain future work.

## Changed files

| Files | Change |
| --- | --- |
| `src/vtuber/contracts/perception.py`, `src/vtuber/runtime/perception_bus.py` | Batch IDs, settle and steering, metadata traces. |
| `src/vtuber/runtime/single_mind.py`, `src/vtuber/m6.py` | Serial turn ownership, stdin lifecycle and trace option. |
| `src/vtuber/runtime/journal.py`, `src/vtuber/minds/m6_context.py`, `src/vtuber/minds/fake.py` | Group membership, frame projection and fake reply text. |
| `tests/test_perception_bus.py`, `tests/test_single_mind.py`, `tests/test_m6_cli.py` | Bus, integrated Runtime and console checks. |
| `README.md`, `docs/PROJECT_BLUEPRINT.md`, this report | Usage, architecture and acceptance evidence. |
