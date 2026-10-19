# MIG03 AFI12 receipt and legacy-writer boundary — 2026-10-17

This small `dev` round closes a source-level import and legacy-writer refusal gap. It does not establish formal MIG03 PASS.

## Scope

- Execution child commit: `d034881a56fac3d4e6360b19371f51ecb9168643`, parent `10348e6d44a585ff80f1d7952bb66ba9c5367523`. It changes only `paper_legacy_import.py` and its focused test. The importer now accepts the actual legacy cash-funded spot position projection (`margin_value == market_value`, `margin_rate == multiplier == 1`) while retaining the source document and digest. Mismatched notional and leveraged settings remain rejected.
- AFI source scope: `legacy_paper_migration.py`, `mig03_boundary_inventory.py`, `test_legacy_paper_import_migration.py`, and `test_mig03_boundary_inventory.py`. These paths bind and conserve the AFI12 import receipt/fence identity and exact source/account economics; the real legacy `submit_order` and `_process_order` entrypoints are checked after import activation.
- Static review: `dim05_roll_exit_review` returned `GO_STATIC` for the six code/test pins. It confirmed the migration-installed account-update trigger stops the legacy writer lease before lease grant and that its exception classifier accepts only one valid active receipt with matching account, fence, owner, version, generation, and state. The runtime guarantee depends on applying the AFI12 import migration.

## Verification

- Execution `tests/test_paper_legacy_import.py`: 12 passed; JUnit and stdout are `D:\temp\mig03-execution-paper-legacy-import-r1.xml` and `.log`.
- AFI targeted receipt, preservation, and real matcher/import/refusal selectors: 3 passed; JUnit and stdout are `D:\temp\mig03-afi12-receipt-writer-r3.xml` and `.log`.
- Ruff `F821` over the six changed code/test files: passed. The static reviewer did not rerun QA.
- Earlier AFI diagnostic run `D:\temp\mig03-import-diagnostic-r2.xml` is retained: one fixture/source-contract failure led to the exact spot-margin mismatch above. It is not counted as a pass and was not overwritten.

All test data was local synthetic SQLite. No live account, provider, Host, or external service was used. This round covers AFI12 receipt/writer fencing and conservation only; remaining MIG03 boundary inventory and full cutover requirements remain partial.
