# Story 2.2: Email Verification Flow

Status: ready-for-dev

## Story

As a registered user,  
I want to verify my email,  
so that I can unlock community and tool actions.

## Acceptance Criteria

1. Registration creates an email verification token with an expiry.
2. Verification token values are not stored in plaintext.
3. Verification succeeds only for valid, unexpired tokens.
4. Expired or reused tokens are rejected with a safe error.
5. Unverified users remain blocked from posting, replying, and creating tool jobs.

## Tasks / Subtasks

- [x] Add registration token storage tests. (AC: 1, 2)
  - [x] Verify Redis `setex` stores verification token hash key with configured expiry.
  - [x] Verify plaintext token is not stored in response, key, or Redis value.
- [x] Add email verification endpoint tests. (AC: 3, 4)
  - [x] Verify valid token marks user verified and deletes token.
  - [x] Verify expired or missing token returns a safe error.
  - [x] Verify reused token is rejected after deletion.
- [x] Add unverified-user restriction tests. (AC: 5)
  - [x] Verify forum thread/reply guard rejects unverified users.
  - [x] Verify tool job guard rejects unverified users.
- [x] Run backend tests with timeout through `scripts/quality_check.py`. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Store verification token hashes only; never persist or return plaintext verification tokens.
- Use Redis TTL for token expiry.
- Safe errors should not reveal token validity beyond invalid/expired status.
- Posting, replying, and tool job creation must require a verified email.

### Project Structure Notes

- Registration and verification endpoint: `backend/app/api/v1/auth.py`.
- Token utilities: `backend/app/core/tokens.py`.
- Forum verification guard: `backend/app/api/v1/forum.py`.
- Tool verification guard: `backend/app/api/v1/tools.py`.
- Backend tests: `backend/tests/test_email_verification_flow.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 2 and Story 2.2 acceptance criteria.
- `backend/app/core/config.py` — verification token expiry configuration.
- `backend/app/core/tokens.py` — token generation and hashing utilities.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added email verification flow tests for hashed token storage, valid verification, expired/missing token rejection, reused token rejection, and unverified-user restrictions.
- Verified backend tests through the project quality script.

### File List

- `backend/tests/test_email_verification_flow.py`
- `_bmad-output/implementation-artifacts/2-2-email-verification-flow.md`
- `_bmad-output/implementation-artifacts/2-2-email-verification-flow-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
