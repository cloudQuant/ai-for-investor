# AFI10 service-v2 chart history consumer — R1

- Repository: `D:/source_code/ai-for-investor`, branch `dev`.
- Parent at final source review: `7640b6466e88b310947e6d6be5656f3e681afa7a`; the exact reviewed pins are:
  - `app/api/quote.py` 6,815 B / `9af0c7c3f154bdfd4ef678207508d4bce319b5418dc2c94313cef6ee70261ce8`
  - `app/schemas/quote.py` 7,241 B / `cfea4f2ac9b5d702399a153fa3f5958704b815cf5ab9ab60ea2c9e0200b63b38`
  - `app/services/quote/service_market.py` 43,238 B / `9ef298b760a4a8fc703e3862798c13e517eb08127802e35b3a01424ad3000ddb`
  - `app/services/quote_service.py` 64,682 B / `bb9ba97101213b49d1a6b1094e2305a6de10e3ecc94dda716a0136c1fde8b67f`
  - `tests/test_quote_service_market.py` 38,382 B / `764557121f7aa7ee9b506901d2841c869ea0055a74fb4e649ae2732321ee510d`
  - `tests/integration/test_quote_history_service_market_operator_host_integration.py` 19,930 B / `75800e78eed90001012eda8206485d89cfc57e610604e0b4d1df06a49a6b2678`
- Scope: route an exact JWT-subject/source/symbol/timeframe OKX bar binding through the existing SDK `ServiceMarketClient.history` contract. History-only profiles request `market.history` and do not subscribe; configured history failures return finite errors without using the legacy chart channel. Unconfigured chart routes keep the prior `get_bars` behavior. The quote path does not start the trusted operator; operator lifecycle remains explicitly controlled through the owner-authorized operator API.
- SDK dependency: parent `bt_api_py` dev commit `04e32632d91aaf1ba4c6140abf154b9e249285cd`, Gateway `c2886f60b72544c5690248c450bb2bddb6660c61`, OKX `259208d6a1cf3301456603e8a5290052c9ec80b2`.
- Acceptance: author focused quote-market tests passed 23/23. The new HTTP→operator→Gateway Host→CURVE client integration passed 1/1 with one existing Windows ZMQ Proactor warning. Ruff, `py_compile`, and CRLF-aware `git diff --check` passed. Independent reviewer returned `GO_STATIC` on the exact six AFI pins and did not rerun tests.
- Evidence limits: local synthetic-provider composition only. The operator profile/auth directory is injected by the integration fixture; this does not establish real OKX WSS, real account behavior, installed-wheel QA, or formal AFI10 acceptance.
- Committed paths: `src/backend/app/api/quote.py`, `src/backend/app/schemas/quote.py`, `src/backend/app/services/quote/service_market.py`, `src/backend/app/services/quote_service.py`, `src/backend/tests/test_quote_service_market.py`, and `src/backend/tests/integration/test_quote_history_service_market_operator_host_integration.py`.
- Commit: pending scoped delivery.
