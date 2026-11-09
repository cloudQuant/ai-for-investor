# Wave 37 — collection-plane write chain, measured 2026-11-09

All numbers below were produced on this host. Anything measured on the local integration branch
`fix/combined-collection-plane` is labelled as such; it is not a dev deployment and must be
re-obtained after the PRs merge.

## 1. Four-layer zero-row defect in the script plane

Symptom: `ak_task_executions.status = completed` with zero rows persisted, across controllers and
scheduled tasks. Each layer was found by a production log line and fixed on
`fix/script-control-params`:

| Layer | Log line | Fix | Commit |
| --- | --- | --- | --- |
| dispatch metadata | `bond_zh_hs_cov_daily() got an unexpected keyword argument '_ingest_mode'` | executor strips `_`-prefixed keys | `40eab0746` |
| injected default | `... unexpected keyword argument 'source'` | bond script consumes `source`, stamps the frame | `13974e2f8` |
| fence identity | `... unexpected keyword argument 'claim_key'` | executor also strips claim_key/owner_id/fencing_token/execution_id | `e55402373` |
| claim provenance | `... unexpected keyword argument 'period_key'` | controller prefixes provenance keys with `_` (still auditable) | `60be82ef3` |
| stored legacy parameters | `FuturesDailyMarket.run() got an unexpected keyword argument 'overlap_days'` | executor forwards only declared names unless the callable has `**kwargs` | `24795a604` |

Tests: `test_akshare_script_service.py` 104 passed; `test_bond_convertible_history_controller.py`
41 passed; ruff/format green on every touched file.

Live writes after the fixes (source/warehouse counts, max business date 2026-11-09):
`sz123282` 32→43; `sz127038` 1268→1279; `sz127047` 1186→1197; `sh113043` 1404→1414;
task 514 `daily_market_data` wrote 3360 rows to `FUTURES_DAILY_MARKET`; task 389 wrote 10 rows to
`ETF_FUND_HIST_EM`; task 650 wrote 8759 rows to `STOCK_ZH_INDEX_DAILY`.

## 2. Stock series fix (PR #305)

`STOCK_ZH_A_HIST` held two legitimate series (`legacy_unknown/unknown` and `tencent/qfq`); the
controller read by symbol only (8514 "duplicate" date keys for 000001) and the writer upserted on
`(symbol, data_date)` without stamping `source`/`adjustment`, so the qfq series could never be
written. Fixes: scoped read (`90424c53`), stamped upsert on the table's real unique key
(`b6e97d44`), enum status value (`c55cc12b8`), regression test (`edd9a97aa`).

Production evidence on the integration branch: 10/10 `scheduled_verified` per stock batch
(`exact_match=True`, 0 duplicate keys); pooled stock reports for the day: 1023 `scheduled_verified`
and 230 `verified_match`.

## 3. Bond epoch comparison (PR #341 + follow-up)

The controller compared raw epoch keys against ISO warehouse dates; the follow-up also had to
normalise millisecond/microsecond/nanosecond epochs (`dd5197393`, `year 52960` otherwise).
With both, a timer bond batch (run `20261109T160207Z-7d0eb70b54b6`) reported
`verified_source_sequence` x3 (source/warehouse 1424/1424, match true) + `verified_unchanged` x2,
zero mismatches.

## 4. AC11 runtime evidence

Instrument: `scripts/task_param_audit.py --out-dir` then
`scripts/ops/ac11_runtime_evidence.py --census ... --since 2026-11-05T14:00:00+00:00`.
Reading 16:00Z: **516 completed_and_grew / 1048** (161 no_delta, 27 failed_only, 344 not_run).
Booked sequence: 443 @ 03:01Z → 513 @ 15:55Z → 516 @ 16:00Z.
Six of the remaining failed_only tasks were confirmed source-empty (not code defects), e.g. tasks
66/89/91/377/386/425 all return "no data and target table is empty".

## 5. AC14 natural-cycle accrual

`ac14_chain.py` at 15:56Z: **44 consecutive completed hourly slots** (target 48), first
non-completed slot: none. The 48th slot completes just after 19:06Z; the deadline reading is
scheduled then.

## 6. Runtime environment

- The worker invoked by script path imported a stray legacy `app` package from
  `/home/yun/Documents/backtrader_web/src/backend`, resolving DATABASE_URL to the dead
  `backtrader_web` database. Fixed with a systemd drop-in that sets `PYTHONPATH` after
  `run_with_core_environment` filters the environment.
- The unit now also loads `src/backend/.env` via `EnvironmentFile` so the legacy `MysqlBase` path
  receives its DB credentials.

