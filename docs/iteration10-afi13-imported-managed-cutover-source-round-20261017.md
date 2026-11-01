# AFI13: explicitly activate an imported Paper account

Repository: D:/source_code/ai-for-investor, existing dev checkout. Parent: 7290547f3c3ea96c1cb664074956237019e9fc3c.

An ACTIVE legacy import can now be explicitly confirmed for managed Paper operation. The immutable v2 receipt binds the authenticated owner, account, exact submit binding, active import generation, target counts and digest, and execution scope/domain. Reads and new submissions revalidate that receipt. Source ledger rows remain read-only and are not fabricated as new execution fills. Empty-account cutover retains the existing v1 path. The migration preserves v1 receipt rows and writer fences; downgrade refuses imported v2 receipts.

Scope: seven application files, one Alembic migration and three test files, plus this record. The updated managed-paper end-to-end fixture is prepared source only; its new actual imported-account path has not yet run. Unrelated existing changes are preserved.

Acceptance is fixed-source synthetic SQLite/component evidence, not formal AFI13, provider or account acceptance. Independent static review accepted the ten-path production/test patch and the additive two-case real Alembic/SQLite regression.

Root R2 ran five selected component tests: two passed and three failed because --noconftest omitted the existing in-memory database fixture. Those raw failures remain unchanged. R3 removed that harness option, enabled the pinned conftest and explicitly selected an in-memory DATABASE_URL, then ran only the three failed nodes: 3 passed in 2.79 seconds, exit 0, two known timeout plugin configuration warnings. Both runs preserved all 2,954 pinned inputs and all eight repository HEADs; stderr was empty. Together they cover the five selected assertions; this is not a claim of one all-green five-test run.

- R2 output: D:/temp/afi13-imported-cutover-root-qa-r2-20261017; stdout SHA-256 d0618f22812b0d96c8cf8bdeed44f79267dc6457e64b509320cb52acc87a23ba.
- R3 output: D:/temp/afi13-imported-cutover-root-qa-r3-20261017; stdout SHA-256 d9702c419ddc9e8ce45333ed2ded955afbac585122aac9a2ad74b259338d4bfd.
- R3 spec: D:/temp/afi13-imported-cutover-fixed-source-r1-20261017/root-qa-spec-prep-r3.json, SHA-256 5fc5988b4645f0d8afcdc71aaa19dcbce61be4129d510c36fe85f17fef57fd4e.

The author R5 migration regression separately passed both tests in 0.61 seconds, exit 0, four known pytest configuration warnings. It invokes all three migration modules, preserves populated v1 receipts and legacy rows, restores v1 fences on downgrade, and refuses downgrade with v2 imported receipts. Root checked the exact saved JUnit, output and source hash; it did not repeat those tests. Raw artifacts remain at .codex-tmp/afi13-import-cutover-migration-regression-r5-20261017; stdout SHA-256 9511a0a49baa3c6c796bdb1ed278e57a5deb66e4365c74875c7e08b411f708c2, JUnit d1742d39dc5b84039a667816718bfd74d8c1f84473152f82dcc112bc59aa22f6.

The earlier author five-pass transcript lacked raw output/JUnit and is not substituted for Root evidence. Earlier failures and the unrelated migration-file failures are preserved; no broader suite pass is claimed. Next acceptance is the normal API/import/explicit cutover/new Paper fill integration with actual local services.

Reviewed checkout pins (Git may normalize existing line endings):

- `src/backend/app/api/paper_trading.py`: 21750 bytes, `4a5ac91c9414bc8350567ec016e5d192763bf1593c00ef8df73043ee85eeb9d8`.
- `src/backend/app/models/__init__.py`: 10039 bytes, `2252b032acd39801f351260837315e4757ad94f1cbade8125b3ff2da93fe0844`.
- `src/backend/app/models/legacy_paper_cutover.py`: 5050 bytes, `5f11f4f88fe32782e0267f5b5c1f11d52cc75e853ed32938ec269b133a9290e1`.
- `src/backend/app/schemas/paper_trading.py`: 9627 bytes, `69faeb1aa2f63dc7441170e7ec5cdc2d2a3ca0e8ea2a89c246e227ac6e3f695d`.
- `src/backend/app/services/legacy_paper_import_migration.py`: 74467 bytes, `93af5b6e4a9b13f59a56baf65080511da827e3668d92d8da1050b42e756f0ead`.
- `src/backend/app/services/legacy_paper_migration.py`: 35062 bytes, `a45a0e8edd0501a3118442426bafbadbe1a3401a634d8c82b40ecc7410553f1c`.
- `src/backend/app/services/managed_paper_adapter.py`: 25022 bytes, `0c9d99d02733ec935ff98c27fbe5bcafc74e6122f6a8ffe679bb147627504aa5`.
- `src/backend/tests/test_legacy_paper_import_migration.py`: 44731 bytes, `dd5bc4af943326c73ed1243185a3e6330cbc199ba8f3fdc25e7e4c7a3e8e7aad`.
- `src/backend/tests/test_managed_paper_end_to_end.py`: 60033 bytes, `faa8ca8ec69975083b8dc60869cc9fe0a276d4db60ca8fcd51454f4aa4d469dd`.
- `src/backend/alembic/versions/20261017_legacy_paper_import_cutover.py`: 6999 bytes, `de977b1f4f633361b3381c1a82deb55b485f6ea75b32036c0c1e266f16d3de1b`.
- `src/backend/tests/test_legacy_paper_import_cutover_migration.py`: 13471 bytes, `a74ed3130eb22dcd105a9efe0bc0ce7bba639a4ba6d6943b2480590528b2a64f`.
