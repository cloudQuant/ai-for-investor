# Story 4.3: Author Edit and Delete Controls

Status: ready-for-dev

## Story

As a content author,  
I want to edit or delete my own forum content,  
so that I can correct mistakes while preserving moderation needs.

## Acceptance Criteria

1. Authors can edit their own threads and replies within allowed rules.
2. Authors can delete or soft-delete their own content within allowed rules.
3. Users cannot edit or delete other users' content.
4. Deleted or hidden content has a safe public display state.
5. Edit and delete actions are auditable when required.

## Tasks / Subtasks

- [x] Add backend tests for author-only thread/reply update and delete controls. (AC: 1, 2, 3)
- [x] Sanitize and validate edited thread/reply content. (AC: 1)
- [x] Ensure deleted/hidden content is safely excluded from public detail/list responses. (AC: 4)
- [x] Add structured audit logging for update/delete actions. (AC: 5)
- [x] Add frontend author controls for edit/delete on owned content. (AC: 1, 2, 3)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Editing/deleting requires authenticated, email-verified users.
- Authors can only modify their own content; moderators/admins are handled in Story 4.4.
- Delete should remain a soft delete for audit/moderation purposes.
- Public endpoints should not expose deleted replies as normal visible content.

### Project Structure Notes

- Backend API: `backend/app/api/v1/forum.py`.
- Backend tests: `backend/tests/test_forum_author_controls.py`.
- Frontend thread detail: `frontend/pages/forum/[id].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.3 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_author_controls.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added backend tests for author-only thread/reply update and soft-delete behavior.
- Reused forum sanitization validation for thread/reply edit paths.
- Added structured logs for thread/reply update and delete actions.
- Preserved soft-delete behavior and public hidden/deleted content safety.
- Added frontend owner-only edit/delete controls on thread detail page.

### File List

- `backend/app/api/v1/forum.py`
- `backend/tests/test_forum_author_controls.py`
- `frontend/pages/forum/[id].vue`
- `_bmad-output/implementation-artifacts/4-3-author-edit-and-delete-controls.md`
- `_bmad-output/implementation-artifacts/4-3-author-edit-and-delete-controls-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
