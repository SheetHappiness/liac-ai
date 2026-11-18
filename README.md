# Liac Single Mind

Liac is a local, text-only runtime inspired by ProjectBEA. A perception bus
groups incoming events. The runtime records each batch in SQLite and runs one
serialized turn for each batch with fresh direct chat. GPT-6 Luna chooses
`speak` or `stay_silent`. Streaming speech is provisional until the decision
is committed.

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
suffix of journaled dialogue. The runtime reads up to 40 dialogue events, and
the Pythonâ€“Bun bridge caps each JSONL frame at 64 KiB. Completed tool calls
and their results travel together. Older dialogue remains in SQLite. The
runtime has no long-term memory or compaction.

## Checks

```powershell
python -m unittest discover -s tests -v
node --test tools/luna-bridge/*.test.mjs
```

See the [M6.1 perception report](docs/M6_1_BEA_PERCEPTION_REWRITE.md) for the
batch timing and acceptance evidence. Earlier milestones are indexed in
the [archive](archive/README.md).
