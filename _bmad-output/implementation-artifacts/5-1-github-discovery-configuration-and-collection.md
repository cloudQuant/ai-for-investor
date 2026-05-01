# Story 5.1: GitHub Discovery Configuration and Collection

Status: ready-for-dev

## Story

As an editor,  
I want configurable GitHub discovery keywords,  
so that the system can collect relevant projects for review.

## Acceptance Criteria

1. Admin or editor can configure discovery keywords.
2. Discovery job queries GitHub using configured keywords.
3. GitHub API token is read from environment configuration.
4. Collection handles GitHub API rate limits gracefully.
5. Discovery failures record safe error details for review.

## Tasks / Subtasks

- [x] Add editor/admin protected discovery keyword configuration endpoints. (AC: 1)
- [x] Add GitHub discovery client that reads token from environment settings. (AC: 2, 3)
- [x] Add discovery collection job endpoint using active keywords. (AC: 2)
- [x] Handle GitHub rate limits without crashing collection. (AC: 4)
- [x] Record safe audit details for collection failures. (AC: 5)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Existing discovery models include `DiscoveryKeyword` and `OpenSourceProject`.
- Existing config already includes `GITHUB_TOKEN`.
- Story 5.2 will handle deduplication and snapshot storage in more depth; Story 5.1 should only provide safe initial collection into reviewable project records.
- GitHub API failures must not expose secrets or raw authorization headers.

### Project Structure Notes

- Backend API: `backend/app/api/v1/open_source.py`.
- Backend service: `backend/app/services/github_discovery.py`.
- Backend tests: `backend/tests/test_github_discovery_configuration.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 5.1 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_github_discovery_configuration.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added editor/admin protected discovery keyword list and create endpoints.
- Added GitHub discovery client and collection service that reads `GITHUB_TOKEN` from environment settings.
- Added active keyword collection into pending project records.
- Added graceful rate limit handling.
- Added sanitized audit logging for discovery failures.

### File List

- `backend/app/api/v1/open_source.py`
- `backend/app/services/github_discovery.py`
- `backend/tests/test_github_discovery_configuration.py`
- `_bmad-output/implementation-artifacts/5-1-github-discovery-configuration-and-collection.md`
- `_bmad-output/implementation-artifacts/5-1-github-discovery-configuration-and-collection-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
