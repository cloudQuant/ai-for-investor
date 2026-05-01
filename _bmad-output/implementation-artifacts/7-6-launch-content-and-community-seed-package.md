# Story 7.6: Launch Content and Community Seed Package

Status: ready-for-dev

## Story

As a content operator,  
I want launch-ready seed content and discussions,  
so that the public beta does not feel empty.

## Acceptance Criteria

1. Homepage has selected launch content.
2. At least 10 blog posts or drafts are prepared for launch operations.
3. At least 20 forum seed topics are prepared.
4. At least 3 to 5 tools are configured as runnable, external, or documentation-only entries.
5. First AI trading and investing open-source weekly report is ready to publish.

## Tasks / Subtasks

- [x] Create launch content package with homepage selected content. (AC: 1)
- [x] Prepare at least 10 blog posts or drafts. (AC: 2)
- [x] Reference or include at least 20 forum seed topics. (AC: 3)
- [x] Configure 3 to 5 launch tool entries. (AC: 4)
- [x] Prepare first AI trading and investing open-source weekly report. (AC: 5)
- [x] Add automated structure tests. (AC: 1, 2, 3, 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Launch content must preserve education/research boundaries and avoid investment advice, return promises, or real trading instructions.
- Existing Story 3.6 editorial package and Story 4.6 forum seed package can be reused as source material.

### Project Structure Notes

- Launch package: `_bmad-output/implementation-artifacts/7-6-launch-content-and-community-seed-package-package.md`.
- Test coverage: `backend/tests/test_launch_content_seed_package.py`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 7.6 acceptance criteria.
- `_bmad-output/implementation-artifacts/3-6-seed-content-and-editorial-templates-package.md`.
- `_bmad-output/implementation-artifacts/4-6-community-rules-and-seed-discussion-plan-package.md`.
- `backend/app/content/forum_seed.py`.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_launch_content_seed_package.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added launch package with homepage selected launch content slots.
- Prepared 11 blog drafts including the first weekly report.
- Reused and referenced 24 forum seed topics from `backend/app/content/forum_seed.py`.
- Prepared 5 launch tool entries across runnable, external, and documentation-only entry types.
- Prepared first AI trading and investing open-source weekly report as ready-to-publish.
- Added automated structure tests validating all Story 7.6 acceptance criteria and compliance boundaries.

### File List

- `_bmad-output/implementation-artifacts/7-6-launch-content-and-community-seed-package.md`
- `_bmad-output/implementation-artifacts/7-6-launch-content-and-community-seed-package-package.md`
- `_bmad-output/implementation-artifacts/7-6-launch-content-and-community-seed-package-review.md`
- `backend/tests/test_launch_content_seed_package.py`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
