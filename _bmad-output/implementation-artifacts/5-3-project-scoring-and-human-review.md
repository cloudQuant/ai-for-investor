# Story 5.3: Project Scoring and Human Review

Status: ready-for-dev

## Story

As an editor,  
I want automatic project scoring with human review,  
so that only credible projects are promoted.

## Acceptance Criteria

1. Automatic scoring uses transparent criteria such as stars, activity, documentation, license, and relevance.
2. Automatic score is marked as an editorial aid, not a recommendation.
3. Editors can set review status values such as new, reviewed, selected, and ignored.
4. Editors can adjust project score notes or review rationale.
5. Public promotion requires human review.

## Tasks / Subtasks

- [x] Add transparent automatic scoring helper. (AC: 1, 2)
- [x] Add editor/admin review endpoint for scores, notes, and status. (AC: 3, 4)
- [x] Validate review status values. (AC: 3)
- [x] Restrict public project listing to human-selected projects. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- `OpenSourceProject` already stores score component fields and status.
- `ProjectScore` stores score history and notes.
- Public pages must avoid implying investment advice or recommendations.
- Automatic scoring should be framed as an editorial aid only.

### Project Structure Notes

- Backend model: `backend/app/models/discovery.py`.
- Backend schemas: `backend/app/schemas/discovery.py`.
- Backend API: `backend/app/api/v1/open_source.py`.
- Backend service: `backend/app/services/project_scoring.py`.
- Backend tests: `backend/tests/test_project_scoring_review.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 5.3 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_project_scoring_review.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added transparent automatic project scoring helper with stars, activity, documentation, license, and relevance criteria.
- Marked automatic scores as editorial aids only, not recommendations.
- Added editor/admin review endpoint for review status, score overrides, score notes, and rationale.
- Restricted public project listing to human-selected projects.

### File List

- `backend/app/services/project_scoring.py`
- `backend/app/schemas/discovery.py`
- `backend/app/api/v1/open_source.py`
- `backend/tests/test_project_scoring_review.py`
- `_bmad-output/implementation-artifacts/5-3-project-scoring-and-human-review.md`
- `_bmad-output/implementation-artifacts/5-3-project-scoring-and-human-review-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
