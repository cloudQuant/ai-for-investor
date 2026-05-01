# Story 7.1: End-to-End Test Coverage for Core Paths

Status: ready-for-dev

## Story

As a tester,  
I want automated coverage for core user paths,  
so that launch regressions can be caught before release.

## Acceptance Criteria

1. E2E or integration coverage includes visitor browsing homepage and blog.
2. E2E or integration coverage includes registration, email verification, and login.
3. E2E or integration coverage includes posting and replying in forum.
4. E2E or integration coverage includes creating and viewing a tool job.
5. E2E or integration coverage includes admin publishing content and moderating forum content.

## Tasks / Subtasks

- [x] Add core path coverage guard mapping acceptance criteria to automated tests. (AC: 1, 2, 3, 4, 5)
- [x] Verify visitor homepage/blog coverage through frontend page presence and public blog integration tests. (AC: 1)
- [x] Verify auth lifecycle coverage through registration, email verification, login, and current-user tests. (AC: 2)
- [x] Verify forum posting/reply and moderation coverage. (AC: 3, 5)
- [x] Verify tool job creation and result viewing coverage. (AC: 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- The current frontend stack does not include Playwright/Cypress dependencies.
- Story 7.1 can satisfy the acceptance criteria with integration coverage as explicitly allowed by the story.
- The coverage guard should fail if a required core-path test file or expected test case is removed.

### Project Structure Notes

- Coverage guard: `backend/tests/test_core_path_integration_coverage.py`.
- Existing backend integration tests remain the source of behavioral coverage.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 7.1 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_core_path_integration_coverage.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added `backend/tests/test_core_path_integration_coverage.py` as a launch-readiness coverage guard.
- Mapped Story 7.1 acceptance criteria to existing automated backend integration coverage and required frontend route/page files.
- Verified visitor homepage/blog route presence and public blog list/detail tests.
- Verified registration, email verification, login, and current-user tests.
- Verified forum thread creation, reply creation, moderation, and report handling tests.
- Verified tool job creation, job history, and safe job detail display tests.

### File List

- `backend/tests/test_core_path_integration_coverage.py`
- `_bmad-output/implementation-artifacts/7-1-end-to-end-test-coverage-for-core-paths.md`
- `_bmad-output/implementation-artifacts/7-1-end-to-end-test-coverage-for-core-paths-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
