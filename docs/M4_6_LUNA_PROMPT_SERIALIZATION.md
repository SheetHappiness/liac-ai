# M4.6 — Luna Prompt Serialization

Luna receives a semantic JSON projection while the authoritative DeepRequest,
SQLite, cursor, OMP lifecycle and schema-v3 response are unchanged. The original
request remains in `deep.started` technical traces; `deep.prompt` and Conversation
Lab show the actual projected prompt. The local wall clock and timezone are
included, as are original event occurrence times, not recording times.

The projection merges repeated event instances across snapshot, new observations
and compaction by event identity. It omits IDs, sequence numbers, revisions,
recording times, envelopes and repeated JSON payloads. Compaction boundaries
refer to counts within the ordered arrays; recovery includes the meaningful prior
Epoch and all canonical dialogue supplied by Journal. Journal's existing canonical
compaction range contains user messages and completed replies, while cancellation,
failure and initiative events are available when present in new observations.

## Verification

A single in-memory SQLite Journal generated each request; each pair below compares
`canonical_json(asdict(request))` with the new projection of the same request.
Values are UTF-8 bytes, not model tokens; IDs and timestamps vary between runs.

| Request | Old bytes | New bytes | Reduction |
| --- | ---: | ---: | ---: |
| Ordinary dialogue | 1,999 | 464 | 76.8% |
| Cancellation and pending initiative | 3,203 | 922 | 71.2% |
| Compaction | 4,394 | 970 | 77.9% |
| Epoch recovery | 2,520 | 624 | 75.2% |

51 focused Luna, Deep, OMP, tracing and Lab recovery tests passed. The baseline
full suite ran 113 tests with three pre-existing errors: a context budget test,
a desktop test referencing a missing `MainWindow.context`, and an LM Studio test
expecting outdated prompt text. No live inference or actual OMP input-token usage
was measured. OMP retains its existing session messages, including prior prompts
and responses, so these request-byte reductions do not quantify total provider
input or establish KV-cache reuse.
