# ai-for-investor

`ai-for-investor` is an AI trading and investing open-source project curation, tutorial, controlled tool demo, and community discussion platform.

The MVP focuses on education, research, content discovery, community discussion, and low-risk tool experiences. It does not provide investment advice, return promises, real trading execution, broker or exchange account binding, user fund handling, or arbitrary user code execution.

## Repository Structure

```text
.
├── backend/                     # FastAPI backend
├── frontend/                    # Nuxt 3 frontend
├── docs/迭代01/                 # Iteration 01 product, design, and acceptance docs
├── _bmad-output/
│   ├── planning-artifacts/      # BMad planning outputs
│   └── implementation-artifacts/ # BMad implementation tracking outputs
└── docker-compose.yml           # Local MySQL, MongoDB, Redis, backend, frontend stack
```

## Current MVP Baseline

- **Frontend:** Nuxt 3, Vue 3, TypeScript, Pinia.
- **Backend:** FastAPI, SQLAlchemy async, Motor, Redis, structured logging.
- **Datastores:** MySQL, MongoDB, Redis.
- **Deployment baseline:** Docker Compose for local development; Tencent Cloud deployment is planned.
- **BMad outputs:** Epic/story baseline is in `_bmad-output/planning-artifacts/epics.md`; sprint tracking is in `_bmad-output/implementation-artifacts/sprint-status.yaml`.

## Local Setup

### Backend

From `backend/`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

OpenAPI docs:

```text
http://localhost:8000/docs
```

### Frontend

From `frontend/`:

```bash
npm install
npm run dev
```

Default local URL:

```text
http://localhost:3000
```

### Docker Compose

From the repository root:

```bash
docker compose up --build
```

This starts MySQL, MongoDB, Redis, backend, and frontend. The backend container reads service connection values from `docker-compose.yml`.

## Environment Configuration

Backend configuration is documented in `backend/.env.example`.

Required local values include:

- **`SECRET_KEY`:** backend token/session signing secret.
- **`MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`:** MySQL connection settings.
- **`MONGODB_URL`, `MONGODB_DATABASE`:** MongoDB connection settings.
- **`REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`:** Redis connection settings.

Optional integration values include:

- **`GITHUB_TOKEN`:** GitHub discovery workflow.
- **`TENCENT_COS_*`:** object storage.
- **`SENTRY_DSN`:** error monitoring.

## Database Initialization and Migrations

The MVP backend architecture is a modular monolith with async workers. The architecture baseline and ADR convention live in `docs/architecture/README.md`, and database change rules live in `docs/architecture/migration-policy.md`.

The current development bootstrap script is:

```bash
python init_db.py
```

Run it from `backend/` after MySQL is available and `.env` is configured.

`init_db.py` is a development bootstrap only. It creates local tables from SQLAlchemy metadata during early MVP work and is not a replacement for production migrations.

Current migration policy:

- **Alembic is initialized with baseline revision `20260501_0001_initial_schema_baseline`.**
- **New database changes require migrations or an explicit documented temporary exception.**
- **Before production deployment, apply the baseline to a controlled environment and use new Alembic revisions for subsequent schema changes.**
- **Sprint work items that change schema must include migration and rollback acceptance criteria.**

Alembic commands run from `backend/` after `.env` is configured:

```bash
alembic upgrade head
alembic downgrade -1
```

## Quality Checks

### Project Baseline

From the repository root:

```bash
python3 scripts/quality_check.py --timeout 120
```

This checks required files, README sections, backend requirements, frontend scripts, Docker Compose services, BMad artifacts, and sprint status values.

Optional checks can run the underlying backend or frontend commands with the same timeout guard:

```bash
python3 scripts/quality_check.py --timeout 120 --run-backend-tests
python3 scripts/quality_check.py --timeout 120 --run-frontend-lint
python3 scripts/quality_check.py --timeout 120 --run-frontend-typecheck
python3 scripts/quality_check.py --timeout 120 --run-frontend-build
```

### Backend

From `backend/`:

```bash
pytest
pytest --cov=app
```

### Frontend

From `frontend/`:

```bash
npm run lint
npm run typecheck
npm run build
```

## Documentation

Primary planning documents are in `docs/迭代01/`:

- **`00-文档体系与迭代开发流程.md`:** process, document system, Definition of Ready, Definition of Done.
- **`01-业务需求文档BRD.md`:** business goals and scope.
- **`02-产品需求文档PRD.md`:** product requirements.
- **`03-软件需求规格说明书SRS.md`:** software requirements.
- **`04-技术设计文档.md`:** architecture and technical design.
- **`05-验收测试与上线验收文档.md`:** acceptance and launch checks.
- **`06-需求追踪矩阵RTM.md`:** requirement traceability.
- **`07-论坛UI设计规范与主题系统.md`:** forum UI and theme system.

## BMad Recommended Next Steps

Current state:

- **Planning docs exist:** PRD, SRS, technical design, acceptance tests, RTM, and UI spec are available.
- **Implementation tracking now exists:** `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- **Next actionable workflow:** create the first implementation story from Epic 1.

Recommended sequence:

1. **`bmad-check-implementation-readiness`** — validate alignment across PRD, architecture, epics, and stories.
2. **`bmad-create-story`** — create Story 1.1 or Story 1.3 as the first ready-for-dev story.
3. **`bmad-dev-story`** — implement the selected story.
4. **`bmad-code-review`** — review implemented changes before marking done.

Suggested first story:

- **Story 1.3: Development Environment and Quality Commands**

Reason:

- It directly addresses the previous README gap.
- It prepares contributors and agents for reliable future development.
- It can also capture the migration gap as an explicit follow-up instead of letting it remain implicit.
