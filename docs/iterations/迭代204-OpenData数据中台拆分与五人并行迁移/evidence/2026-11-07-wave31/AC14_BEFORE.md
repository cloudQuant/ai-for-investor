# AC14 before-image: task 1049, 2026-11-06T19:00Z .. 2026-11-07T19:08Z

`ac14_before_after.py` (read-only). Task 1049 is the only armed task that can fire hourly
(`3 * * * *`), so it is AC14's whole population until the fix ships.

- runs: **25** — 24 `failed`, 1 `running` (the 19:03 slot, still inside the 600 s timeout)
- runs with `duration >= 599 s`: **24**
- successes: **0**
- row growth (`rows_after > rows_before`): **0**

That is the pairing anchor: after PR #316 is merged and deployed, the same command with
`--since <deploy timestamp>` must show runs that finish well under 600 s and grow rows. If it does
not, the backfill-before-tail diagnosis was wrong and AC14 stays NOT-PROVEN.