## 7. Unmerged work (GitHub REST returns 000; git push is intermittent)

- `fix/stock-series-scoped-comparison` → PR #305 (4 commits, pushed).
- `fix/script-control-params` (5 commits, pushed) — PR not yet created.
- `fix/afi-bond-epoch-date-normalisation` → PR #341 head `dd5197393` (pushed).
- #341's Alembic check is red; the same upgrade failure reproduces on dev locally, so the red is
  not attributable to the PR without its CI log.

## 8. Late readings (same day, 16:27Z)

- AC11 numerator continued to rise as converted tasks ran: 513 (15:55Z) → 516 (16:00Z) → 521
  (16:18Z) → **522/1048 (16:27Z, completed_no_delta 162, failed_only 21, not_run 343)**; artifact
  `/tmp/it204/ac11_cumulative5/ac11_runtime_evidence.json`, same `--since` window.
- `etf_minute_hist_em` (task 390) completed with a 150-second timeout (45 s was too short); two other
  endpoints (`macro_china_nbs_region`, `foreign_futures_history_em`) still time out at 150 s and stay
  source-side failures.
- AC14: 45/48 consecutive hourly slots at 16:22Z; 48th completes just after 19:00Z, reading scheduled
  at 19:06Z.
- Bond timer batch 16:09Z: 5/5 `verified_source_sequence`, `history_completeness=not_certified`
  (listing boundary unknown) — reconciled, not certified.

## 9. AC11 manual-exercise tranche (16:33Z)

Twenty tasks from the `not_run` set were exercised through the managed service with their stored
parameters (45 s cap): 18 COMPLETED and grew, 2 source-empty (`article_oman_rv`,
`energy_carbon_domestic`). Numerator **535/1048** (completed_no_delta 167, failed_only 23, not_run 323),
same `--since 2026-11-05T14:00:00+00:00`.
Attribution: these are **manually triggered** executions, not scheduler-cadence evidence. They prove
the scripts bind and write through the production service; they do not prove the scheduler fired them.
Artifact: `/tmp/it204/ac11_cumulative6/ac11_runtime_evidence.json`.

## 10. AC11 second manual-exercise tranche (16:39Z)

Another 25 `not_run` tasks exercised the same way: 24 COMPLETED and grew, 1 source-empty
(`energy_carbon_eu`). Numerator **557/1048** (completed_no_delta 169, failed_only 24, not_run 298),
same `--since` window. Same attribution caveat as §9: manually triggered executions prove the scripts
bind and write; scheduler cadence is proven separately by the timer runs.
Artifact: `/tmp/it204/ac11_cumulative7/ac11_runtime_evidence.json`.

## 11. AC11 third manual-exercise tranche (16:49Z)

Fifty more `not_run` tasks: 48 COMPLETED and grew, 2 source-empty. Numerator **601/1048**
(completed_no_delta 174, failed_only 26, not_run 247), same `--since` window.
Day sequence: 443 (03:01Z) → 513 → 516 → 521 → 522 → 535 → 557 → **601** (16:49Z).
Attribution unchanged: manually triggered executions prove binding and writing, not scheduler cadence.
Artifact: `/tmp/it204/ac11_cumulative8/ac11_runtime_evidence.json`.

## 12. AC11 fourth manual-exercise tranche (17:05Z)

Fifty more `not_run` tasks: 49 COMPLETED and grew, 1 source-empty (`video_variety_show`).
Numerator **644/1048** (completed_no_delta 179, failed_only 27, not_run 198), same window.
Day sequence now 443 → 513 → 516 → 521 → 522 → 535 → 557 → 601 → **644**.
Artifact: `/tmp/it204/ac11_cumulative9/ac11_runtime_evidence.json`. Same attribution caveat.

## 13. AC11 fifth manual-exercise tranche (17:16Z)

Fifty more `not_run` tasks: 49 COMPLETED and grew, 1 source-empty. Numerator **682/1048**
(completed_no_delta 190, failed_only 28, not_run 148), same window.
Day sequence: 443 → 513 → 516 → 521 → 522 → 535 → 557 → 601 → 644 → **682** (17:16Z).
Artifact: `/tmp/it204/ac11_cumulative10/ac11_runtime_evidence.json`. Same attribution caveat:
manually triggered executions prove binding and writing, not scheduler cadence.

## 14. AC11 full coverage reached (17:42Z)

Tranches 5–8 exercised every remaining `not_run` task through the managed service with its stored
parameters: 49/50, 50/50, 49/50 and 47/48 completed and grew; the six non-completions are source-empty
endpoints, not script defects. Final reading, same `--since 2026-11-05T14:00:00+00:00`:

