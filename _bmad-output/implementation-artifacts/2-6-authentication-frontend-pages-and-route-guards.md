# Story 2.6: Authentication Frontend Pages and Route Guards

Status: ready-for-dev

## Story

As a user,  
I want registration, login, verification result, password reset, and profile entry pages,  
so that authentication flows are usable from the browser.

## Acceptance Criteria

1. Frontend includes registration and login forms with validation and error states.
2. Frontend includes email verification result and password reset pages.
3. Frontend stores and clears authenticated state consistently.
4. Protected routes redirect unauthenticated users to login.
5. Unverified users receive clear guidance when trying restricted actions.

## Tasks / Subtasks

- [x] Update frontend auth state handling. (AC: 3)
  - [x] Store and restore access/refresh tokens consistently.
  - [x] Clear tokens on logout and failed current-user fetch.
- [x] Update login/register forms. (AC: 1)
  - [x] Use auth store login/register actions.
  - [x] Display backend validation and generic error states.
- [x] Add verification and password reset pages. (AC: 2)
  - [x] Add email verification result page.
  - [x] Add password reset request and confirmation page.
- [x] Add route guard for protected pages. (AC: 4)
- [x] Add unverified-user guidance in user center. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Do not expose passwords, password hashes, verification tokens, or refresh-token internals in UI state beyond required token storage.
- Authentication state is client-side persisted for MVP via browser storage.
- Protected routes should redirect to login with a safe `redirect` query.
- Unverified users should receive clear, non-alarming guidance before write actions.

### Project Structure Notes

- Auth store: `frontend/stores/auth.ts`.
- API plugin/composable: `frontend/plugins/api.ts`, `frontend/composables/useApi.ts`.
- Auth pages: `frontend/pages/auth/*.vue`.
- Protected user page: `frontend/pages/user/index.vue`.
- Route middleware: `frontend/middleware/auth.ts`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.6 acceptance criteria.
- `backend/app/api/v1/auth.py` — backend auth API contracts.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`
- `python3 - <<'PY' ... npm run typecheck ... PY`

### Completion Notes List

- Updated auth store token persistence and logout behavior.
- Added verification and password reset pages.
- Added protected route middleware and user-center verification guidance.
- Verified backend and frontend typecheck through timeout-wrapped commands.

### File List

- `frontend/stores/auth.ts`
- `frontend/plugins/api.ts`
- `frontend/composables/useApi.ts`
- `frontend/plugins/auth.ts`
- `frontend/middleware/auth.ts`
- `frontend/pages/auth/login.vue`
- `frontend/pages/auth/register.vue`
- `frontend/pages/auth/verify-email.vue`
- `frontend/pages/auth/password-reset.vue`
- `frontend/pages/user/index.vue`
- `_bmad-output/implementation-artifacts/2-6-authentication-frontend-pages-and-route-guards.md`
- `_bmad-output/implementation-artifacts/2-6-authentication-frontend-pages-and-route-guards-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
