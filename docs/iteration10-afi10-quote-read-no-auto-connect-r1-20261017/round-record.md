# AFI10 quote-read implicit Gateway startup retirement — R1

- Repository/branch: `D:/source_code/ai-for-investor`, `dev`.
- Source base: `9cfd98b9beece31288e59e45d987e52e0f79114a`.
- Scope: `manager.py`, `quote_service.py`, `test_live_trading_manager.py`, `test_quote_service.py`, and `test_quote_service_market.py` under `src/backend/`.
- Delivery: source commit `cd9185f1d46757d1008d89ee6e39f31a93a21c84` (parent `9cfd98b9beece31288e59e45d987e52e0f79114a`); record finalization is a separate docs-only commit.
- Result: author-local focused checks passed; independent static review returned GO. This is not formal AFI10 acceptance.

Quote reads no longer read MT5 credentials, create/restore the legacy live-trading manager, or connect an MT5 Gateway as a side effect. QuoteService consults only an already-existing manager, so an explicitly connected Gateway can continue to supply legacy quotes. Explicit manual connect/disconnect routes and manager operations remain available; their obsolete callbacks that toggled quote-page auto-connect state are removed. Tests cover a quote read with no manager creation or Gateway connect, and manual connect/disconnect without a QuoteService side effect.

Author checks, run from `src/backend` with the repository `.venv`, `PYTHONUTF8=1`, plugin autoload disabled, and `pytest_asyncio.plugin` explicitly loaded:

- `tests/test_quote_service.py tests/test_quote_service_market.py`: 39 passed, two existing unknown-`timeout` pytest configuration warnings.
- `tests/test_live_trading_manager.py -k 'gateway_does_not_trigger_quote_service or disconnect_gateway_removes_persisted_manual_gateway or connect_gateway_returns_error_result_when_manual_service_raises'`: 4 passed, 85 deselected, two existing unknown-`timeout` warnings.
- Ruff on the five scoped files, `py_compile` on those files, and CRLF-aware `git diff --check` on the scoped paths passed.

The first test invocation omitted `pytest_asyncio.plugin`; pytest reported async-fixture setup errors. That invocation is not counted as acceptance. The same quote test command was then run with the plugin explicitly loaded and passed as reported above.

Evidence is local unit-test/source evidence only. No live Host, venue, account, installation, or formal acceptance was performed. Legacy Gateway/raw-ZMQ quote paths remain for explicitly connected and unconfigured routes; this round removes only implicit quote-read startup. History consumer support is recorded separately in `iteration10-afi10-history-consumer-r1-20261017`.
