# Luna Prompt Serialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Compact Luna's input while retaining available evidence and temporal context.

**Architecture:** Project immutable DeepRequest data at the Luna boundary; merge overlapping canonical events by identity into ordered history and new observations. Preserve the original request, runtime lifecycle and tracing.

**Tech Stack:** Python 3.12+, stdlib unittest, existing OMP transport.

**Spec:** User's M4.6 request in this chat; existing architecture in `docs/PROJECT_BLUEPRINT.md` and `docs/M4_5_RUNTIME_SIMPLIFICATION.md`.

## Global Constraints

- Preserve schema-v3 output, SQLite, cursor, cancellation and OMP lifecycle.
- Preserve event occurrence times and local current time with timezone; omit recording timestamps and technical identifiers.
- Do not silently truncate canonical evidence or duplicate dialogue.
- One implementation commit; no push or PR; credit softsock.

## Review Focus

- Recovery across a degraded epoch retains both meaningful prior Epoch and complete supplied history.
- Cancelled and failed replies preserve outcome and reason, including autonomous speech.
- Repeated overlapping event inputs occur only once, with exact Unicode and chronological order.
- Pending intention retains its text and deadline even when initiative is disabled.
- Compaction boundaries distinguish covered events from later observations without repeating text.

### Task 1: Projection and documentation

**Files:** Modify `src/vtuber/minds/luna.py`, `src/vtuber/minds/deep.md`; test `tests/test_luna.py`.

**Interfaces:** `render_request(request: DeepRequest) -> str` returns compact JSON; `parse_result` remains unchanged.

- [x] Add tests for the five review cases, timestamps, and unchanged authoritative request.
- [x] Run focused tests and verify they fail on the old serialization.
- [x] Implement semantic projection, chronological deduplication, Epoch and compaction boundary handling.
- [x] Explain fields and compaction boundaries in `deep.md`.
- [x] Run focused tests and compare old/new UTF-8 byte sizes using the same captured requests.
- [x] Verify trace/Lab availability, run relevant existing checks, inspect diff and commit once with the required co-author.