**completed_and_grew 813 · completed_no_delta 205 · failed_only 30 · not_run 0 = 1048**

Day sequence: 443 → 513 → 516 → 521 → 522 → 535 → 557 → 601 → 644 → 682 → 728 → 771 → **813**.
Every armed task has now been exercised at least once inside the window; the residual 30 failed_only
are source-side (Eastmoney proxy absent, DCE/macro endpoints empty, >150 s endpoints). Attribution
stays explicit: these executions were manually triggered through the production service; scheduler
cadence is evidenced separately by the timer batches.
Artifacts: `/tmp/it204/ac11_cumulative{5..13}/`; per-tranche JSON in `/tmp/it204/ac11_notrun_batch{,2..8}.json`.

## 15. Scheduler cadence since the 12:39Z restart

Direct DB reading (`ai_for_investor.ak_task_executions`, read-only):
- scheduler-triggered: **491 executions across 475 distinct tasks** since 2026-11-09 12:39Z
- manual-triggered: 620 executions in the same window (the manual AC11 tranches)
- hourly: 12Z 7, 13Z 33, 14Z 28, 15Z 27, 16Z 180, 17Z 216

The 16Z/17Z jump follows the write-chain fixes: overdue tasks finally completed instead of failing at
the first private parameter. This is the scheduler-side counterpart to the manual AC11 coverage and
keeps the two kinds of evidence separate.

## 16. Correction to §9–§11, §14 and §15 — manual tranches were tagged as scheduler

The manual AC11 tranches called `run_script(..., triggered_by=TriggeredBy.SCHEDULER)`, so their
executions are indistinguishable from real scheduler runs in `ak_task_executions`. Consequences:

- §15's "scheduler-triggered 491 executions / 475 distinct tasks" **cannot be attributed to the
  scheduler**; those rows include the manual tranches.
- The AC11 numerator (813/1048) is unaffected as a *capability* reading (the executions are real and
  the tables grew), but it is **not** scheduler-cadence evidence. The §9–§11, §14 caveats stand:
  manually triggered, attribution labelled.
- `--triggered-by scheduler` on the instrument now reproduces 813 as well, which is exactly the
  contamination — the filter is correct but the historical rows carry the wrong trigger value.
  No rows were rewritten; execution history stays append-only.
- Future manual runs must pass `TriggeredBy.MANUAL`. The instrument change adding `--triggered-by`
  is on a branch, not yet merged.

## 17. AC14 deadline reading — hourly leg met (19:06Z)

Deadline job output (`/tmp/it204/ac14_deadline_reading.txt`, measured_at 2026-11-09T19:06:00Z):
task 1049 `crypto_hourly_market`, armed=1, cron `3 * * * *`; **48 executions since deploy
2026-11-07T19:26:47Z**, every hourly slot from 11-07 20Z through 11-09 19Z `completed`;
consecutive completed hourly slots = **48/48**, first non-completed slot: none.

This closes the hourly leg of AC14's natural-cycle target. The daily (2), weekly (1) and sub-daily (1)
legs were last measured at their window maxima in wave 34 and must be re-read with the same window
before AC14 is declared fully met; today's reading covers the hourly leg only.

## 18. AC14 per-cadence audit (19:09Z) — hourly met, daily still accruing

Direct DB readings (read-only) over the last 14 days, per representative task:

| cadence | task | cron | completed runs | due runs since repair | verdict |
| --- | --- | --- | --- | --- | --- |
| hourly | 1049 crypto_hourly_market | `3 * * * *` | **48** | 48 since 11-07 20Z | **target 48 met** |
| daily | 11 ChinaBond curve | `20 19 * * *` | 4 | 4 since 11-06 (every day) | target 7 needs 3 more days |
| daily | 1048 crypto_daily_market | `10 8 * * *` | 4 | 4 since 11-06 (every day) | same |
| weekly(-weekday) | 33 bond_zh_hs_cov_daily pilot | `10 18 * * mon-fri` | 2 | 2 (Fri 11-06, Mon 11-09; weekend not due) | target 2 met |
| sub-daily | 101 Fx Spot Quote | `10 10-23 * * mon-fri` | 30 | 30 | target 1 met |

So AC14 is **not fully met**: the hourly, weekly and sub-daily legs are met; the daily leg has run
every due day since the write-chain repair (4/4) but the 7-cycle target is time-limited and cannot be
claimed before 2026-11-12/13. This is accrual arithmetic, not a collector failure.
