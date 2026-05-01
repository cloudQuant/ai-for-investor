# Story 4.1: Forum Categories and Public Browsing

Status: ready-for-dev

## Story

As a visitor,  
I want to browse forum categories and threads,  
so that I can understand community activity before registering.

## Acceptance Criteria

1. Forum categories can be listed publicly.
2. Forum threads can be listed by category.
3. Thread list supports pagination and basic sorting.
4. Thread detail is readable by visitors unless hidden by moderation.
5. Empty category states invite relevant discussion.

## Tasks / Subtasks

- [x] Add backend tests for public categories, category filtering, sorting, pagination, and hidden thread detail. (AC: 1, 2, 3, 4)
- [x] Extend public forum thread listing with category slug and sort options. (AC: 2, 3)
- [x] Harden thread detail visibility for moderated/deleted content. (AC: 4)
- [x] Update forum index UI with category query sync, sorting, pagination, and empty state. (AC: 2, 3, 5)
- [x] Add public forum detail page. (AC: 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Public browsing must not require authentication.
- Moderated or deleted threads must not be exposed in public detail/list endpoints.
- Empty states should invite readers to register or browse other categories without implying investment advice.
- Preserve verified-user requirements for creating threads and replies in later stories.

### Project Structure Notes

- Backend API: `backend/app/api/v1/forum.py`.
- Backend models: `backend/app/models/forum.py`.
- Backend schemas: `backend/app/schemas/forum.py`.
- Backend tests: `backend/tests/test_forum_public_browsing.py`.
- Frontend forum list: `frontend/pages/forum/index.vue`.
- Frontend forum detail: `frontend/pages/forum/[id].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.1 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_public_browsing.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added public forum browsing tests for categories, category slug filtering, pagination, sorting, detail reading, and hidden thread protection.
- Extended forum thread list responses with category metadata.
- Added public category slug filter and sort modes to forum thread listing.
- Hardened thread detail endpoint to hide non-normal or deleted threads.
- Updated forum index with category query sync, sorting, pagination, and empty states.
- Added public forum thread detail page with replies.

### File List

- `backend/app/api/v1/forum.py`
- `backend/tests/test_forum_public_browsing.py`
- `frontend/pages/forum/index.vue`
- `frontend/pages/forum/[id].vue`
- `_bmad-output/implementation-artifacts/4-1-forum-categories-and-public-browsing.md`
- `_bmad-output/implementation-artifacts/4-1-forum-categories-and-public-browsing-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
