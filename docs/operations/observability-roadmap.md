# Observability Roadmap

## Purpose

This roadmap defines the path from MVP in-process observability to production-grade monitoring for public beta and post-beta operations.

## Current MVP State

The backend exposes lightweight operational snapshots through `/api/v1/admin/observability`:

- API request volume, latency, and error rate snapshot.
- Worker queue backlog, running jobs, failed jobs, and total jobs.
- Email delivery attempt and failure counters.
- Database and storage health placeholders.
- Alert summaries for API, worker, email, database, and storage conditions.

This is sufficient for a controlled public beta readiness review, but it is not production-grade because in-process metrics reset on restart and are not retained centrally.

## Public Beta Entry Requirements

Before opening public beta, the release owner must record:

1. Deployment target.
2. Monitoring owner.
3. Admin account verification for `/api/v1/admin/observability`.
4. Incident communication channel.
5. Where logs, backup artifacts, restore drill records, and release notes are stored.

## Production-Grade Direction

### Metrics

Preferred path:

- Export API, worker, email, database, and storage metrics to Prometheus-compatible or managed cloud monitoring.
- Track latency percentiles, request rate, error rate, queue backlog, job failure rate, email failure rate, and storage/database health.
- Preserve the admin observability endpoint as a human-readable operations summary.

### Logs

Preferred path:

- Continue structured logging with request IDs.
- Route backend and worker logs to a centralized log store.
- Ensure logs include request ID, user ID where safe, route/action, status, and safe error details.
- Do not log passwords, tokens, secrets, private user content, or raw third-party credentials.

### Tracing

Preferred path:

- Add OpenTelemetry once deployment target is finalized.
- Trace API request, database query, Redis, GitHub discovery, worker job, and email delivery boundaries.
- Use request ID as the bridge between logs, traces, and API responses.

### Alerting

Minimum alert categories:

- API error rate above threshold.
- API latency above threshold.
- Worker queue backlog above threshold.
- Tool job failure or timeout spike.
- Email delivery failure spike.
- Database or Redis unavailable.
- Backup or restore readiness check failure.

## Post-Beta Implementation Sequence

1. Select monitoring backend based on deployment target.
2. Add metrics exporter or managed monitoring integration.
3. Add centralized log shipping and retention policy.
4. Add alert rules with named owners and escalation channel.
5. Add OpenTelemetry traces for API, worker, and external integrations.
6. Add synthetic smoke checks for `/health`, public pages, and admin observability.
7. Review observability gaps after the first public beta incident or operational drill.

## Ownership Checklist

| Area | Required Owner Before Public Beta | Evidence |
|---|---|---|
| Monitoring backend | yes | Deployment/monitoring ownership record |
| Alert response | yes | Incident communication channel |
| Log retention | yes | Log storage location |
| Admin observability verification | yes | Actual admin account test result |
| Backup/restore monitoring | yes | Restore drill record |

## Safety Boundaries

Observability must preserve the MVP safety boundary:

- No secrets in logs or metrics.
- No user fund, broker, or exchange account data because these integrations are out of scope.
- No personalized investment advice in generated operational summaries.
- No arbitrary user code execution telemetry because arbitrary execution is not enabled.
