# Story 4.2: Thread and Reply Creation

Status: ready-for-dev

## Story

As a verified user,  
I want to create threads and replies,  
so that I can participate in AI trading and investing discussions.

## Acceptance Criteria

1. Only authenticated and email-verified users can create threads.
2. Only authenticated and email-verified users can create replies.
3. Thread and reply content is validated and sanitized.
4. New user posting limits and cooldowns apply.
5. Unauthenticated users are guided to login or registration when attempting write actions.

## Tasks / Subtasks

- [x] Add backend tests for verified-only creation, sanitization, cooldowns, and locked thread behavior. (AC: 1, 2, 3, 4)
- [x] Implement backend content sanitization and validation for threads/replies. (AC: 3)
- [x] Implement posting cooldown limits for write actions. (AC: 4)
- [x] Add frontend new thread page with auth/unverified guidance. (AC: 1, 3, 5)
- [x] Add reply composer guidance and submission on thread detail. (AC: 2, 3, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Posting requires authenticated and email-verified users.
- Forum content should be treated as plain text and sanitized before persistence.
- Cooldown enforcement should return HTTP 429 with a safe message.
- Locked threads should reject new replies.
- Unauthenticated frontend users should see login/register guidance rather than a broken form.

### Project Structure Notes

- Backend API: `backend/app/api/v1/forum.py`.
- Backend schemas: `backend/app/schemas/forum.py`.
- Backend tests: `backend/tests/test_forum_thread_reply_creation.py`.
- Frontend new thread page: `frontend/pages/forum/new.vue`.
- Frontend thread detail/reply composer: `frontend/pages/forum/[id].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.2 acceptance criteria.
- `_bmad-output/implementation-artifacts/4-1-forum-categories-and-public-browsing.md`.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_thread_reply_creation.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added verified-only backend tests for thread and reply creation.
- Added plain-text sanitization and non-empty validation for thread titles, thread content, and reply content.
- Added new-user posting cooldown enforcement returning HTTP 429.
- Added category validation for new threads and locked/deleted thread checks for replies.
- Added frontend new thread page with login/register and email verification guidance.
- Added reply composer to public thread detail page with login/register and email verification guidance.

### File List

- `backend/app/api/v1/forum.py`
- `backend/tests/test_forum_thread_reply_creation.py`
- `frontend/pages/forum/new.vue`
- `frontend/pages/forum/[id].vue`
- `_bmad-output/implementation-artifacts/4-2-thread-and-reply-creation.md`
- `_bmad-output/implementation-artifacts/4-2-thread-and-reply-creation-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
