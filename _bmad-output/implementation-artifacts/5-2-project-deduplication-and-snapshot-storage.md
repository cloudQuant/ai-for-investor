# Story 5.2: Project Deduplication and Snapshot Storage

Status: ready-for-dev

## Story

As an editor,  
I want collected projects deduplicated and snapshotted,  
so that project history and freshness can be evaluated.

## Acceptance Criteria

1. Duplicate repositories are not inserted as separate projects.
2. Project snapshots store repository metadata, README summary fields, license signal, and update timestamps when available.
3. Snapshot history can support trend analysis later.
4. Failed snapshot collection can retry safely.
5. Storage model separates raw snapshots from reviewed public project records.

## Tasks / Subtasks

- [x] Add project snapshot storage model separated from public project records. (AC: 2, 3, 5)
- [x] Deduplicate repository collection by `repo_full_name`. (AC: 1)
- [x] Store repository metadata and README/license/update snapshot fields. (AC: 2, 3)
- [x] Record failed snapshot attempts in retryable form. (AC: 4)
- [x] Run quality verification with timeout. (AC: 1, 2, 3, 4, 5)
- [x] Generate code review report and update sprint status. (AC: 1, 2, 3, 4, 5)

## Dev Notes

- Story 5.1 introduced initial GitHub discovery collection and pending project records.
- Story 5.2 should separate raw snapshot history from reviewed/public `OpenSourceProject` records.
- Duplicate handling should avoid creating multiple `OpenSourceProject` rows for the same repository.
- Snapshot failures must keep sanitized error details and remain safe to retry.

### Project Structure Notes

- Backend model: `backend/app/models/discovery.py`.
- Backend service: `backend/app/services/github_discovery.py`.
- Backend tests: `backend/tests/test_project_deduplication_snapshots.py`.
- Sprint status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.

### References

- `_bmad-output/planning-artifacts/epics.md` — Story 5.2 acceptance criteria.

## Dev Agent Record

### Agent Model Used

Cascade

### Debug Log References

- `python3 - <<'PY' ... pytest tests/test_project_deduplication_snapshots.py -vv ... PY`
- `python3 scripts/quality_check.py --timeout 120 --run-backend-tests`

### Completion Notes List

- Added `ProjectSnapshot` as raw snapshot storage separated from public project records.
- Updated discovery collection to avoid duplicate `OpenSourceProject` inserts by `repo_full_name`.
- Added success snapshots containing repository metadata, README summary, license signal, and update timestamps.
- Added retryable failed snapshots with sanitized error detail and retry count.

### File List

- `backend/app/models/discovery.py`
- `backend/app/models/__init__.py`
- `backend/init_db.py`
- `backend/app/services/github_discovery.py`
- `backend/tests/test_project_deduplication_snapshots.py`
- `_bmad-output/implementation-artifacts/5-2-project-deduplication-and-snapshot-storage.md`
- `_bmad-output/implementation-artifacts/5-2-project-deduplication-and-snapshot-storage-review.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
