# Minds

Keep model adapters independent of SQLite, Runtime and the CLI. Keep
`character.md` as the authored identity. Preserve complete tool call/result
pairs in replay. Treat stream previews as provisional and require a completed
tool decision. Cancellation must stop the owned stream. Keep request content,
credentials and reasoning out of diagnostics. Fake checks establish behavior
of the local runtime. Use a separate live check for provider claims.
