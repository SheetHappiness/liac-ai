# Liac Single Mind

Liac is a local runtime inspired by ProjectBEA. A perception bus
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
available in Live. Select **Resume** in Replay to continue a recorded
conversation in a new run. Hub takes a SQLite snapshot of the selected run
and displays its chat in Live. Launching Hub starts a fresh conversation.

With Node.js 22.12+, Python 3.12+ and Bun 1.4.4+, run once from the checkout:

```powershell
python -m pip install -e '.[luna]'
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
python -m pip install -e '.[luna]'
npm ci --ignore-scripts --prefix tools/luna-bridge
bun --no-env-file tools/luna-bridge/probe.mjs --login
python -m vtuber --backend luna --reasoning low
```

The Luna route is `openai-codex/gpt-6-luna` via `@oh-my-pi/pi-ai`. The console
reuses `.data/m6-fake.sqlite3` for fake mode and `.data/m6-0.sqlite3` for Luna.
Use `--db PATH` to select a different journal and `--trace` for local scheduling
metadata. Use one process per journal. Input in the in-memory bus can be lost
if the process is killed before the batch reaches SQLite.

### Screen inspection on Windows

In PowerShell, list the Windows display device names and set `LIAC_SCREEN_DISPLAY`
to the number at the end of the game display's name before starting Liac.

```powershell
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Screen]::AllScreens | Select-Object DeviceName, Bounds
$env:LIAC_SCREEN_DISPLAY = '1'
python -m vtuber --backend luna --reasoning low
```

With that setting, Luna can choose `inspect_screen` during a conversation turn.
The Pi bridge takes a fresh screenshot of the selected display and sends it to
the same Luna model as an image tool result. Luna can then speak or stay silent.
A turn without inspection uses one model request. Each inspection adds a model
request, with up to four inspections within the existing turn deadline.

The whole selected display is sent to the model when inspected. Screenshots stay
out of local files, the Journal, and diagnostics. Later turns retain the spoken
conversation. Turn usage totals include every model request in the turn.

## Context

Luna receives the character instructions, a recap of older turns, recent
whole turns in chronological order, and the current input. The estimate uses
`o200k_base` and includes the tool schemas and replayed tool calls and results.
The bridge accepts up to 8 MiB per request and 64 KiB per response, including
the JSONL delimiters.

At 37,500 estimated input tokens, a background handoff can fold an older
prefix into a recap of up to 1,024 tokens. It keeps at least the two newest
completed turns and all fragments since the last spoken reply out of the
recap. SQLite commits the recap and its coverage together and keeps the
original events. During a slow or failed handoff, a foreground turn uses the
last saved recap and the newest whole turns that fit. The trace records
whether history was omitted, the estimated and provider-reported input
counts, frame size, and timing. The fake console retains its lightweight
byte-bounded projection.

The 50,000-token working budget is 80% of the largest successful synthetic
recall probe, rounded down to 1,000 tokens. Each probe placed a unique
checkpoint code more than 64 KiB before the end of the request and asked
Luna to repeat it. Each response matched exactly.

| Target | Estimated input | Reported input | Request bytes | First speech fragment |
| ---: | ---: | ---: | ---: | ---: |
| 16,000 | 15,249 | 14,977 | 213,860 | 1,099 ms |
| 32,000 | 31,245 | 30,973 | 442,346 | 1,529 ms |
| 64,000 | 63,249 | 62,977 | 899,464 | 1,630 ms |

The probes used the live GPT-6 Luna low route through Pi. Each row is one
synthetic run. The working context is scoped to a single conversation.
In a separate live check, Hub resumed a journal after a handoff. Luna
repeated the exact checkpoint code from the saved recap, with both recent
silent turns preserved verbatim. The source journal and its replay were
still available.

## Checks

```powershell
python -m unittest discover -s tests -v
node --test tools/luna-bridge/*.test.mjs
```

See the [M6.1 perception report](docs/M6_1_BEA_PERCEPTION_REWRITE.md) for the
batch timing and acceptance evidence. Earlier milestones are indexed in
the [archive](archive/README.md).
