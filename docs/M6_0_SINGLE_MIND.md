# M6.0 Single Mind

Status **EXPERIMENT**. Base `fa7c5d7` in SheetHappiness/liac-ai.

## Task 1 transport decision

**GO with Bun.** Node 22.23.3 passes the syntax check but cannot load the
published TypeScript entry point of `@oh-my-pi/pi-ai` 18.22.1
(`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`). The package declares Bun
1.4.4 or newer. The user approved Bun for the optional bridge after the
standalone probe succeeded. `pi-ai` and its public model catalog are both
pinned at 18.22.1 in the isolated lockfile.

Run from the worktree root on Windows:

```powershell
Push-Location tools/luna-bridge
npm ci --ignore-scripts
Pop-Location
node --check tools/luna-bridge/probe.mjs
node tools/luna-bridge/probe.mjs --list
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --list
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --login
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --reasoning low
npx --yes --package=bun@1.4.4 bun --no-env-file tools/luna-bridge/probe.mjs --reasoning off
```

The Bun probe listed the exact `openai-codex/gpt-6-luna` model offline and
again through authenticated discovery. Browser OAuth uses the library's
loopback flow and the isolated, ignored `.data/m6-auth/` credential store.
The ordinary stdout report includes only model, capability, validation and
timing metadata. The wire hook compared the exact model, `low` request effort,
two synthetic prompt items and two tool names in memory.

| Matched `low` trial | First event (ms) | First tool delta (ms) | First usable fragment (ms) | Completed (ms) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 449 | 862 | 958 | 1025 |
| 2 | 519 | 885 | 949 | 1057 |
| 3 | 498 | 919 | 987 | 1096 |
| 4 | 533 | 1183 | 1259 | 1352 |
| 5 | 576 | 1024 | 1069 | 1163 |
| Median | 519 | 919 | 987 | 1096 |

Five of five measured requests produced a single completed `speak`, with
strictly parsed stream arguments matching the terminal call. The provider
reported 81 input and 21 output tokens per trial, with zero cache reads and
writes. An exploratory request successfully returned a tool call while the
initial probe failed to detect the short fragment from the SDK's throttled
partial arguments. The measured run used the raw argument deltas to detect
the ASCII fixture's first usable fragment. The active catalog advertised
`low`, `medium`, `high`, `xhigh` and `max`. **`off` unavailable** on the
observed route. The probe declined it before inference.

The offline M5.0 baseline on Python 3.14.7 ran 165 tests with 164 passing.
`test_desktop.WindowTests.test_chat_context_selection_and_offline_history`
errored because `MainWindow.context` is absent.

## Task 2 transport verification

The same authenticated Bun subprocess handled two turns from Python 3.14.7
through `LunaStream`. The final standalone run used synthetic prompts and a
short probe system prompt.

| Decision | First tool delta (ms) | First speech fragment (ms) | Completed (ms) | Input / output tokens |
| --- | ---: | ---: | ---: | ---: |
| `speak` | 1017 | 1116 | 1238 | 78 / 24 |
| `stay_silent` | 2069 | — | 2105 | 76 / 16 |

The speech turn streamed seven provisional deltas and their concatenation
matched the final message. Silence delivered zero text deltas and a complete
tool call. Both reported zero cache reads and writes. The timings are for
the standalone transport. The first `speak_delta` is decoded preview text.
Only a validated terminal `result` carries a completed decision to Python.
A third live turn was cancelled after its first preview, and a subsequent
turn returned a valid silence decision with no stale frames.

Offline checks use a Python subprocess fixture and the pure JS decoder:

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
python -m unittest test_luna_stream -v
node --test tools/luna-bridge/speak_stream.test.mjs tools/luna-bridge/request_privacy.test.mjs
node --check tools/luna-bridge/bridge.mjs
python -m unittest discover -s tests -v
```

The final run passed six focused Python tests and seven Node tests. The full
Python suite had 170 passes out of 171 tests, with the same baseline desktop
error.

Independent review found raw SDK logging, a race on repeated cancellation,
and duplicate JSON fields. Regression tests reproduced each issue before the
fix. Both JS entry points clear the inherited `PI_REQ_DEBUG` flag and set the
pinned SDK's `PI_TEST_RUNTIME` guard for automatic HTTP 400/413 request dumps.
That guard also makes the dedicated SDK process headless and redirects its
general SDK log directory to the Bun test temp location. A synthetic 400/413
check intercepted disk writes and confirmed both were suppressed. The final
live bridge smoke inherited `PI_REQ_DEBUG=1` and produced no debug dumps.

The Python adapter holds its process lock through bounded cancellation cleanup,
including repeated cancellation. Tool decisions require raw JSON argument stream
evidence matching the provider's completed call. Missing deltas, duplicate
properties, malformed arguments and stale frames cannot authorize a decision.

This work covers Tasks 1 and 2. Durable Journal ingestion, tool-call replay,
SingleMind runtime and end-to-end console acceptance remain for Tasks 3–5.
