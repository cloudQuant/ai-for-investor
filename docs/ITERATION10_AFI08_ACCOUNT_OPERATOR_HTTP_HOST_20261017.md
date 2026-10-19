# Iteration10 AFI08 account operator HTTP Host acceptance

Repository: ai-for-investor, existing dev. Base: 7498010ee10c9764d1e86130e91ee67476a8a6fa.

Root ran `test_owner_http_start_stop_controls_only_granted_account_host` once against fixed committed AFI and SDK/package source. Result: 1 passed, pytest exit 0, 4.91 seconds; 2,236 source hashes and AFI HEAD unchanged, empty stderr. One known PyZMQ Windows Proactor selector-thread warning was recorded. Evidence: `D:/temp/afi08-gateway-operator-http-root-20261017-r2/` (exact spec, JUnit, stdout/stderr, source before/after and result).

The test calls the existing HTTP status/start/stop routes with real ServiceGatewayOperatorControl, GatewayOperatorApplication, GatewayOperatorDeployment and the local Gateway ServiceHost. A synthetic local account provider is the only provider leaf. Foreign owner and ungranted-account requests return 403 before Host construction. The granted start returns a ready account session; stop and final status report closed/not-ready. Assertions confirm provider close exactly once, all provider operations on the owner thread, thread exit, zero uncertain providers and closed control.

Authentication boundary: require_persisted_owner_scope is overridden with synthetic persisted subjects. This proves route/account authorization and the real local owner lifecycle, not JWT/DB authentication or external account access. It supplies the account-management slice of AFI08, not full AFI08 PASS. The first collection attempt had a package-parent PYTHONPATH error before tests; it is preserved. Corrected collection ran once before the accepted Root body run.

Scope: new integration test and this record only; no production change.
