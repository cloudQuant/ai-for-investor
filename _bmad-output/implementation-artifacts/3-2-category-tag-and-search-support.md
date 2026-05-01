# Story 3.2: Category, Tag, and Search Support

Status: ready-for-dev

## Story

As a visitor,  
I want to filter and search content,  
so that I can find relevant tutorials, project reviews, and risk methodology articles.

## Acceptance Criteria

1. Blog posts support category assignment.
2. Blog posts support multiple tags.
3. Public list can filter by category and tag.
4. Public search supports keyword queries.
5. Empty search and filter states are clear and actionable.

## Tasks / Subtasks

- [x] Add backend tests for category, tag, and search filters. (AC: 1, 2, 3, 4)
- [x] Extend public blog list API with `category`, `tag`, and `q` query parameters. (AC: 3, 4)
- [x] Keep published-only visibility rules while filtering/searching. (AC: 3, 4)
- [x] Add frontend filter/search controls to blog list. (AC: 3, 4, 5)
- [x] Add clear empty state with reset action. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Category and tag models already exist: `Category`, `Tag`, and `TagRelation`.
- Public list must continue hiding draft, deleted, and unpublished posts.
- Search is scoped to public published posts only.
- Frontend should use existing `$api` plugin and query parameters.
- Do not add investment advice, return promises, broker/exchange integrations, or arbitrary code execution.

### Project Structure Notes

- Backend API: `backend/app/api/v1/blog.py`.
- Blog models: `backend/app/models/blog.py`.
- Backend tests: `backend/tests/test_public_blog.py`.
- Frontend list page: `frontend/pages/blog/index.vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 3.2 acceptance criteria.
- `_bmad-output/implementation-artifacts/3-1-public-blog-listing-and-detail-pages.md` — preceding public blog implementation.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_public_blog.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Extended public blog API with category, tag, and keyword search filters.
- Added frontend category/tag dropdowns, keyword search, and empty-state reset action.
- Verified backend tests and frontend typecheck.

### File List

- `backend/app/api/v1/blog.py`
- `backend/tests/test_public_blog.py`
- `frontend/pages/blog/index.vue`
- `_bmad-output/implementation-artifacts/3-2-category-tag-and-search-support.md`
- `_bmad-output/implementation-artifacts/3-2-category-tag-and-search-support-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
