# Story 2.4: Password Reset Flow

Status: ready-for-dev

## Story

As a registered user,  
I want to reset a forgotten password,  
so that I can recover access securely.

## Acceptance Criteria

1. Password reset request accepts an email without exposing whether the account exists.
2. Reset tokens expire according to configuration.
3. Reset token values are not stored in plaintext.
4. Password reset applies the same password policy as registration.
5. Used or expired reset tokens cannot be reused.

## Tasks / Subtasks

- [x] Add password reset request tests. (AC: 1, 2, 3)
  - [x] Verify existing and unknown email requests return the same public response.
  - [x] Verify existing account reset token is stored with configured Redis TTL.
  - [x] Verify plaintext reset token is not stored in Redis key/value or response.
- [x] Add password reset confirmation tests. (AC: 4, 5)
  - [x] Verify weak new passwords are rejected by the same policy as registration.
  - [x] Verify valid reset token updates password hash and deletes token.
  - [x] Verify missing, expired, or reused tokens are rejected safely.
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Password reset requests must not reveal whether an email exists.
- Store reset token hashes only; never persist or return plaintext reset tokens.
- Use Redis TTL for reset token expiry.
- Password reset confirmation must reuse the configured password strength policy.
- Used reset tokens must be deleted after successful password update.

### Project Structure Notes

- Password reset endpoints: `backend/app/api/v1/auth.py`.
- Token utilities: `backend/app/core/tokens.py`.
- Password utilities: `backend/app/core/security.py`.
- Backend tests: `backend/tests/test_password_reset_flow.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.4 acceptance criteria.
- `backend/app/core/config.py` — password reset token expiry and password policy configuration.
- `backend/app/core/security.py` — password validation and Argon2 hashing.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added password reset request tests for account enumeration prevention, configured TTL, and hashed token storage.
- Added password reset confirmation tests for password policy enforcement, successful password update, token deletion, and reused token rejection.
- Verified backend tests through the project quality script.

### File List

- `backend/tests/test_password_reset_flow.py`
- `_bmad-output/implementation-artifacts/2-4-password-reset-flow.md`
- `_bmad-output/implementation-artifacts/2-4-password-reset-flow-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
