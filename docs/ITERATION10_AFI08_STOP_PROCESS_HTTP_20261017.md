# AFI08 STOP_PROCESS HTTP round — 2026-10-17

Repository: `D:/source_code/ai-for-investor`, branch `dev`. This round is based on `b595f4c6e3e7afb9166911b54bf63350914de870` and delivers only the exact STOP_PROCESS route, selector/helper, focused tests, and this record. The `strategy_reduction` and `risk_policy` router registrations are separate concurrent hunks and are excluded from this round.

Selected paths: `src/backend/app/api/strategy_process_stop.py`, the single `strategy_process_stop` registration in `src/backend/app/api/router.py`, `src/backend/app/services/live_trading/strategy_process_stop.py`, `src/backend/tests/test_strategy_process_stop.py`, and `src/backend/tests/integration/test_strategy_process_stop_http_integration.py`.

The bodyless authenticated route accepts one manager-owned instance ID and an idempotency key. It resolves the current trusted service-strategy run and unique exact `STOP_NEW` grant from server state, fences new writes, and only then asks the manager to gracefully stop that exact child. Unknown or rejected owner results retain the process. A successful receipt confirms process exit and runtime/subscription release only; open orders remain `left_open_unverified` and positions remain `unobserved`.

Acceptance: the five focused unit/integration nodes passed together (5 unit + 1 HTTP/Host/strategy-child integration) on the AFI Python 3.12.10 virtual environment, with one expected Windows pyzmq Proactor selector warning. After the separate manager live-profile guard commit, the affected HTTP integration node passed again. Ruff passed for the owned code and tests. Independent static review returned GO for the selector, route, and exact router registration row.

Evidence is local synthetic owner/ServiceHost/process integration only. It does not establish real provider, account, order cancellation, position flattening, or formal AFI08 acceptance.
