# Story 3.4: Markdown Rendering and Content Safety

Status: ready-for-dev

## Story

As a reader,  
I want readable Markdown content with code highlighting while staying protected from unsafe markup.

## Acceptance Criteria

1. Markdown content renders headings, lists, links, code blocks, and tables.
2. Rendered Markdown is sanitized against XSS.
3. External links are handled safely.
4. Code blocks are readable on supported themes.
5. Unsafe HTML or scripts do not execute in published articles.

## Tasks / Subtasks

- [x] Add tests for Markdown rendering output. (AC: 1, 4)
- [x] Add tests for sanitization and safe external links. (AC: 2, 3, 5)
- [x] Implement backend Markdown-to-safe-HTML rendering. (AC: 1, 2, 3, 4, 5)
- [x] Expose rendered content in blog detail and preview responses. (AC: 1, 2, 3, 4, 5)
- [x] Update frontend blog detail page to render sanitized HTML. (AC: 1, 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Backend dependencies already include `markdown`, `bleach`, `markdown-it-py`, and `Pygments`.
- Prefer server-side Markdown rendering and sanitization so API consumers receive consistent safe HTML.
- Keep raw Markdown `content` available for management/editing workflows.
- Public blog detail and management preview should include sanitized `rendered_content`.
- Unsafe HTML attributes, script tags, and `javascript:` URLs must not survive rendering.

### Project Structure Notes

- Backend renderer/API: `backend/app/api/v1/blog.py`.
- Backend tests: `backend/tests/test_public_blog.py`.
- Frontend display: `frontend/pages/blog/[slug].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 3.4 acceptance criteria.
- `_bmad-output/implementation-artifacts/3-3-admin-blog-crud-and-publishing-workflow.md`.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_public_blog.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added backend Markdown rendering with `markdown` extensions for headings, lists, links, code blocks, and tables.
- Added sanitization with an explicit HTML tag/attribute/protocol allowlist.
- Added safe external link handling with `rel="noopener noreferrer"` and `target="_blank"`.
- Exposed `rendered_content` in blog detail and management preview responses.
- Updated frontend blog detail display and styles for Markdown content, code blocks, and tables.

### File List

- `backend/app/api/v1/blog.py`
- `backend/tests/test_public_blog.py`
- `frontend/pages/blog/[slug].vue`
- `_bmad-output/implementation-artifacts/3-4-markdown-rendering-and-content-safety.md`
- `_bmad-output/implementation-artifacts/3-4-markdown-rendering-and-content-safety-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
