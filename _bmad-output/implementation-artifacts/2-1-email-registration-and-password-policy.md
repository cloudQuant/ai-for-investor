# Story 2.1: Email Registration and Password Policy

Status: ready-for-dev

## Story

As a visitor,  
I want to register with email and password,  
so that I can become a verified community user.

## Acceptance Criteria

1. Registration accepts email and password and validates email format.
2. Password rules follow configured minimum length and complexity settings.
3. Passwords are hashed with Argon2 or an approved secure hash strategy.
4. Duplicate email registration is rejected safely.
5. Registration responses do not leak sensitive token or password data.

## Tasks / Subtasks

- [x] Add registration/password policy tests. (AC: 1, 2, 3, 4, 5)
  - [x] Verify invalid email is rejected by schema validation.
  - [x] Verify password policy enforces configured length and complexity.
  - [x] Verify password hashing uses Argon2 and can verify valid passwords.
  - [x] Verify duplicate email registration returns a safe error.
  - [x] Verify successful registration response excludes password hashes and verification tokens.
- [x] Update registration schema to allow email/password registration with optional username. (AC: 1)
- [x] Preserve username support for clients that provide it. (AC: 1)
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Do not return plaintext passwords, password hashes, or verification token values in registration responses.
- Keep verification token storage hashed and delegated to the existing token utility.
- Keep rate limiting behavior intact.
- Do not add real trading, broker, exchange, fund, advice, return-promise, or arbitrary-code-execution behavior.

### Project Structure Notes

- Registration endpoint: `backend/app/api/v1/auth.py`.
- User schema: `backend/app/schemas/user.py`.
- Password utilities: `backend/app/core/security.py`.
- Backend tests: `backend/tests/test_registration_policy.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.1 acceptance criteria.
- `backend/app/core/config.py` — configured password policy.
- `backend/app/core/security.py` — Argon2 hashing and password validation.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added registration/password policy tests.
- Updated `RegisterRequest.username` to be optional for email/password registration.
- Generated a fallback username from the email local part when not supplied.
- Verified backend tests through the project quality script.

### File List

- `backend/app/api/v1/auth.py`
- `backend/app/schemas/user.py`
- `backend/tests/test_registration_policy.py`
- `_bmad-output/implementation-artifacts/2-1-email-registration-and-password-policy.md`
- `_bmad-output/implementation-artifacts/2-1-email-registration-and-password-policy-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
