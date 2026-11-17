# M4.8 — Asynchronous Context Handoff

Status: proposed specification, based on the user's M4.8 request. No implementation is authorized by this planning deliverable.

## Scope

Luna summarizes Cold history asynchronously while Bolt continues using its immutable Fast snapshot. After an atomic Epoch transition, future prompts contain the summary, untouched raw Hot history, and newer dialogue. Reuse Epochs, SQLite, the existing Deep worker, canonical journal and exact Nemotron tokenizer.

- Default context window: 16,384 tokens including generation reserve; preserve current output reserve and safety margin.
- Hot suffix target: 1024 tokens, counted through the configured tokenizer and actual message rendering.
- Keep complete terminal turns; a 1400-token final turn stays whole.
- Preserve the 75% preparation trigger, existing emergency fallback and prefix order.
- Summary is authored only by Luna. Hot is raw and unchanged.
- Luna may see Hot for understanding, but compaction covers only the explicitly marked Cold range and previous Epoch knowledge.
- Frozen active Fast snapshots cannot change. No inference occurs inside SQLite transactions and Bolt never waits for Luna.
- New turns committed during inference remain raw after the requested cutoff.
- Late Luna results cannot rewind a newer fallback Epoch. Recovery remains durable across restart.
- Markdown-only changes cannot alter the stable prefix within one Epoch.
- Preserve M4.7 Bolt/Luna roles, Nemotron template and schema-v3 result envelope.
- No new memory store, worker, persistence format, Perception Bus, VLM or Neuro SDK.
- English application UI and code comments; no GPT-6 Astra subagents. Every commit and PR credits softsock <109231668+softsock@users.noreply.github.com>.

## Planning decisions for review

Select the shortest newest suffix reaching **at least** 1024 rendered tokens, including whole turns until it does. If all available raw history is shorter, preserve all of it and request no ordinary compaction. Token cost is the difference between rendering that suffix and rendering empty dialogue with identical fixed framing; do not add independently counted event costs.

Use globally closed turn boundaries: a terminal event is not a legal cutoff if another turn opened before it is still unfinished there. Failed/cancelled turns retain their canonical user text; partial replies are not invented.

Recovery's cutoff is at least the active fallback cutoff. It may preserve more Hot than 1024 tokens, but cannot resurrect dialogue already omitted by fallback as raw Hot. Rebuild summary from the last meaningful Epoch plus canonical Cold events. If the request's observation range cannot cover that floor, defer recovery until a safe batch can; never clamp to a nonterminal sequence.

These are implementation choices, not additional user requirements. Emergency fallback can retain less than the Hot target; label it degraded budget projection, not semantic compaction.

## Acceptance

Offline checks prove unchanged Hot UTF-8 payloads, whole-turn cutoffs, nonblocking delayed Luna, immutable in-flight Fast snapshots, preservation of newly completed turns, fallback supersession/equal-cutoff recovery, stable prefixes after Markdown updates, and SQLite restart recovery.

One controlled live run uses a 4096-token window and real Bolt/Luna: inspect the actual request boundary, real summary, retained Hot, next Fast prompt and recall after restarting the same database. Exercise overflow while Luna is held and distinguish the injected hold from natural provider latency. Then verify Markdown-only prefix caching with a 16,384-token configuration and short real dialogue, without filling the window artificially. Prefix byte equality proves stability; backend counters are needed to claim cache reuse. Missing counters or inaccurate recall must be reported explicitly.

## Delivery

At execution time create `codex/m4-8-context-handoff` from verified M4.7 in an isolated worktree. Two commits: (1) cutoff algorithm, integration and regression tests; (2) live verification support, evidence report and documentation. Planning creates no branch or repository changes.
