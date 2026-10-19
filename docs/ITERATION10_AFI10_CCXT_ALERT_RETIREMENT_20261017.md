# Iteration 10 AFI10: retire the unused CCXT live-task monitor

- Base: AFI `dev` at `c53beefb38ac37555ea39aa979d0f7ff7d49222d`.
- Scope: remove the uncalled `LiveTradingService` CCXT/Cerebro runner and its dedicated tests; stop constructing it from `MonitoringService`; report retained legacy `live_task_id` account/position alert metrics as unavailable (`None`) rather than synthetic zero; update the live-trading guide. Persisted `AlertRule` rows, paper/backtest monitoring and offline research are unchanged.
- Plan basis: Iteration 10 P9D requires caller inspection and retirement of `LiveTradingService.submit_live_strategy()` when no active consumer exists. Backend application search found no caller beyond the deleted monitoring dependency; no runtime application reference remains.
- Focused author check: AFI backend `.venv` Python 3.12.10, `PYTHONUTF8=1`, seven selected alert/monitoring selectors, **10 passed**. Ruff on the changed Python paths passed. `git diff --check` passed on the selected paths.
- A wider 62-item neighborhood run had 59 passes and three unrelated failures in version rollback and live-manager/version-service edge tests; none were in this round's selected assertions. No live account, Host, or formal Iteration 10 acceptance is claimed.
- Status: independent static review GO; scoped commit follows.