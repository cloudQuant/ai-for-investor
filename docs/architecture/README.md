# Architecture Baseline

## MVP Architecture

The MVP architecture is a modular monolith backend with async workers.

- **Backend API:** FastAPI exposes REST endpoints under `/api/v1/*`.
- **Relational data:** MySQL stores transactional entities that require relational integrity.
- **Document data:** MongoDB stores document-style and discovery-oriented records where flexible shape is useful.
- **Cache and transient state:** Redis stores rate-limit counters, short-lived tokens, and queue/cache state.
- **Async workers:** background work should run outside request handlers when tasks are long-running, scheduled, or integration-heavy.
- **Frontend:** Nuxt 3 consumes backend APIs through the documented API boundary.

## Architecture Decision Records

Architecture decisions are tracked in `docs/architecture/adr/`.

Use numbered markdown files with this naming convention:

```text
NNNN-short-kebab-case-title.md
```

Each ADR should include:

- **Status:** proposed, accepted, superseded, or rejected.
- **Context:** the forces and constraints behind the decision.
- **Decision:** the chosen approach.
- **Consequences:** tradeoffs, risks, and operational impact.
- **Supersedes / Superseded by:** links when a decision changes.

## Migration Baseline

Database change rules are defined in `docs/architecture/migration-policy.md`.

`backend/init_db.py` is a development bootstrap only. It is not a replacement for production migrations.
