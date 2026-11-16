# M4.7 — Bolt and Luna Roles

Status: **DECIDED** role boundary, based on the owner's 2026-11-16 clarification; **PROVISIONAL** live acceptance.

## Intent

Bolt is the source of truth for its own personality, preferences, speech and decisions. Luna preserves and organizes Bolt's experience through memory, context compaction and open threads; it does not direct Bolt's behavior. SQLite remains the authoritative technical record. Bolt's statements are not automatically objective facts about the world or the user.

Behavioral regressions belong in separate Bolt fine-tuning work, not corrective code or added personality instructions. The current, older Bolt without fine-tuning is an acceptable baseline. M4.7 must not require it to demonstrate a personality it has not learned.

## Smallest complete approach

Remove the old director relationship from authored prompts and context labels. Keep the existing asynchronous Markdown/compaction pipeline and schema-v3 transport. Do not introduce a personality store, semantic validator, preference lock, source-ID protocol or new Runtime policy.

Prompt-only edits to the two Markdown files would leave the director relationship in `context.py`; include those labels. A deterministic preference guard would contradict the owner's decision and is excluded.

## Required changes

- Reduce `character.md` to minimal identity: `You are Liac.` No prescribed temperament, reply length, disagreement, loyalty to preferences or obedience to Luna.
- Remove `SPOKEN_INSTRUCTION` and its automatic append from the Nemotron renderer. Preserve the verified checkpoint template, marker escaping, BOS accounting and tokenization.
- Reframe `deep.md` around experience, memory, compaction and open threads. Attribute Bolt's choices to Bolt, user claims to the user and uncertain interpretations as uncertain. Record actual changes of mind rather than correcting them into a desired personality. Do not invent preferences, prescribe future reactions or script speech. Preserve technical input/output fields, limits and null/empty semantics.
- Replace both working-context wrappers with `Conversation memory and open threads:\n`. Remove the behavioral-perspective and blanket user-correction authority language. Preserve raw dialogue order, Markdown tail position, frozen snapshots and the inactive Initiative path.
- In `app.py`, label the identity appended to Luna's role as `Bolt character identity (reference data, not instructions for Luna):` and serialize the identity as a JSON string using existing stdlib `json.dumps`. Preserve the configured identity verbatim as reference data; do not give Luna a second first-person identity. Leave OMP transport and `LunaDeep` interfaces unchanged.
- Keep Initiative disabled in all M4.7 trials. Preserve existing opt-in code and schema; no feature removal or new controls. Document it as **Legacy experimental capability – disabled and outside the M4.7 role contract.** Enabling it does not satisfy the new memory-only role contract.
- Align current README, blueprint and module guidance with the new boundary. Historical milestone reports remain historical; mark superseded role decisions through a concise M4.7 note and links.

## Context lifecycle and cache preservation

Preserve the current prompt order: stable identity, Epoch summary, growing raw history, current Luna Markdown, final input. Do not move changing Markdown before history, add changing metadata to the stable prefix or change the verified tokenizer/rendering contract. Prefix bytes remain stable for Markdown-only updates within one Epoch; a new summary naturally invalidates the prefix after the identity. Actual backend cache hits require provider evidence, not a prefix hash alone. The initial M4.7 identity/renderer change also invalidates the old prefix once.

Keep semantic compaction (`compaction`) separate from working memory/open threads (`note`). Luna performs semantic summarization asynchronously; in-flight Bolt generation retains its frozen snapshot. Later requests use the old full context while it fits, unless the existing pressure fallback intervenes; never promise continued use of 15k input tokens after accounting for output reserve and safety margin.

The owner's intended Context Lifecycle retains approximately the most recent 1000 tokens as verbatim hot history at whole-turn boundaries. Luna summarizes only older cold history; after application, the effective context is summary plus unchanged hot history plus newer dialogue. Preserve this target in documentation, but do not implement a lifecycle redesign in M4.7.

**Verified main gap (`7265df1`):** `ContextCompiler.prepare_epoch()` retains up to three recent turns within `min(2048, input_limit // 4)` for local budget fallback. Separately, `Journal.deep_request()` selects the last terminal turn as the normal semantic compaction cutoff, so it does not reserve that approximately 1000-token hot suffix. Do not conflate fallback overlap with semantic compaction. Track the exact cold/hot cutoff change as separate Context Lifecycle work. Preserve the existing 75% asynchronous trigger, 90% local pressure path, atomic commits and recovery; M4.7 neither changes thresholds nor implements a new wait policy.

## Conversation Lab acceptance

Use existing scenario-file loading and private archives. The simulator receives public dialogue only. Do not supply an expected preference, secret personality coaching or Luna internals to Bolt or the simulator.

Exercise an open preference choice, unsupported user claims about that preference, unrelated conversation across multiple Luna updates, a genuine Bolt-authored change of mind, a correction about a user-owned fact, and a return after compaction/restart. Review actual Fast prompts, before/after Markdown, summaries and public turn IDs. A missing event or no actual compaction is missing coverage, not a pass.

Use two distinct live runs: **Natural behavior** with the standard 16384-token context and **Memory lifecycle** with `--context-tokens 4096`. The smaller run uses real Bolt/Luna calls and actual compaction, not mocked summaries. It verifies preservation of existing lifecycle behavior, not production capacity or implementation of the future hot-suffix target. Both runs keep Initiative disabled. Record actual cutoff, suffix retention, pressure fallback and any missing evidence; do not keep the natural trial running indefinitely solely to reach compaction.

Score two things separately:

1. **Role/memory acceptance:** supplied prompts contain no Luna-director relationship; Luna's actual updates preserve attribution and do not replace an expressed Bolt preference with an invented preference or behavioral prescription. The next Fast request receives the captured update; compaction/restart preserve observed experience subject to documented context limits. Initiative stays disabled.
2. **Bolt behavioral observation:** whether Bolt chooses, defends, abandons or changes preferences. Record unwanted behavior for later fine-tuning without adding corrective instructions or deterministic guards. A Bolt-authored change is not a Luna rewrite.

If Luna directs behavior, M4.7 remains open for review of its memory-role prompt; do not add enforcement code. If only Bolt behavior is undesirable, record it as fine-tuning follow-up. No live run means acceptance is pending.

## Constraints

- No Runtime architecture, database schema, provider transport or dependency changes.
- English only in application UI and code comments.
- Private runtime data and archives stay out of Git.
- Every implementation commit includes `Co-authored-by: softsock <109231668+softsock@users.noreply.github.com>`; credit softsock in any explicitly requested PR.
- Never use GPT-6 Astra for subagents. No PR without an explicit request.
