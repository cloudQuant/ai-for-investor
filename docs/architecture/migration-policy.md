# Migration Policy

## Rule

Every schema-changing backend story must include one of the following before it can be marked done:

- **Migration:** a forward migration plus rollback guidance.
- **Temporary exception:** an explicit documented exception explaining why a migration is deferred, the risk, owner, and follow-up story.

## Scope

This policy applies to changes that add, remove, rename, or alter:

- MySQL tables, columns, indexes, constraints, or seed data required by application logic.
- MongoDB collections, indexes, document contracts, or required seed records.
- Redis key formats that affect compatibility, retention, or cleanup behavior.

## Development Bootstrap

`backend/init_db.py` may create local development tables from SQLAlchemy metadata during early MVP work.

It must not be treated as a production migration system because it does not provide:

- ordered migration history,
- reversible rollback steps,
- production change review,
- zero-downtime deployment guidance,
- auditability for incremental schema changes.

## Sprint Acceptance Criteria for Schema Changes

Any sprint work item that changes schema must include acceptance criteria covering:

1. Forward migration or documented temporary exception.
2. Rollback guidance or explicit non-rollback rationale.
3. A verification command or test that proves the target schema state.
4. Data compatibility note for existing development or production data.
5. Operational risk note when the change affects availability or data integrity.

## Alembic Direction

Alembic is the migration path for MySQL schema changes.

The baseline revision is `20260501_0001_initial_schema_baseline`.

After the baseline is applied to a controlled environment, future schema-changing stories must create a new Alembic revision instead of editing the baseline. Each new revision must include downgrade guidance or an explicit non-rollback rationale.
