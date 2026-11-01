# Iteration10 AFI08: approved strategy reduction HTTP route

Scope: add a separate authenticated route for one exact approved target and an operator-owned exact-run deployment setting. The request carries target/approval references and an idempotency key; server authorization resolves the persisted target and configured service identity/scope. The signed target remains CLOSE/reduce-only on its declared NET/ALL dimensions. Requests cannot override trade terms. Partial fills stay partial, UNKNOWN requires review and is replay/query only, and responses do not claim the account or strategy is flat.

Acceptance evidence: AFI backend venv Python 3.12.10 with explicit local SDK source roots ran tests/test_strategy_reduction_control.py: 12 passed in 7.17s. This file has eight test functions, with parameterization accounting for twelve pytest cases. The tests include strict deployment/request parsing, authenticated identity and exact scope binding, persisted target close terms, bounded outcome projection, expiry and no-runtime-on-expiry checks, and a direct asynchronous handler invocation with fakes. No raw JUnit/result artifact was saved. Independent static review returned GO for the pinned candidate. This is author test evidence, not a formal AFI08 pass.

AFI source pins:
- src/backend/app/config.py: 63,035 bytes, SHA-256 873deb3c9a5169f657b0db60eec6f784b709d05dd219214e97341466aa896c1c
- src/backend/app/api/router.py: 9,486 bytes, SHA-256 47b1980f18ad5d4b54c4823cd18286444a16ab7afd54287dff87dce1adaed7aa; this whole-file pin also includes another lane's risk_policy registration, excluded from this scope. Stage only the strategy_reduction router row.
- src/backend/app/api/strategy_reduction.py: 20,426 bytes, SHA-256 42987b22b965e5ca2f7ce733b8c3eb23551872f5df7d5cc3755b2a65b3006cb8
- src/backend/app/services/strategy_reduction_control.py: 19,935 bytes, SHA-256 d9b8fad15e599708481efe8894f733e51d51a097873a6b5d7601ca490e33de77
- src/backend/tests/test_strategy_reduction_control.py: 20,802 bytes, SHA-256 db1a84c549faaf84e45d76acd58f02c3a9211cefc462ceccc0e06e4915ce2ce1

The supporting Execution component is committed in bt_api_execution/dev at fdf53a416f7a7243e987fc46b267fc11ff2272a6. No real HTTP server plus ServiceHost integration or provider/account operation has run. The service-registry owner.reduce SDK wiring remains a separate uncommitted candidate awaiting its own review and index window. No formal AFI08 case closure is claimed.
