# AFI10 / MIG01 installed ServiceHost acceptance delivery

Scope: one exact shadow-test postimage and this record only. No source implementation, package metadata, or runtime code is changed by this accepted delivery.

## Frozen source and isolated test

- AFI repository: D:/source_code/ai-for-investor, branch dev, current HEAD d4ad3094775aa47e3284e789c500be7d4f27c8bb.
- Canonical target: src/backend/tests/integration/test_service_strategy_execution_host_integration.py.
- AFI HEAD blob: 23,269 bytes, SHA-256 00e093cfc983bf7f6311f596f292a27597c81eb3224c2f0db6c07cf58e28247e.
- Frozen R3b shadow postimage: 41,356 bytes, SHA-256 23d40befd630e3824854040328a5e5947c9a166f100abe9108a8c37948b3a82a.
- The live canonical checkout file is currently a mixed uncommitted worktree file: 61,210 bytes, SHA-256 a4e2708918821f52b7371ca729c3a17500194b6fede1652e4305c413eb89e0e4. This delivery must apply only the patch below to the AFI HEAD blob; do not stage the live worktree file because it contains unrelated/newer WIP.
- Exact transformation patch: service-host-r3b-sdk55c-accepted-postimage-from-afid4ad.patch, 24813 bytes, SHA-256 af5287faf20aa9db75026677fb4c0d24a4b9a31bf1e96a7104a2677cc8047b30. It was applied in an isolated scratch repository with core.autocrlf=false to the AFI HEAD blob and reproduced the frozen postimage byte-for-byte. The scratch directory was removed. No source checkout file or Git index was changed.

The Root-owned actual run used the unchanged frozen spec service-host-node-r3b-sdk55c-shadow-actual-r1-spec.json (55617 bytes, SHA-256 98800d8a16060d6eeb6c7f506aa24e90b2e5a07afc40820394a939ba6a2c9863) and runner service-host-r3b-sdk55c-shadow-actual-r1-runner.py (3549 bytes, SHA-256 7cbb517b605976d2b41717356167e8b9373595731bea82fc352917ad1d8f3e38). It selected only test_live_manager_runs_service_strategy_order_query_and_graceful_stop; the shadow file contains auxiliary tests that were not run by this node. Result: pytest exit 0, one selected test passed, 199 source pins unchanged, SDK HEAD remained a4edcacdd1f5378412b49d51a5196fe0beeff776. Result pin: 610 bytes / 52e398d8bfc3948610b1f83c7d4a28ccfdd675f83404604e5d94703451f6e2d0. JUnit pin: 415 bytes / af056160e5c6c7e01c55a300dbcf0cc1f80f90e8336d6a7edf6f75f185b19186.

The finite cleanup receipt (489 bytes / 6931b203c594b9b32f13763c6e9a88b5656d91d0158dac10777f17879371c24d) records phase=strategy_stop, normal close true, close reply closed/closed, child return code 0, no forced cleanup, no remaining owner exclusion, and no cleanup error types. Stderr is 434 bytes / 2e1044e036ff7577dc31e3ec9063c9172c4cde9332624f7bba8fb3311af4fe79 and contains the one known PyZMQ warning.

## Installed artifact provenance and limits

This was an isolated Python 3.12.10 venv run with -I -X utf8, system_site_packages=false; the runtime import report records 19 cold-import origins under that venv's site-packages, excluding the live AFI backend, Backtrader checkout, and SDK checkout from sys.path. Origin report pin: 64268 bytes / 89ad1008abb2c216b44a62bcafccaa3e60e9fefcb243b920a98cfe5fe015484a.

- SDK wheel: bt_api_py 0.15.5, built from SDK dev commit 55c05166709aa538f43fb78805085468724d023d; wheel SHA-256 69348eaeff211bf023ac6bc75cbad1d2b00ecf59905f78878b204d13808fa57c.
- AFI wheel: ai_for_investor_backend 0.1.0, built from AFI source commit 94386432b862fa0bfdf858033d95724ef5399169; wheel SHA-256 ae0ed4794ab775e00f9ac64c4b2a124ca7d40c1635714ed5a41d1c668a981fd0.
- Backtrader wheel: backtrader 1.4.0, source commit 4f3e6a1ca3c41c1e5a726d11cce162faec25b140; wheel SHA-256 f48328ebba1d1bd7c259c135d6477e638f0e920c66f1b1ee3ab18f3721745561.
- The two Backtrader test-support files were materialized from that committed source as shadow-only helpers; they were not imported from the live checkout.

The tested runtime is precisely the SDK 55c0516 wheel. Current SDK checkout HEAD is a4edcacdd1f5378412b49d51a5196fe0beeff776; the difference from wheel source includes intervening production changes (including the later DIM05 group-exit change), so this run does not validate that later SDK runtime. Current AFI checkout HEAD is d4ad3094775aa47e3284e789c500be7d4f27c8bb, while the installed AFI wheel is from 94386432; do not attribute the wheel run to all current checkout changes. No live venue, account credential, or exchange was used.

## Formal-plan mapping

The accepted AFI10 path now has a concrete normal service-strategy invocation using the installed SDK/AFI/Backtrader wheel set: the configured service profile completed order and query operations and graceful STOP/child exit. Together with prior AFI10 offline-R5 evidence, the previously migrated/retired legacy live-writer and quote entrypoints, and the installed-wheel origin/provenance evidence, this is the strongest remaining normal-path acceptance evidence for the existing AFI10 plan row.

This single synthetic-profile case does not establish real-provider/account execution or every strategy/mode. It is not a formal MIG01 completion claim. Remaining MIG01 closure is limited to any plan-required active exports/runtime/package dependency still present after the accepted Base/SDK/provider retirements and the actual release/package closure check; this record makes no claim about untested providers or current checkout wheels.

No tests, Host, wheel build/install, or QA were run while preparing this accepted delivery.

Root adopted this exact test postimage after verifying the successful raw result and cleanup receipt. This delivery adds no formal case count. Exact commit/blob verification is recorded at `D:/bt_api_py/.codex-tmp/afi10-installed-service-postcommit-20261017.json`.
