# Architecture Decision Records

ADRs live in this directory and record decisions that affect architecture, persistence, security, compliance, deployment, or operations.

## Naming Convention

Use sequential numbers and short kebab-case titles:

```text
NNNN-short-kebab-case-title.md
```

Example:

```text
0001-use-modular-monolith-for-mvp.md
```

## Required Sections

Each ADR should contain:

- **Title**
- **Status**
- **Context**
- **Decision**
- **Consequences**
- **Supersedes / Superseded by** when applicable

## Status Values

- **Proposed:** under review.
- **Accepted:** current project decision.
- **Superseded:** replaced by a newer ADR.
- **Rejected:** considered but not adopted.

## Change Rule

Do not rewrite accepted ADRs to change history. Add a new ADR that supersedes the previous decision.
