# AFI10 ServiceMarket close retry — round R1

- Repository: `D:/source_code/ai-for-investor`, branch `dev`.
- Parent before this round: `fc27194e47cbc984431921bda9679c5112ed7e5d`.
- Scope: retain failed ServiceMarket client/runtime owners after uncertain close; allow explicit retry on the same owner thread; reset the `QuoteService` deployment only after cleanup is confirmed. Add focused production-owner and normal FastAPI lifespan tests.
- Source paths: `src/backend/app/services/quote/service_market.py`, `src/backend/tests/test_quote_service_market.py`, and `src/backend/tests/test_service_gateway_operator_lifecycle.py`.
- Independent static review: `GO_STATIC`, reviewer `resume_bt_v3_cpf`; final pins were checked and the SDK runtime's cumulative `cleanup_failures` semantics were explicitly covered. No tests or Host were run by the reviewer.
- Focused owner retry: author-local pytest, `1 passed` in 1.47 s. The test uses the production `ServiceMarketDeployment`, `_ServiceMarketOwner`, and SDK `ServiceClientRuntime` on the owner thread; only the market client and a synthetic transport leaf are injected. It covers client close failure, transport close failure, the SDK's cumulative failure count remaining at one after a successful retry, owner-reference retention, fail-closed market reads, and final reset after cleanup.
- Normal app bootstrap: author-local `TestClient` pytest node passed `1 passed`, with two existing Windows/TestClient warnings. It follows `main_module.app` lifespan through the real `GatewayOperatorApplication`, `GatewayOperatorDeployment`, and `ServiceHost`; the market stream is synthetic. After that run, only the new test's signature wrapping and local import ordering changed. This is local synthetic lifecycle evidence, not live WSS, venue, account, installed-wheel, or formal AFI10 acceptance.
- Static checks: Ruff lint passed for the three source/test paths. CRLF-aware `git diff --check` passed. No full-file formatting rewrite was applied because the formatter reports older unrelated formatting in these files.
- Independent reviewer result and scope: exact three-file pins matched the final candidate; `GO_STATIC`. The review did not run tests or Host.
- Commit: pending Root's scoped commit.
