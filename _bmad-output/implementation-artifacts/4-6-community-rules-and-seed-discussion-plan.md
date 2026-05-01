# Story 4.6: Community Rules and Seed Discussion Plan

Status: ready-for-dev

## Story

As a community operator,  
I want rules and seed discussion topics,  
so that the forum can avoid an empty launch.

## Acceptance Criteria

1. Community rules define prohibited financial advice, spam, abusive behavior, and unsafe tool claims.
2. Default categories cover project discussion, strategy research, tools, data/backtesting, beginner Q&A, and site feedback.
3. At least 20 seed discussion topics are prepared.
4. Key articles can link to associated discussion threads.
5. Community guidance explains how to ask high-quality strategy and tool questions.

## Tasks / Subtasks

- [x] Add a testable forum seed content package. (AC: 1, 2, 3, 4, 5)
- [x] Prepare default forum category definitions. (AC: 2)
- [x] Prepare at least 20 launch seed discussion topics. (AC: 3)
- [x] Include article-to-thread linking guidance. (AC: 4)
- [x] Add a public forum rules and question guidance page. (AC: 1, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Content should preserve platform compliance boundaries: no personalized investment advice, no trading instructions, no return promises, and no unsafe tool claims.
- Seed discussions should support AI trading and investing education while remaining research-only.
- Default categories should align with public browsing and creation flows from Stories 4.1 and 4.2.

### Project Structure Notes

- Backend seed content: `backend/app/content/forum_seed.py`.
- Backend tests: `backend/tests/test_forum_seed_content.py`.
- Frontend page: `frontend/pages/forum/rules.vue`.
- Forum index entry point: `frontend/pages/forum/index.vue`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 4.6 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_forum_seed_content.py -vv ... PY`
- `python3 - <<'PY' ... npm run typecheck ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added structured community rules covering prohibited investment advice, spam, abusive behavior, and unsafe tool claims.
- Added six default category definitions covering all required forum launch areas.
- Added 24 seed discussion topics across all default categories.
- Added article-to-thread linking guidance using `discussion_thread_id`.
- Added public `/forum/rules` guidance and linked it from the forum index.

### File List

- `backend/app/content/__init__.py`
- `backend/app/content/forum_seed.py`
- `backend/tests/test_forum_seed_content.py`
- `frontend/pages/forum/rules.vue`
- `frontend/pages/forum/index.vue`
- `_bmad-output/implementation-artifacts/4-6-community-rules-and-seed-discussion-plan.md`
- `_bmad-output/implementation-artifacts/4-6-community-rules-and-seed-discussion-plan-package.md`
- `_bmad-output/implementation-artifacts/4-6-community-rules-and-seed-discussion-plan-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
