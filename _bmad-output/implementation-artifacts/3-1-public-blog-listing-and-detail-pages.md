# Story 3.1: Public Blog Listing and Detail Pages

Status: ready-for-dev

## Story

As a visitor,  
I want to browse and read published blog posts,  
so that I can learn from curated AI trading and investing content.

## Acceptance Criteria

1. Public blog list shows published posts with title, summary, author, category, tags, and published date.
2. Draft, deleted, or unpublished posts are not visible publicly.
3. Public blog detail page renders published post content and metadata.
4. Missing or non-public posts return safe not-found responses.
5. Blog list supports pagination using the existing API response shape.

## Tasks / Subtasks

- [x] Add backend public blog API tests. (AC: 1, 2, 3, 4, 5)
  - [x] Verify list returns published posts only.
  - [x] Verify detail returns one published post by slug.
  - [x] Verify draft/deleted/missing detail returns `404`.
  - [x] Verify pagination metadata is returned.
- [x] Implement public blog list and detail endpoints. (AC: 1, 2, 3, 4, 5)
- [x] Add public blog detail frontend page. (AC: 3, 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Public endpoints must never expose drafts or deleted posts.
- Public read endpoints must not require authentication.
- Keep response payloads compatible with current frontend list expectations.
- Do not add investment advice, return promises, broker/exchange integrations, or arbitrary code execution.

### Project Structure Notes

- Backend API: `backend/app/api/v1/blog.py`.
- Blog models: `backend/app/models/blog.py`.
- Blog schemas: `backend/app/schemas/blog.py`.
- Backend tests: `backend/tests/test_public_blog.py`.
- Frontend pages: `frontend/pages/blog/index.vue`, `frontend/pages/blog/[slug].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Epic 3 and Story 3.1 acceptance criteria.
- `backend/app/models/blog.py` — `BlogPost`, `Category`, and `Tag` models.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`
- `python3 - <<'PY' ... npm run typecheck ... PY`

### Completion Notes List

- Added published-only public blog list/detail backend tests.
- Implemented public blog list/detail endpoints with pagination.
- Added frontend dynamic blog detail page.
- Verified backend tests and frontend typecheck.

### File List

- `backend/app/api/v1/blog.py`
- `backend/tests/test_public_blog.py`
- `frontend/pages/blog/[slug].vue`
- `_bmad-output/implementation-artifacts/3-1-public-blog-listing-and-detail-pages.md`
- `_bmad-output/implementation-artifacts/3-1-public-blog-listing-and-detail-pages-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
