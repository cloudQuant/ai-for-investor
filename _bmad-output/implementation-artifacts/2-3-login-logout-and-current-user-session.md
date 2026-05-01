# Story 2.3: Login, Logout, and Current User Session

Status: ready-for-dev

## Story

As a registered user,  
I want to log in, log out, and fetch my current session,  
so that the frontend can display correct authenticated state.

## Acceptance Criteria

1. Login validates credentials and returns an approved session or token response.
2. Logout invalidates the active session or token according to the selected auth model.
3. Current user endpoint returns user identity, roles, and verification state.
4. Authentication failures use generic error messages.
5. Login attempts are rate limited according to configuration.

## Tasks / Subtasks

- [x] Add login/session tests. (AC: 1, 3, 4, 5)
  - [x] Verify valid login returns bearer access and refresh tokens.
  - [x] Verify invalid login uses generic error messaging.
  - [x] Verify rate-limited login returns `429`.
  - [x] Verify current user response includes identity, roles, and verification state.
- [x] Add logout invalidation tests. (AC: 2)
  - [x] Verify logout stores active access token in Redis blacklist.
  - [x] Verify blacklisted access tokens cannot be used for current user lookup.
- [x] Update auth implementation to support token blacklist checks. (AC: 2)
- [x] Update current user response with roles and verification state. (AC: 3)
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- The selected auth model remains JWT bearer tokens.
- Logout invalidates the active access token by storing a blacklist marker in Redis until token expiry.
- Authentication failure messages must remain generic and avoid account enumeration.
- Current session payload must not return password hashes, refresh tokens, or sensitive token internals.

### Project Structure Notes

- Auth endpoints: `backend/app/api/v1/auth.py`.
- User schema: `backend/app/schemas/user.py`.
- Token configuration: `backend/app/core/config.py`.
- Backend tests: `backend/tests/test_login_session_flow.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.3 acceptance criteria.
- `backend/app/core/security.py` — password verification.
- `backend/app/core/config.py` — token expiry and login rate limit configuration.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added JWT login/session tests.
- Added Redis-backed access-token blacklist checks for logout.
- Added roles and `email_verified` to the current-user response.
- Verified backend tests through the project quality script.

### File List

- `backend/app/api/v1/auth.py`
- `backend/tests/test_login_session_flow.py`
- `_bmad-output/implementation-artifacts/2-3-login-logout-and-current-user-session.md`
- `_bmad-output/implementation-artifacts/2-3-login-logout-and-current-user-session-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
