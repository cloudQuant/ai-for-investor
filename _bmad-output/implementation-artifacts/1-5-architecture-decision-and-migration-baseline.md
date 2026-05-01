# Story 1.5: Architecture Decision and Migration Baseline

Status: ready-for-dev

## Story

As a technical lead,  
I want architecture decision and migration conventions,  
so that data and architecture changes remain auditable.

## Acceptance Criteria

1. Project documentation identifies modular monolith plus async workers as the MVP architecture.
2. New database changes require migrations or an explicit documented temporary exception.
3. A location or convention exists for future ADR records.
4. README explains that `init_db.py` is a development bootstrap and not a replacement for production migrations.
5. Sprint work items that change schema include migration and rollback acceptance criteria.

## Tasks / Subtasks

- [x] Add architecture baseline documentation. (AC: 1, 3)
  - [x] Document modular monolith plus async workers as the MVP architecture.
  - [x] Create ADR directory and naming convention.
- [x] Add migration policy documentation. (AC: 2, 4, 5)
  - [x] Define migration-or-exception rule for schema changes.
  - [x] Define rollback requirements for schema-changing sprint work.
  - [x] Clarify `init_db.py` is a local development bootstrap only.
- [x] Update README migration section with architecture and migration policy links. (AC: 1, 2, 3, 4, 5)
- [x] Add tests verifying architecture, ADR, migration, README, and sprint-schema-change policy coverage. (AC: 1, 2, 3, 4, 5)
- [x] Run project quality validation and backend tests with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- This story establishes process guardrails and documentation; it does not need to create production migrations yet.
- Do not use `init_db.py` as a production migration mechanism.
- Any future schema-changing story must include forward migration, rollback guidance, and verification criteria.
- ADRs should be concise, numbered, and immutable after acceptance except for superseding records.

### Project Structure Notes

- Architecture overview: `docs/architecture/README.md`.
- ADR convention: `docs/architecture/adr/README.md`.
- Migration policy: `docs/architecture/migration-policy.md`.
- Backend policy tests: `backend/tests/test_architecture_migration_baseline.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 1 and Story 1.5 acceptance criteria.
- `docs/迭代01/04-技术设计文档.md` — backend architecture and data store responsibilities.
- `README.md` — database initialization and migration guidance.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added architecture overview, ADR convention, and migration policy documents.
- Updated README to clarify the development-only role of `init_db.py` and link to policy docs.
- Added tests protecting the architecture/migration baseline.
- Verified backend tests through the project quality script.

### File List

- `docs/architecture/README.md`
- `docs/architecture/adr/README.md`
- `docs/architecture/migration-policy.md`
- `README.md`
- `backend/tests/test_architecture_migration_baseline.py`
- `_bmad-output/implementation-artifacts/1-5-architecture-decision-and-migration-baseline.md`
- `_bmad-output/implementation-artifacts/1-5-architecture-decision-and-migration-baseline-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
