# Runtime

Keep one owner for the perception loop and one active turn. Journal raw
perceptions and the grouped input in one short transaction before inference.
Keep model work outside SQLite transactions. On orderly shutdown join the
active turn and journal accepted pending input. On restart close unfinished
journaled inputs without repeating the model call. Trace failures must not
affect domain work. Keep provider dependencies in adapters and credentials
outside domain events.
