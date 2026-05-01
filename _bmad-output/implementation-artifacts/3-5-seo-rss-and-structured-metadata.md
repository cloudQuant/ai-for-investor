# Story 3.5: SEO, RSS, and Structured Metadata

Status: ready-for-dev

## Story

As a content operator,  
I want articles to produce SEO metadata and feeds,  
so that content can be discovered through search and syndication.

## Acceptance Criteria

1. Published posts expose canonical metadata.
2. Published posts expose Open Graph metadata.
3. Published posts are included in RSS output.
4. Public pages support basic structured data where applicable.
5. Sitemap generation or documented sitemap path includes published content.

## Tasks / Subtasks

- [x] Add tests for canonical, Open Graph, and structured data in post detail responses. (AC: 1, 2, 4)
- [x] Add tests for RSS and sitemap output containing published posts. (AC: 3, 5)
- [x] Implement backend SEO metadata helpers and response fields. (AC: 1, 2, 4)
- [x] Implement RSS and sitemap XML endpoints. (AC: 3, 5)
- [x] Update frontend blog detail head metadata, canonical link, and JSON-LD. (AC: 1, 2, 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Published-only filtering must remain enforced for RSS and sitemap output.
- Use configurable site URL defaults for canonical links and feed URLs.
- Frontend should consume backend-provided metadata where available.
- Structured data should avoid investment advice or return claims.

### Project Structure Notes

- Backend config: `backend/app/core/config.py`.
- Backend API: `backend/app/api/v1/blog.py`.
- Backend tests: `backend/tests/test_public_blog.py`.
- Frontend config: `frontend/nuxt.config.ts`.
- Frontend display/head: `frontend/pages/blog/[slug].vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 3.5 acceptance criteria.
- `_bmad-output/implementation-artifacts/3-4-markdown-rendering-and-content-safety.md`.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_public_blog.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added configurable backend `SITE_URL` and frontend `siteUrl`.
- Added canonical URL, Open Graph metadata, and Article JSON-LD structured data to blog detail responses.
- Added RSS feed endpoint at `/api/v1/blog/rss.xml`.
- Added sitemap endpoint at `/api/v1/blog/sitemap.xml`.
- Updated frontend blog detail page to emit canonical link, Open Graph/Twitter metadata, and JSON-LD.
- Added tests covering metadata, RSS, and sitemap output.

### File List

- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/app/api/v1/blog.py`
- `backend/tests/test_public_blog.py`
- `frontend/nuxt.config.ts`
- `frontend/pages/blog/[slug].vue`
- `_bmad-output/implementation-artifacts/3-5-seo-rss-and-structured-metadata.md`
- `_bmad-output/implementation-artifacts/3-5-seo-rss-and-structured-metadata-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
