# AC11 numerator, as-of 2026-11-07T19:02Z

Same instrument, same `--since 2026-11-05T14:00:00+00:00`, same definition; the only change is
that the census was re-run on the current armed set (1048, after the 2026-11-06 queue-A
deactivation) instead of the pre-deactivation 1098-row census.

- AC11_RUNTIME_EVIDENCED = 318 / 1048
- outcome totals: {"completed_and_grew": 318, "completed_no_delta": 109, "failed_only": 20, "not_run": 601}
- previous comparable reading: 168/1048 at 2026-11-06T15:36Z

The numerator is an INPUT to the AC11 disposition, not a disposition: it proves the task bound
its parameters and wrote rows, not that a human reviewed it. `assigned` remains 0 until the
owner signs the review ledger.
