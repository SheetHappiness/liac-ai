# Verification

Use standard-library unittest and temporary SQLite files. Close SQLite
connections explicitly. Pin batch order, timing and provenance, atomic
deduplication, serialized turns, cancellation, restart recovery and tool
replay. Run the real CLI for milestone smoke checks and report fake evidence
separately from live provider evidence.
