# Liac Single Mind

Liac is a local, text-only runtime inspired by ProjectBEA. A perception bus
groups incoming events. The runtime records each batch in SQLite and runs one
serialized turn for each batch with fresh direct input. GPT-6 Luna chooses
`speak` or `stay_silent`. Streaming speech is provisional until the decision
is committed.

## Liac Hub

The Electron app starts the real GPT-6 Luna runtime at low reasoning. The
right-hand chat treats typed messages as final STT transcripts and displays
committed speech as simulated TTS output. The simulator settles a batch after
1.2 seconds without another submitted transcript, with no time ceiling for
the burst. On the left, Live shows perception,
batching, admission, model timing and actions. Select an event or chat message
to inspect its turn. Replay opens earlier runs while the current runtime stays
available in Live.

With Node.js 22.12+, Python 3.12+ and Bun 1.4.4+, run once from the checkout:

```powershell
npm ci --prefix tools/hub
npm ci --ignore-scripts --prefix tools/luna-bridge
bun --no-env-file tools/luna-bridge/probe.mjs --login
```

Open [Start-Hub.cmd](Start-Hub.cmd) on Windows or run `npm start --prefix tools/hub`.
Hub uses the checkout's `.venv` when present. Set `LIAC_PYTHON` and `LIAC_BUN` to
override executable paths. Hub also checks `.data/hub/bin` for a local Bun.

Each Hub run stores chat and diagnostic events under `.data/hub/runs/`.
**Record model context** is off on startup. Enabling it saves the exact
system and messages sent to the Bun bridge for subsequent requests in that
run. Treat the run folders as private conversation data.

## Run locally

From the source checkout, use Python 3.12 or newer in a virtual environment.

```powershell
python -m pip install -e .
python -m vtuber
```

The default fake backend needs no model, credentials or Bun. The `vtuber`
command and `python -m vtuber.m6` also open the Single Mind console.
Enter text, then type `/quit` or close stdin to finish queued input.

Install the pinned bridge dependencies and use Bun 1.4.4 or newer to run Luna.
The login uses the existing Codex OAuth flow. Run these commands from the
checkout root with Bun on PATH or pass its path with `--bun`.

```powershell
npm ci --ignore-scripts --prefix tools/luna-bridge
bun --no-env-file tools/luna-bridge/probe.mjs --login
python -m vtuber --backend luna --reasoning low
```

The Luna route is `openai-codex/gpt-6-luna` via `@oh-my-pi/pi-ai`. The console
reuses `.data/m6-fake.sqlite3` for fake mode and `.data/m6-0.sqlite3` for Luna.
Use `--db PATH` to select a different journal and `--trace` for local scheduling
metadata. Use one process per journal. Input in the in-memory bus can be lost
if the process is killed before the batch reaches SQLite.

## Context

Each request includes the character identity, tool instructions and a bounded
suffix of journaled dialogue. The runtime reads newest events first and stops
when the next event would exceed the 63 KiB projection budget. It sends the
retained events in chronological order, with completed tool calls and their
results together. The Python-Bun bridge caps each JSONL frame at 64 KiB.
Older dialogue remains in SQLite. The runtime has no long-term memory or
compaction.

## Checks

```powershell
python -m unittest discover -s tests -v
node --test tools/luna-bridge/*.test.mjs
```

See the [M6.1 perception report](docs/M6_1_BEA_PERCEPTION_REWRITE.md) for the
batch timing and acceptance evidence. Earlier milestones are indexed in
the [archive](archive/README.md).
