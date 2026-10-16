# MIG03 AFI12 runtime snapshot fence — 2026-10-17

This `dev` round closes the AFI legacy Paper runtime snapshot association and post-import writer-fence gap. It does not establish formal MIG03 PASS.

## Scope

- AFI source: `legacy_paper_import_migration.py`, `paper_runtime_service.py`, `paper_runtime_scheduler.py`, and the two corresponding API files `legacy_paper_import.py` and `paper_runtime.py`.
- Focused node: `tests/test_mig03_paper_runtime_snapshot_import_fence.py`.
- Base: AFI `dev` HEAD `0c815427a92926fb6886e5e1670c8b229ae41dd7`.

Import requires each owned runtime's existing snapshot history to establish one explicit owner/workspace/unit/instance/account relationship. Missing, unbound, mixed, orphaned, or ambiguous history fails before a target status/import call; the importer rechecks under the shared owner/account serialization path before writing `PREPARED`. No account identity is inferred or assigned to old rows.

New snapshots carry forward only a previously persisted and owner-validated `paper_account_id`. The existing AFI12 account trigger/receipt is checked at write and scheduler startup; restore skips fenced instances and an explicit old-worker restart exits before writing. The preserved-context schema remains the SDK-compatible v1 envelope, with exact source snapshot identity/FK rows retained in the existing `paper_equity_snapshots` category.

## Verification

- `test_unbound_running_runtime_fails_import_before_target_and_remains_operational`: 1 passed (`D:\temp\mig03-afi-snapshot-import-fence-unbound-r4.xml`).
- `test_bound_scheduler_is_stopped_by_active_import_receipt_and_write_fence`: 1 passed (`D:\temp\mig03-afi-snapshot-import-fence-bound-r4.xml`).
- Three previously targeted compatibility regressions passed 3/3 at `D:\temp\mig03-afi-snapshot-regressions-r1.xml`; that run preceded the final bounded account-query and context-envelope refinements.
- Ruff, `py_compile`, and scoped `git diff --check` passed. Independent static review returned `GO_STATIC` for the final six source/test pins.
- An earlier bound selector attempt failed in test setup because it called a nonexistent helper; that result is preserved at `D:\temp\mig03-afi-snapshot-import-fence-bound-r3.xml` and is not counted. The test now reads the persisted receipt through the model and passed in bound-r4.

All verification used local synthetic SQLite and the fixed DIM09 package-source export. No live account, external provider, or real venue was used. Unbound/no-history runtime relations remain deliberately unallocated and are rejected; this round does not establish every MIG03 participant or full cutover acceptance.
