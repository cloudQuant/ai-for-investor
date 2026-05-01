# Story 5.5: Weekly Report Candidate Pool

Status: ready-for-dev

## Story

As an editor,  
I want to add selected projects to a weekly report candidate pool,  
so that weekly content can be produced consistently.

## Acceptance Criteria

1. Editors can add reviewed projects to a weekly report candidate pool.
2. Candidate pool records selection rationale and editorial notes.
3. Candidate pool can be filtered by week or status.
4. At least one weekly report can be assembled from selected candidates.
5. Candidate tools show license and security review signals before promotion.

## Tasks / Subtasks

- [x] Add candidate pool create and update schemas. (AC: 1, 2, 3)
- [x] Add candidate model fields for rationale, editorial notes, and status. (AC: 2, 3)
- [x] Add editor/admin candidate pool create/list/update endpoints. (AC: 1, 2, 3, 5)
- [x] Add weekly report assembly endpoint from selected candidates. (AC: 4, 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Candidate projects must already be human-selected before entering weekly promotion workflow.
- Candidate responses should surface license and security score signals before editorial promotion.
- Weekly report assembly is an editorial package and must avoid investment advice framing.

### Project Structure Notes

- Backend API: `backend/app/api/v1/open_source.py`.
- Backend model: `backend/app/models/discovery.py`.
- Backend schema: `backend/app/schemas/discovery.py`.
- Backend tests: `backend/tests/test_weekly_report_candidate_pool.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 5.5 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_weekly_report_candidate_pool.py -vv ... PY`
- `python3 - <<'PY' ... pytest tests/test_github_discovery_configuration.py tests/test_project_deduplication_snapshots.py tests/test_project_scoring_review.py tests/test_public_project_library.py tests/test_weekly_report_candidate_pool.py -q ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added weekly report candidate create and update schemas.
- Added content-role protected candidate create, list, and update endpoints.
- Candidate creation requires a human-selected project.
- Candidate list can filter by week, year, and status.
- Weekly report assembly returns selected candidates with license and security score signals.

### File List

- `backend/app/models/discovery.py`
- `backend/app/schemas/discovery.py`
- `backend/app/api/v1/open_source.py`
- `backend/tests/test_weekly_report_candidate_pool.py`
- `_bmad-output/implementation-artifacts/5-5-weekly-report-candidate-pool.md`
- `_bmad-output/implementation-artifacts/5-5-weekly-report-candidate-pool-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
