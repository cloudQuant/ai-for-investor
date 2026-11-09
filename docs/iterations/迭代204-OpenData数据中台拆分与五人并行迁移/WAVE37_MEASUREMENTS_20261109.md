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

- AC11 numerator continued to rise as converted tasks ran: 513 (15:55Z) → 516 (16:00Z) → 521 (16:18Z)
  → the figure in §8 of this update file's commit message; see the artifact below for the exact
  final reading.
- `etf_minute_hist_em` (task 390) completed with a 150-second timeout (45 s was too short); two other
  endpoints (`macro_china_nbs_region`, `foreign_futures_history_em`) still time out at 150 s and stay
  source-side failures.
- AC14: 45/48 consecutive hourly slots at 16:22Z; 48th completes just after 19:00Z, reading scheduled
  at 19:06Z.
- Bond timer batch 16:09Z: 5/5 `verified_source_sequence`, `history_completeness=not_certified`
  (listing boundary unknown) — reconciled, not certified.
