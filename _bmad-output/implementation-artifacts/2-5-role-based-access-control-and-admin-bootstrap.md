# Story 2.5: Role-Based Access Control and Admin Bootstrap

Status: ready-for-dev

## Story

As an administrator,  
I want role-based access checks and bootstrap support,  
so that admin-only actions are protected.

## Acceptance Criteria

1. Roles include visitor, registered user, author, editor, moderator, and administrator concepts.
2. Backend dependencies or guards protect admin and moderation endpoints.
3. Admin bootstrap can create an initial administrator account safely.
4. Admin login or admin-sensitive actions produce audit records.
5. Unauthorized and forbidden responses are distinguishable and safe.

## Tasks / Subtasks

- [x] Add RBAC helper tests. (AC: 1, 2, 5)
  - [x] Verify required role concepts exist.
  - [x] Verify admin guard accepts admin role and rejects missing/insufficient roles.
  - [x] Verify moderator guard accepts moderator/admin roles.
  - [x] Verify unauthenticated and forbidden responses are distinguishable.
- [x] Add admin bootstrap tests. (AC: 3)
  - [x] Verify bootstrap creates a verified active admin with hashed password.
  - [x] Verify bootstrap refuses to create a second administrator.
- [x] Add admin audit tests. (AC: 4)
  - [x] Verify admin-sensitive endpoint emits an audit log event.
- [x] Replace admin email convention with role-based admin guard. (AC: 2, 5)
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- RBAC must rely on role membership, not hard-coded admin email conventions.
- Unauthorized unauthenticated requests should return `401`.
- Authenticated users without required roles should return `403`.
- Admin-sensitive actions should emit audit-oriented structured logs.
- Bootstrap must safely refuse duplicate initial administrators.

### Project Structure Notes

- RBAC helpers: `backend/app/core/rbac.py`.
- Admin endpoints: `backend/app/api/v1/admin.py`.
- User/role model: `backend/app/models/user.py`.
- Backend tests: `backend/tests/test_rbac_admin_bootstrap.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.5 acceptance criteria.
- `backend/app/models/user.py` — role enum and user-role relationship.
- `backend/app/models/audit.py` — audit log model baseline.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added role-based RBAC helpers and admin bootstrap helper.
- Replaced admin email convention with role membership checks.
- Added admin-sensitive structured audit log events.
- Verified backend tests through the project quality script.

### File List

- `backend/app/core/rbac.py`
- `backend/app/api/v1/admin.py`
- `backend/tests/test_rbac_admin_bootstrap.py`
- `_bmad-output/implementation-artifacts/2-5-role-based-access-control-and-admin-bootstrap.md`
- `_bmad-output/implementation-artifacts/2-5-role-based-access-control-and-admin-bootstrap-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
