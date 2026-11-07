# AC13 verdict, 2026-11-07T18:59:57Z

Instrument: `ac13_verdict.py` (read-only; `SET SESSION TRANSACTION READ ONLY`).
Cohort: the 50 tasks the #284 census classified `script_file_absent` (queue A), deactivated
`is_active=0` at 2026-11-06T13:47:56Z by owner ruling.

## What the numbers say

- All 50 are still `is_active=0` (50/50) — the deactivation itself held.
- **48 executions landed after deactivation**, on 46 distinct tasks, every one `failed`:
  - 2026-11-06 22:30–22:45Z (CST 11-07 06:30–06:45): 41 rows
  - 2026-11-07 00:35–01:43Z (CST 11-07 08:35–09:43): 31 rows
  - two tasks (1095, 1096) fired twice.
- Nothing since 01:43Z, but that is not evidence of a fix: those crons are fixed-time CST
  slots, and the next ones are 11-07 22:30Z and 11-08 00:35Z.
- Baseline for comparison: 798 executions over 2026-10-20..11-06 11:45Z (323 completed / 475 failed),
  so the cohort was genuinely firing before.

**Verdict: deactivation alone did not stop the ghost tasks.** The running code at the time
registered their APScheduler jobs at startup and never consulted `is_active` when firing.
PR #306 (merged) fixes exactly that; it was deployed at 2026-11-07T17:22:14Z (`ai-for-investor.service`
`ExecMainStartTimestamp`). The first slots that fall entirely after that restart are
2026-11-07T22:30Z and 2026-11-08T00:35Z — those decide whether #306 closes AC13.

## Clock base of the window (checked, not assumed)

`ak_task_executions.created_at`/`start_time` are UTC: the newest `triggered_by='scheduler'`
row reads 2026-11-07 19:03 while `UTC_TIMESTAMP()` was 19:04:27 (DB `NOW()` was 11-08 03:04 CST).
A CST reading would have put the newest row 8 hours in the future.
