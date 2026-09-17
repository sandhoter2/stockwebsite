# Agent instructions

Before any work on Telegram channel parsing (regexes, `signals.py`, per-channel
tests, `parse_signals`), read **`docs/AGENT_HANDOFF.md`** and the target channel's
`Channel.style_notes`. Seven of 76 channels already have specialist work recorded
there; re-deriving it from scratch is the single biggest waste in this repo
(observed: 132k tokens on a channel that needed no change, 307k on one that did).

Cheap-path rules, in short — full text and the reasoning in §3 of the handoff doc:

1. Triage before specializing: §2 buckets the remaining channels into
   parser-blind (31), generic-already-works (24), and skip (11 near-empty or dead).
   Sample 5 messages (§5 SQL) before concluding `0 trades` means a broken parser.
2. Do not read `signals.py` end to end (654 lines). The map in §3 Rule 1 of the
   handoff doc gives the six insertion points; read ~40 lines around yours plus the
   comment blocks above them, which are prior agents' KT inline.
3. Do not run the 84-test suite (29s) unless `signals.py`'s sha256 differs from the
   anchor recorded in the handoff doc, or you touched a shared `RE_*`. Otherwise run
   only your own test labels.
4. Do not re-parse all 76 channels to check one: `manage.py parse_signals --channel <id>`.
   And until the §7 defect in the handoff doc is fixed, never run `parse_signals`
   unscoped at all — each full pass re-books the same rupee profit onto another
   Options Train / Stock Thunder leg and inflates realized (₹53,425 → ₹210,765 over
   four passes). Use the §7 fingerprint diff for cross-channel checks instead.
5. Batch lookalike publishers; never double-spend on the duplicate peers listed in §5.
6. When you finish, append your row to the handoff doc's §1 board and its §6 run log,
   with your worktree path and commit sha, in the same commit as the code change.

`db.sqlite3` is gitignored, so a parse run has no revert path — copy it aside first.
