# Backup, Restore, and Rollback Runbook

## Scope

This runbook covers MVP launch readiness for AI For Investor services using the current Docker Compose baseline:

- MySQL application database
- MongoDB document/content store
- Redis cache/session/rate-limit store
- Optional Tencent COS object storage
- Backend and frontend application deployment rollback

## Database Backup Strategy

### MySQL

- **Frequency:** daily snapshot before public beta; manual snapshot before each release.
- **Command pattern:** `mysqldump --single-transaction --routines --triggers --databases <database> > backups/mysql/<timestamp>.sql`.
- **Retention:** keep at least 7 daily backups and every release backup until the next stable release.
- **Integrity check:** verify the dump file is non-empty and contains schema plus data statements.
- **Security:** store backups outside the application container and restrict access to operators only.

### MongoDB

- **Frequency:** daily snapshot before public beta; manual snapshot before each release.
- **Command pattern:** `mongodump --uri <mongodb-url> --db <database> --out backups/mongodb/<timestamp>`.
- **Retention:** keep at least 7 daily backups and every release backup until the next stable release.
- **Integrity check:** verify collection BSON files and metadata files exist for expected collections.
- **Security:** store dumps outside the application container and restrict access to operators only.

### Redis

- **Scope:** Redis stores cache, token blacklist, verification/reset tokens, and rate-limit counters.
- **Backup assumption:** Redis data is non-authoritative for MVP recovery. A restart may invalidate short-lived sessions or tokens but should not lose source-of-truth data.
- **Optional snapshot:** if session continuity becomes required, enable Redis RDB/AOF snapshots and archive `/data` volume snapshots with release backups.

## File/Object Storage Backup Assumptions

- MVP object storage is optional and represented by `TENCENT_COS_*` environment values.
- If object storage is enabled, object buckets must use provider-side versioning or lifecycle snapshots before public beta.
- Object backups must include uploaded content, generated assets, and metadata required to map objects back to application records.
- If object storage is not enabled, record this as a launch assumption and verify no production flow depends on non-backed-up object uploads.

## Restore Procedure

### Restore Drill Requirement

A restore procedure must be tested at least once before public beta using a non-production environment.

### Restore Steps

1. Create a fresh environment from the target release image or commit.
2. Stop application workers and background jobs.
3. Restore MySQL from the selected dump into an empty database.
4. Restore MongoDB from the selected dump into an empty database.
5. Restore object storage from provider snapshot if object storage is enabled.
6. Start backend, frontend, and worker processes.
7. Run `/health` and admin observability checks.
8. Run smoke tests covering auth, blog, forum, tools, and open-source project pages.
9. Record restore timestamp, backup source, operator, verification commands, and result.

### Restore Verification Commands

```bash
python3 scripts/backup_restore_rollback_check.py --mode restore-drill --dry-run
python3 scripts/quality_check.py --timeout 120 --run-backend-tests
```

## Deployment Rollback Procedure

1. Identify failed release version, previous stable version, and incident owner.
2. Freeze new deployments and pause background workers if data integrity is at risk.
3. If the release is code-only, redeploy the previous stable backend and frontend images or commit.
4. If the release includes schema changes, follow the story-specific migration rollback guidance or documented non-rollback exception.
5. If data corruption is suspected, restore from the latest verified release backup into a clean environment.
6. Run health checks and observability dashboard checks.
7. Announce rollback status and known user impact.
8. Create a follow-up incident note with root cause, affected version, rollback duration, and prevention actions.

## Release Checklist Backup and Rollback Verification

Before public beta or any production release, verify:

- [ ] MySQL backup command, destination, retention, and restore owner are documented.
- [ ] MongoDB backup command, destination, retention, and restore owner are documented.
- [ ] Redis recovery assumption is documented and accepted.
- [ ] Object storage backup assumption or provider snapshot setup is documented.
- [ ] A non-production restore drill has been executed or explicitly scheduled before public beta.
- [ ] Deployment rollback target version is identified.
- [ ] Schema rollback or non-rollback exception is documented for the release.
- [ ] Health, observability, and smoke verification commands are listed.
- [ ] Operators know where backup artifacts and restore drill records are stored.

## Non-Destructive Readiness Check

Use this check to validate the runbook and expected operational artifacts without executing backup, restore, or rollback commands:

```bash
python3 scripts/backup_restore_rollback_check.py --mode readiness --dry-run
```
