# Story 3.3: Admin Blog CRUD and Publishing Workflow

Status: ready-for-dev

## Story

As an author or administrator,  
I want to create, preview, publish, update, and unpublish articles,  
so that content operations can run safely.

## Acceptance Criteria

1. Authorized users can create and edit article drafts.
2. Authorized users can preview drafts before publication.
3. Authorized users can publish and unpublish articles.
4. Publishing records author, status, and publication timestamps.
5. Unauthorized users cannot access article management actions.

## Tasks / Subtasks

- [x] Add content-role RBAC guard for author/editor/admin. (AC: 1, 2, 3, 5)
- [x] Add backend tests for admin blog create, update, preview, publish, unpublish, and delete. (AC: 1, 2, 3, 4, 5)
- [x] Implement admin blog management endpoints under the blog API. (AC: 1, 2, 3, 4, 5)
- [x] Ensure public endpoints still only expose published posts. (AC: 2, 3)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Content operations are restricted to `author`, `editor`, and `admin` roles.
- New posts default to `draft` and receive generated slugs from title.
- Publish workflow sets `status = published` and `published_at` when first published.
- Unpublish workflow sets `status = draft` without deleting content.
- Delete workflow uses soft delete by setting `deleted_at`.
- Do not expose draft content through public list/detail endpoints.

### Project Structure Notes

- RBAC helpers: `backend/app/core/rbac.py`.
- Backend API: `backend/app/api/v1/blog.py`.
- Blog schemas: `backend/app/schemas/blog.py`.
- Backend tests: `backend/tests/test_admin_blog_workflow.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 3.3 acceptance criteria.
- `_bmad-output/implementation-artifacts/3-1-public-blog-listing-and-detail-pages.md`.
- `_bmad-output/implementation-artifacts/3-2-category-tag-and-search-support.md`.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_admin_blog_workflow.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added content-role RBAC guard.
- Added admin blog endpoints for create, list, preview, update, publish, unpublish, and soft delete.
- Added tests for workflow and authorization.

### File List

- `backend/app/core/rbac.py`
- `backend/app/api/v1/blog.py`
- `backend/tests/test_admin_blog_workflow.py`
- `_bmad-output/implementation-artifacts/3-3-admin-blog-crud-and-publishing-workflow.md`
- `_bmad-output/implementation-artifacts/3-3-admin-blog-crud-and-publishing-workflow-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
