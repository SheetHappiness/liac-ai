# Repository Guidelines

Liac runs one perception-driven GPT-6 Luna turn at a time.
`src/vtuber/contracts/` defines immutable data and ports, `runtime/` owns
perception batching, SQLite and task lifecycle, and `minds/` owns model adapters
and character identity. `cli.py` composes the runtime. The Bun bridge lives in
`tools/luna-bridge/`.

- Read the nearest `AGENTS.md` before editing. Read the [M6.1 report](docs/M6_1_BEA_PERCEPTION_REWRITE.md) when changing settle timing, the turn loop or replay.
- Use Python 3.12+ in a virtual environment. Run `python -m pip install -e .` and `python -m vtuber` for the fake console. See the [README](README.md) for Luna setup.
- Run `python -m unittest discover -s tests -v`, `node --test tools/luna-bridge/*.test.mjs` when touching the bridge, and `git diff --check`.
- Use four spaces, snake_case functions, PascalCase classes, and type hints at public boundaries. Use English for interface text and code comments.
- Keep private data and credentials out of Git and diagnostics. Do not modify Loonyball, deploy, or install large services without an explicit request. Never use GPT-6 Astra for subagents.
- Use imperative Git subjects. Every commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`. Create PRs only when requested and credit softsock in the description.

The [archive index](archive/README.md) points to the original Fast/Deep system.
