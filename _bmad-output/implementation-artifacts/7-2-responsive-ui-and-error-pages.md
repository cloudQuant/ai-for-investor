# Story 7.2: Responsive UI and Error Pages

Status: ready-for-dev

## Story

As a visitor,  
I want the site to work on common screen sizes and show clear error pages,  
so that the experience feels production-ready.

## Acceptance Criteria

1. Homepage, blog, forum, tools, project library, auth pages, and user center are responsive.
2. 404 page is available.
3. 500 or generic error page is available.
4. Unauthorized and forbidden states provide clear next actions.
5. Loading, empty, and error states exist for key frontend pages.

## Tasks / Subtasks

- [x] Add project-level error page with 404 and generic error variants. (AC: 2, 3)
- [x] Improve global layout and key pages for mobile widths. (AC: 1)
- [x] Add clear unauthorized/forbidden next-action states. (AC: 4)
- [x] Ensure key frontend pages expose loading, empty, and error states. (AC: 5)
- [x] Add automated structure guard for responsive/error-state requirements. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Prefer minimal CSS changes using the existing theme token system.
- Do not introduce new frontend dependencies for this story.
- Nuxt supports project-level `error.vue` for 404 and generic error rendering.

### Project Structure Notes

- Global layout: `frontend/layouts/default.vue`.
- Error page: `frontend/error.vue`.
- Frontend pages: `frontend/pages/**`.
- Coverage guard: `backend/tests/test_frontend_responsive_error_pages.py`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 7.2 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_frontend_responsive_error_pages.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added project-level Nuxt `error.vue` with 404, 401, 403, and generic error messaging and next actions.
- Improved global layout mobile wrapping and reduced small-screen padding.
- Added mobile breakpoints for homepage, forum, tools, project library, auth pages, and user center.
- Added clear user-center login fallback and kept forum create-page login/register next actions.
- Added empty state for tools listing and normalized frontend error color token usage.
- Added automated structure guard for responsive, error page, unauthorized/forbidden, and loading/empty/error state requirements.

### File List

- `frontend/error.vue`
- `frontend/layouts/default.vue`
- `frontend/pages/index.vue`
- `frontend/pages/forum/index.vue`
- `frontend/pages/tools/index.vue`
- `frontend/pages/tools/[slug].vue`
- `frontend/pages/tools/jobs/index.vue`
- `frontend/pages/tools/jobs/[job_id].vue`
- `frontend/pages/open-source/index.vue`
- `frontend/pages/open-source/[id].vue`
- `frontend/pages/auth/login.vue`
- `frontend/pages/auth/register.vue`
- `frontend/pages/auth/password-reset.vue`
- `frontend/pages/user/index.vue`
- `backend/tests/test_frontend_responsive_error_pages.py`
- `_bmad-output/implementation-artifacts/7-2-responsive-ui-and-error-pages.md`
- `_bmad-output/implementation-artifacts/7-2-responsive-ui-and-error-pages-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
