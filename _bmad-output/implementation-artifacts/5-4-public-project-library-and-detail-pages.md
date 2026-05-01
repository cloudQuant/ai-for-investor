# Story 5.4: Public Project Library and Detail Pages

Status: ready-for-dev

## Story

As a visitor,  
I want to browse curated open-source projects,  
so that I can compare tools and learn safely.

## Acceptance Criteria

1. Public project library lists reviewed projects.
2. Project detail shows repository link, summary, tags, score notes, license signal, update time, and risk reminder.
3. Public pages avoid implying investment advice or return guarantees.
4. Project library supports basic filtering or search.
5. Hidden or ignored projects are not publicly visible.

## Tasks / Subtasks

- [x] Add public project list search/filter support for selected projects only. (AC: 1, 3, 4, 5)
- [x] Add public project detail endpoint with safe educational metadata. (AC: 2, 3, 5)
- [x] Add public open-source project library page. (AC: 1, 3, 4, 5)
- [x] Add public project detail page. (AC: 2, 3, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Public promotion requires `status='selected'` from Story 5.3.
- Public copy must avoid investment advice, return guarantees, or recommendations.
- Detail pages should show score notes as editorial context, not as a recommendation.

### Project Structure Notes

- Backend API: `backend/app/api/v1/open_source.py`.
- Backend tests: `backend/tests/test_public_project_library.py`.
- Frontend list page: `frontend/pages/open-source/index.vue`.
- Frontend detail page: `frontend/pages/open-source/[id].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 5.4 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_public_project_library.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added selected-only public project library API with search and language filters.
- Added selected-only public project detail API with repository link, summary, tags, score context, license, update time, and risk reminder.
- Added public `/open-source` project library page.
- Added public `/open-source/[id]` project detail page.
- Public copy frames content as education/research only and avoids recommendations or return guarantees.

### File List

- `backend/app/api/v1/open_source.py`
- `backend/tests/test_public_project_library.py`
- `frontend/pages/open-source/index.vue`
- `frontend/pages/open-source/[id].vue`
- `_bmad-output/implementation-artifacts/5-4-public-project-library-and-detail-pages.md`
- `_bmad-output/implementation-artifacts/5-4-public-project-library-and-detail-pages-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
