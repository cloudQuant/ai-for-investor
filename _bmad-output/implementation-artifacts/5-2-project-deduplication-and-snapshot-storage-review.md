# Code Review: Story 5.2 Project Deduplication and Snapshot Storage

**Date:** 2026-04-30  
**Story:** `_bmad-output/implementation-artifacts/5-2-project-deduplication-and-snapshot-storage.md`  
**Review mode:** full  
**Decision:** Approved

## Scope Reviewed

- `backend/app/models/discovery.py`
- `backend/app/models/__init__.py`
- `backend/init_db.py`
- `backend/app/services/github_discovery.py`
- `backend/tests/test_project_deduplication_snapshots.py`
- `_bmad-output/implementation-artifacts/5-2-project-deduplication-and-snapshot-storage.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Acceptance Audit

| Acceptance Criterion | Result | Evidence |
|---|---|---|
| Duplicate repositories are not inserted as separate projects. | Pass | `collect_github_projects` queries existing `OpenSourceProject` by `repo_full_name` before adding a project. |
| Project snapshots store repository metadata, README summary fields, license signal, and update timestamps when available. | Pass | `ProjectSnapshot` stores repo metadata, topics, raw payload, `readme_summary`, `license_signal`, and commit/release timestamps. |
| Snapshot history can support trend analysis later. | Pass | Every collection attempt can add a timestamped `ProjectSnapshot` with stars/forks/topics and `collected_at`. |
| Failed snapshot collection can retry safely. | Pass | Failed collection adds a `ProjectSnapshot` with `status='failed'`, sanitized `error_detail`, and `retry_count=0`. |
| Storage model separates raw snapshots from reviewed public project records. | Pass | Raw collection history lives in `project_snapshots`; reviewed records remain in `open_source_projects`. |

## Verification Evidence

Commands run from repository root:

```bash
python3 - <<'PY'
import subprocess, sys
completed = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_project_deduplication_snapshots.py', '-vv'], cwd='backend', text=True, capture_output=True, timeout=120, check=False)
print(completed.stdout)
print(completed.stderr)
raise SystemExit(completed.returncode)
PY
```

```bash
python3 scripts/quality_check.py --timeout 120 --run-backend-tests
```

Observed result:

```text
tests/test_project_deduplication_snapshots.py: 4 passed
PASS cmd:backend:pytest: ============================== 98 passed in 2.77s ==============================
SUMMARY total=96 passed=96 failed=0
```

## Findings

### Patched During Story

1. **No raw snapshot history table**
   - Location: `backend/app/models/discovery.py`
   - Fix: added `ProjectSnapshot` separated from `OpenSourceProject`.

2. **Collection inserted projects without deduplication**
   - Location: `backend/app/services/github_discovery.py`
   - Fix: checks existing `OpenSourceProject.repo_full_name` before adding a new project record.

3. **Failure history was audit-only and not retry-oriented**
   - Location: `backend/app/services/github_discovery.py`
   - Fix: records failed snapshots with `status='failed'`, `error_detail`, and `retry_count=0`.

## Review Conclusion

Story 5.2 satisfies all acceptance criteria and is approved. Recommended next item: Story 5.3 Project Scoring and Human Review.
