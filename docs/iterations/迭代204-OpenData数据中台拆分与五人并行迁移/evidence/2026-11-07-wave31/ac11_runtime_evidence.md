# AC11 runtime evidence (read-only)

- as of (UTC): 2026-11-07T19:02:46+00:00
- evidence window starts: 2026-11-05T14:00:00+00:00 UTC
- population: 1048 census tasks (armed_tasks in census scope: 1048; post-retirement (census generated at/after the 2026-11-06T13:47:56Z ruling))
- database: select_only/ak_task_executions@ai_for_investor (session_read_only)

## Family x outcome matrix
| family | completed_and_grew | completed_no_delta | failed_only | not_run |
|---|---|---|---|---|
| accepts_var_kwargs | 279 | 64 | 7 | 536 |
| binds | 39 | 45 | 6 | 65 |
| unexpected_param | 0 | 0 | 7 | 0 |
| **total** | 318 | 109 | 20 | 601 |

## AC11 numerator
- AC11_RUNTIME_EVIDENCED / population = 318 / 1048 (denominator is the population actually read from the census)
- definition: census task with at least one ak_task_executions row in the window with status='completed' AND rows_after > rows_before

## Assigned (NOT computed here)
- assigned: not computed here — the human-reviewed `assigned` sign-off count comes from the AC11 disposition ledger; runtime evidence is an input to disposition, not a disposition

## Caveats
- runtime_evidenced != assigned: no human sign-off is implied by a growing run
- the number moves as the collector runs; only valid at as_of_utc
- reads ak_task_executions only; the scheduler's host-local last/next_execution_at columns (PR #306) are never compared against this UTC window
- executions before the repair marker ran the old collector and are excluded
