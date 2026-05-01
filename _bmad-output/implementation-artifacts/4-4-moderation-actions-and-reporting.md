# Story 4.4: Moderation Actions and Reporting

Status: ready-for-dev

## Story

As a moderator,  
I want reporting and moderation actions,  
so that harmful or off-topic content can be handled.

## Acceptance Criteria

1. Users can report threads and replies.
2. Moderators and administrators can hide, lock, pin, or feature threads.
3. Locked threads cannot receive new replies.
4. Moderation actions create audit records.
5. Report handling status is visible in the admin or moderation workflow.

## Tasks / Subtasks

- [x] Add backend tests for report target validation and report creation. (AC: 1)
- [x] Add backend tests for moderator/admin-only thread actions. (AC: 2)
- [x] Ensure lock behavior continues to reject new replies. (AC: 3)
- [x] Persist audit records for moderation actions. (AC: 4)
- [x] Add report listing and status update workflow for moderators/admins. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Forum reports require authenticated and email-verified users.
- Moderation actions require moderator or administrator roles.
- Public browsing already filters non-normal threads and locked thread reply creation is covered by Story 4.2.
- Audit records should use `AuditLog` for persistent moderation history.

### Project Structure Notes

- Backend API: `backend/app/api/v1/forum.py`.
- Backend schemas: `backend/app/schemas/forum.py`.
- Backend tests: `backend/tests/test_forum_moderation_reporting.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.4 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_moderation_reporting.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added verified-user report creation with exactly-one target validation.
- Added moderator/admin-only pin, lock, feature, and hide thread actions.
- Added persistent `AuditLog` entries for moderation actions and report status updates.
- Added moderator/admin report listing and report status update workflow.
- Preserved locked-thread reply rejection through existing `create_reply` behavior.

### File List

- `backend/app/api/v1/forum.py`
- `backend/app/schemas/forum.py`
- `backend/app/schemas/__init__.py`
- `backend/tests/test_forum_moderation_reporting.py`
- `_bmad-output/implementation-artifacts/4-4-moderation-actions-and-reporting.md`
- `_bmad-output/implementation-artifacts/4-4-moderation-actions-and-reporting-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
