# M6.1a – Wake and ephemeral Live State

**Status: EXPERIMENT / implementation pushed, not independently tested.**
Base: M6.0 branch at `8f726498`. Branch: `codex/m6-1-attention-live-state`.

## What this slice adds

The first minimal Perception → Attention → Luna context path:

1. Keep the existing `PerceptionBus` and `Journal.accept_local_perceptions` unchanged.
2. **Wake:** only newly accepted local direct chat starts Luna. Ambient state and noise never cause an inference request or cancel an active generation. `should_wake` makes this conservative policy explicit.
3. **Live State:** trusted ambient `state` / `observation` inputs update the last value per (conversation, source, kind), in memory. Default 8 entries, 120-second monotonic expiry. No database or background worker. A replayed sensor ID does not refresh the volatile state.
4. **Attention:** the most recently updated source appears first. `LiveState.snapshot` isolates conversation scopes.
5. **Context:** the next addressed turn gets a bounded JSON-quoted sensor summary **before** the actual user message. Each entry's source and text are truncated; the outer 63-KiB bridge-input budget still applies. The system instruction declares observations untrusted data rather than user commands.
6. **Frozen inference frame:** an ambient event arriving while Luna generates changes only future snapshots.
7. **Manual proof:** type `/scene Window shows an error message`, then a normal question in `python -m vtuber.m6 --backend fake` or `--backend luna`. `/scene` updates state without generating a reply.

This is intentionally **not** a full Bea Attention score engine, event-triggered initiative, memory migration, VLM, TTS or game tools. Direct-only Wake is the safe initial policy until actual autonomous triggers have typed importance metadata.

## Source boundaries

- New: `src/vtuber/runtime/attention.py` (`should_wake`, `LiveState`).
- Updated: `src/vtuber/runtime/single_mind.py`, `src/vtuber/minds/m6_context.py`, `src/vtuber/m6.py`.
- Tests: `tests/test_m6_attention.py`, `tests/test_m6_cli.py`.
- No change to the legacy Fast/Deep model roles, storage schema, OMP or Codex bridge. The new path is opt-in.

## Verification to perform locally

```powershell
$env:PYTHONPATH='src;tests;vendor/omp-rpc/src'
python -m unittest test_m6_attention test_m6_context test_single_mind test_m6_cli test_perception_runtime -v
python -m unittest discover -s tests -v
python -m vtuber.m6 --backend fake --db .data/m6-1-fake.sqlite3
```

In the console, enter `/scene Browser displays a red warning` and then `What do you notice?`. Verify one response, no standalone scene-triggered speech, and a `CURRENT SENSOR STATE` block in the captured model frame.

**Verification status:** source-level review only in this session. No repository-local test runtime or authenticated Luna credentials were available here. **Do not mark tests or live latency as passed without running them.** M6.0's previously recorded baseline was 188/189 Python tests, with one existing Desktop error.

## Next slice

M6.1b: evaluate longer Hot/Cold context replay from M4.8 against real Luna's context and cache measurements, then introduce a carefully scoped exceptional Wake trigger **only when a real VLM/game source supplies meaningful change metadata**. Keep the current direct-only policy otherwise. M6.2 is screen VLM; M6.3 is TTS and first-audio timing.
