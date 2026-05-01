---
title: ai-for-investor MVP Epics and Stories
project: ai-for-investor
status: planning-baseline
source_documents:
  - docs/迭代01/02-产品需求文档PRD.md
  - docs/迭代01/03-软件需求规格说明书SRS.md
  - docs/迭代01/04-技术设计文档.md
  - docs/迭代01/05-验收测试与上线验收文档.md
  - docs/迭代01/06-需求追踪矩阵RTM.md
  - docs/迭代01/产品调研与迭代计划.md
stepsCompleted:
  - bmad-help-gap-analysis
  - epics-and-stories-baseline
---

# ai-for-investor MVP Epics and Stories

This document converts the existing Iteration 01 planning documents into BMad-consumable epics and stories. It keeps the MVP compliance boundary explicit: no real trading APIs, no broker or exchange account binding, no user funds, no investment advice, no return promises, and no arbitrary user code execution.

## Epic 1: Project Foundation and Architecture Baseline

Goal: establish a locally runnable, observable, and maintainable modular monolith foundation for the MVP.

### Story 1.1: Backend Application Skeleton and Health Check

As a developer, I want a FastAPI backend skeleton with a health endpoint and OpenAPI documentation so that the team can verify the service baseline quickly.

Acceptance criteria:

1. FastAPI application starts with the configured app name and version.
2. `GET /health` returns service status, app name, and version.
3. OpenAPI documentation is available in the local backend environment.
4. API routers follow the `/api/v1/*` prefix convention.
5. Unhandled exceptions return a structured error with `request_id`.

### Story 1.2: Database and Cache Connectivity Baseline

As a developer, I want MySQL, MongoDB, and Redis connectivity configured so that later modules can rely on shared persistence and queue infrastructure.

Acceptance criteria:

1. Backend settings load MySQL, MongoDB, and Redis connection values from environment variables.
2. Local Docker Compose exposes MySQL, MongoDB, and Redis with health checks.
3. Backend startup connects to MongoDB and Redis and closes those clients on shutdown.
4. SQLAlchemy async engine is configured for MySQL.
5. Missing required secrets fail fast in development instead of silently using unsafe defaults.

### Story 1.3: Development Environment and Quality Commands

As a contributor, I want documented local setup, test, lint, and build commands so that onboarding and PR checks are repeatable.

Acceptance criteria:

1. README documents backend setup, frontend setup, Docker Compose startup, and health checks.
2. README documents backend test command and frontend lint/typecheck/build commands.
3. README documents required environment files and points to `backend/.env.example`.
4. README documents current database initialization approach and the migration gap.
5. README documents core project compliance boundaries.

### Story 1.4: Request Logging and Request ID Baseline

As an operator, I want request IDs and structured logs so that backend failures can be traced across API responses and logs.

Acceptance criteria:

1. Each HTTP request receives an `X-Request-ID` response header.
2. Structured logging includes the request ID for request-scoped messages.
3. Unhandled exception logs include the request path and error message.
4. Error responses expose a request ID without leaking stack traces.
5. The logging configuration can be adjusted through environment settings.

### Story 1.5: Architecture Decision and Migration Baseline

As a technical lead, I want architecture decision and migration conventions so that data and architecture changes remain auditable.

Acceptance criteria:

1. Project documentation identifies modular monolith plus async workers as the MVP architecture.
2. New database changes require migrations or an explicit documented temporary exception.
3. A location or convention exists for future ADR records.
4. README explains that `init_db.py` is a development bootstrap and not a replacement for production migrations.
5. Sprint work items that change schema include migration and rollback acceptance criteria.

## Epic 2: User System and Basic Permissions

Goal: deliver the authentication and authorization foundation required before write operations, tool usage, forum participation, and admin work.

### Story 2.1: Email Registration and Password Policy

As a visitor, I want to register with email and password so that I can become a verified community user.

Acceptance criteria:

1. Registration accepts email and password and validates email format.
2. Password rules follow configured minimum length and complexity settings.
3. Passwords are hashed with Argon2 or an approved secure hash strategy.
4. Duplicate email registration is rejected safely.
5. Registration responses do not leak sensitive token or password data.

### Story 2.2: Email Verification Flow

As a registered user, I want to verify my email so that I can unlock community and tool actions.

Acceptance criteria:

1. Registration creates an email verification token with an expiry.
2. Verification token values are not stored in plaintext.
3. Verification succeeds only for valid, unexpired tokens.
4. Expired or reused tokens are rejected with a safe error.
5. Unverified users remain blocked from posting, replying, and creating tool jobs.

### Story 2.3: Login, Logout, and Current User Session

As a registered user, I want to log in, log out, and fetch my current session so that the frontend can display correct authenticated state.

Acceptance criteria:

1. Login validates credentials and returns an approved session or token response.
2. Logout invalidates the active session or token according to the selected auth model.
3. Current user endpoint returns user identity, roles, and verification state.
4. Authentication failures use generic error messages.
5. Login attempts are rate limited according to configuration.

### Story 2.4: Password Reset Flow

As a registered user, I want to reset a forgotten password so that I can recover access securely.

Acceptance criteria:

1. Password reset request accepts an email without exposing whether the account exists.
2. Reset tokens expire according to configuration.
3. Reset token values are not stored in plaintext.
4. Password reset applies the same password policy as registration.
5. Used or expired reset tokens cannot be reused.

### Story 2.5: Role-Based Access Control and Admin Bootstrap

As an administrator, I want role-based access checks and bootstrap support so that admin-only actions are protected.

Acceptance criteria:

1. Roles include visitor, registered user, author, editor, moderator, and administrator concepts.
2. Backend dependencies or guards protect admin and moderation endpoints.
3. Admin bootstrap can create an initial administrator account safely.
4. Admin login or admin-sensitive actions produce audit records.
5. Unauthorized and forbidden responses are distinguishable and safe.

### Story 2.6: Authentication Frontend Pages and Route Guards

As a user, I want registration, login, verification result, password reset, and profile entry pages so that authentication flows are usable from the browser.

Acceptance criteria:

1. Frontend includes registration and login forms with validation and error states.
2. Frontend includes email verification result and password reset pages.
3. Frontend stores and clears authenticated state consistently.
4. Protected routes redirect unauthenticated users to login.
5. Unverified users receive clear guidance when trying restricted actions.

## Epic 3: Blog and Content CMS

Goal: establish public content publishing and SEO foundations for AI trading and investing project education.

### Story 3.1: Public Blog Listing and Detail Pages

As a visitor, I want to browse and read published blog posts so that I can learn from curated AI trading and investing content.

Acceptance criteria:

1. Published articles appear on the public blog list.
2. Blog list supports pagination.
3. Blog detail shows title, author, category, tags, content, and publication state.
4. Draft and unpublished articles are not visible to visitors.
5. Blog detail includes risk disclaimer access.

### Story 3.2: Category, Tag, and Search Support

As a visitor, I want to filter and search content so that I can find relevant tutorials, project reviews, and risk methodology articles.

Acceptance criteria:

1. Blog posts support category assignment.
2. Blog posts support multiple tags.
3. Public list can filter by category and tag.
4. Public search supports keyword queries.
5. Empty search and filter states are clear and actionable.

### Story 3.3: Admin Blog CRUD and Publishing Workflow

As an author or administrator, I want to create, preview, publish, update, and unpublish articles so that content operations can run safely.

Acceptance criteria:

1. Authorized users can create and edit article drafts.
2. Authorized users can preview drafts before publication.
3. Authorized users can publish and unpublish articles.
4. Publishing records author, status, and publication timestamps.
5. Unauthorized users cannot access article management actions.

### Story 3.4: Markdown Rendering and Content Safety

As a reader, I want readable Markdown content with code highlighting while staying protected from unsafe markup.

Acceptance criteria:

1. Markdown content renders headings, lists, links, code blocks, and tables.
2. Rendered Markdown is sanitized against XSS.
3. External links are handled safely.
4. Code blocks are readable on supported themes.
5. Unsafe HTML or scripts do not execute in published articles.

### Story 3.5: SEO, RSS, and Structured Metadata

As a content operator, I want articles to produce SEO metadata and feeds so that content can be discovered through search and syndication.

Acceptance criteria:

1. Published posts expose canonical metadata.
2. Published posts expose Open Graph metadata.
3. Published posts are included in RSS output.
4. Public pages support basic structured data where applicable.
5. Sitemap generation or documented sitemap path includes published content.

### Story 3.6: Seed Content and Editorial Templates

As a content operator, I want article templates and seed topics so that the community can launch with credible content.

Acceptance criteria:

1. Project review template includes use case, repository signal, setup notes, risk reminder, and license notes.
2. Weekly report template includes project highlights, updates, recommended readings, discussion prompts, and disclaimer.
3. Initial seed content list covers TradingAgents, Qlib, OpenBB, QuantStats, vectorbt, and risk methodology.
4. Content guidelines distinguish research demos from investable claims.
5. No article promises returns or gives personalized investment advice.

## Epic 4: Forum and Community Governance

Goal: enable discussion around content, tools, and projects while preserving trust, moderation, and theme consistency.

### Story 4.1: Forum Categories and Public Browsing

As a visitor, I want to browse forum categories and threads so that I can understand community activity before registering.

Acceptance criteria:

1. Forum categories can be listed publicly.
2. Forum threads can be listed by category.
3. Thread list supports pagination and basic sorting.
4. Thread detail is readable by visitors unless hidden by moderation.
5. Empty category states invite relevant discussion.

### Story 4.2: Thread and Reply Creation

As a verified user, I want to create threads and replies so that I can participate in AI trading and investing discussions.

Acceptance criteria:

1. Only authenticated and email-verified users can create threads.
2. Only authenticated and email-verified users can create replies.
3. Thread and reply content is validated and sanitized.
4. New user posting limits and cooldowns apply.
5. Unauthenticated users are guided to login or registration when attempting write actions.

### Story 4.3: Author Edit and Delete Controls

As a content author, I want to edit or delete my own forum content so that I can correct mistakes while preserving moderation needs.

Acceptance criteria:

1. Authors can edit their own threads and replies within allowed rules.
2. Authors can delete or soft-delete their own content within allowed rules.
3. Users cannot edit or delete other users' content.
4. Deleted or hidden content has a safe public display state.
5. Edit and delete actions are auditable when required.

### Story 4.4: Moderation Actions and Reporting

As a moderator, I want reporting and moderation actions so that harmful or off-topic content can be handled.

Acceptance criteria:

1. Users can report threads and replies.
2. Moderators and administrators can hide, lock, pin, or feature threads.
3. Locked threads cannot receive new replies.
4. Moderation actions create audit records.
5. Report handling status is visible in the admin or moderation workflow.

### Story 4.5: Forum Theme System and User Preference

As a user, I want forum themes to be switchable and persistent so that I can choose a comfortable reading experience.

Acceptance criteria:

1. At least `fintech-trust-light` and `terminal-agent-dark` themes are available.
2. Theme switch is available to visitors and authenticated users.
3. Visitor theme preference persists locally.
4. Authenticated user theme preference persists to user preferences.
5. Theme switching does not change permissions, information architecture, or core workflows.

### Story 4.6: Community Rules and Seed Discussion Plan

As a community operator, I want rules and seed discussion topics so that the forum can avoid an empty launch.

Acceptance criteria:

1. Community rules define prohibited financial advice, spam, abusive behavior, and unsafe tool claims.
2. Default categories cover project discussion, strategy research, tools, data/backtesting, beginner Q&A, and site feedback.
3. At least 20 seed discussion topics are prepared.
4. Key articles can link to associated discussion threads.
5. Community guidance explains how to ask high-quality strategy and tool questions.

## Epic 5: Open Source Project Discovery and Weekly Report Workflow

Goal: build the core differentiation loop of discovering, reviewing, and publishing curated AI trading and investing open-source projects.

### Story 5.1: GitHub Discovery Configuration and Collection

As an editor, I want configurable GitHub discovery keywords so that the system can collect relevant projects for review.

Acceptance criteria:

1. Admin or editor can configure discovery keywords.
2. Discovery job queries GitHub using configured keywords.
3. GitHub API token is read from environment configuration.
4. Collection handles GitHub API rate limits gracefully.
5. Discovery failures record safe error details for review.

### Story 5.2: Project Deduplication and Snapshot Storage

As an editor, I want collected projects deduplicated and snapshotted so that project history and freshness can be evaluated.

Acceptance criteria:

1. Duplicate repositories are not inserted as separate projects.
2. Project snapshots store repository metadata, README summary fields, license signal, and update timestamps when available.
3. Snapshot history can support trend analysis later.
4. Failed snapshot collection can retry safely.
5. Storage model separates raw snapshots from reviewed public project records.

### Story 5.3: Project Scoring and Human Review

As an editor, I want automatic project scoring with human review so that only credible projects are promoted.

Acceptance criteria:

1. Automatic scoring uses transparent criteria such as stars, activity, documentation, license, and relevance.
2. Automatic score is marked as an editorial aid, not a recommendation.
3. Editors can set review status values such as new, reviewed, selected, and ignored.
4. Editors can adjust project score notes or review rationale.
5. Public promotion requires human review.

### Story 5.4: Public Project Library and Detail Pages

As a visitor, I want to browse curated open-source projects so that I can compare tools and learn safely.

Acceptance criteria:

1. Public project library lists reviewed projects.
2. Project detail shows repository link, summary, tags, score notes, license signal, update time, and risk reminder.
3. Public pages avoid implying investment advice or return guarantees.
4. Project library supports basic filtering or search.
5. Hidden or ignored projects are not publicly visible.

### Story 5.5: Weekly Report Candidate Pool

As an editor, I want to add selected projects to a weekly report candidate pool so that weekly content can be produced consistently.

Acceptance criteria:

1. Editors can add reviewed projects to a weekly report candidate pool.
2. Candidate pool records selection rationale and editorial notes.
3. Candidate pool can be filtered by week or status.
4. At least one weekly report can be assembled from selected candidates.
5. Candidate tools show license and security review signals before promotion.

## Epic 6: Tool Area MVP and Safe Execution Boundary

Goal: validate tool interest while protecting users and the platform from arbitrary execution, real trading, and unsafe third-party code.

### Story 6.1: Tool Catalog and Tool Detail Pages

As a visitor, I want to browse tool descriptions so that I can understand available AI trading and investing demos before logging in.

Acceptance criteria:

1. Tool list is publicly visible.
2. Tool detail shows source project, license, risk level, supported mode, resource cost, and usage limitations.
3. High-risk tools can be configured only as documentation or external-demo mode.
4. Tool detail includes financial and execution risk reminders.
5. Tool list distinguishes runnable demos from documentation-only tools.

### Story 6.2: Tool Manifest and Admin Configuration

As an administrator, I want tool manifests to define allowed parameters and execution boundaries so that tool usage remains controlled.

Acceptance criteria:

1. Tool manifest defines entry command or mode, allowed parameters, resource limits, timeout, and network policy.
2. Manifest validation rejects unsupported parameters and unsafe execution modes.
3. Admin can create, update, publish, unpublish, and retire tool configurations.
4. Admin changes create audit records.
5. Tools cannot execute arbitrary user-provided code.

### Story 6.3: Tool Job Creation and Ownership

As a verified user, I want to create tool jobs so that I can run approved low-risk demos.

Acceptance criteria:

1. Only authenticated and verified users can create tool jobs.
2. Job input is validated against the tool manifest.
3. Job ownership is stored with the user.
4. Users cannot view other users' private job results.
5. Unauthenticated users are guided to login when attempting to run a tool.

### Story 6.4: Worker Execution and Job State Machine

As an operator, I want tool jobs to run asynchronously with clear states so that web requests remain responsive and failures are traceable.

Acceptance criteria:

1. Job states include queued, running, succeeded, failed, and timeout.
2. Worker updates job state and timestamps during execution.
3. Jobs enforce configured timeout and resource boundaries.
4. Failed jobs capture safe failure reasons.
5. Job ID links API requests, worker logs, and frontend status.

### Story 6.5: Tool Result Display and Usage History

As a user, I want to view my tool job status, results, and history so that I can learn from previous runs.

Acceptance criteria:

1. User can view their own job list.
2. User can view status and result for their own job.
3. Result output size is limited.
4. Sensitive information is filtered before result display where applicable.
5. Frontend handles queued, running, succeeded, failed, and timeout states.

### Story 6.6: Tool Security and Supply Chain Checks

As a platform owner, I want tool security checks so that third-party tool risk is assessed before publication.

Acceptance criteria:

1. Tool onboarding includes license review.
2. Tool onboarding includes dependency and image vulnerability review where applicable.
3. Tool containers use read-only filesystem and temporary cleanup where applicable.
4. Default outbound network access is denied unless a domain whitelist is approved.
5. High-risk trading or broker-connected functions remain excluded from MVP execution.

## Epic 7: Public Beta Readiness and Launch Operations

Goal: make the MVP publicly usable, testable, observable, and recoverable before launch.

### Story 7.1: End-to-End Test Coverage for Core Paths

As a tester, I want automated coverage for core user paths so that launch regressions can be caught before release.

Acceptance criteria:

1. E2E or integration coverage includes visitor browsing homepage and blog.
2. E2E or integration coverage includes registration, email verification, and login.
3. E2E or integration coverage includes posting and replying in forum.
4. E2E or integration coverage includes creating and viewing a tool job.
5. E2E or integration coverage includes admin publishing content and moderating forum content.

### Story 7.2: Responsive UI and Error Pages

As a visitor, I want the site to work on common screen sizes and show clear error pages so that the experience feels production-ready.

Acceptance criteria:

1. Homepage, blog, forum, tools, project library, auth pages, and user center are responsive.
2. 404 page is available.
3. 500 or generic error page is available.
4. Unauthorized and forbidden states provide clear next actions.
5. Loading, empty, and error states exist for key frontend pages.

### Story 7.3: Legal, Privacy, and Risk Disclosure Pages

As a platform owner, I want legal and risk disclosure pages so that MVP boundaries are visible to users.

Acceptance criteria:

1. User agreement page exists.
2. Privacy policy page exists.
3. Financial risk disclaimer page exists.
4. Disclaimer states the platform is for education and research and does not provide investment advice.
5. Public content and tool pages link to relevant disclaimer information.

### Story 7.4: Observability and Operational Dashboards

As an operator, I want monitoring for API, worker, database, and content operations so that production issues can be detected.

Acceptance criteria:

1. API latency, error rate, and request volume are observable.
2. Worker queue backlog and job failure rate are observable.
3. Email delivery success or failure is observable.
4. Database slow query or health indicators are observable.
5. Alerts exist for critical API, worker, and storage failures.

### Story 7.5: Backup, Restore, and Rollback Readiness

As an operator, I want backup and rollback procedures so that launch incidents can be recovered safely.

Acceptance criteria:

1. Database backup strategy is documented.
2. File/object storage backup assumptions are documented.
3. Restore procedure is tested at least once before public beta.
4. Deployment rollback procedure is documented.
5. Release checklist includes backup and rollback verification.

### Story 7.6: Launch Content and Community Seed Package

As a content operator, I want launch-ready seed content and discussions so that the public beta does not feel empty.

Acceptance criteria:

1. Homepage has selected launch content.
2. At least 10 blog posts or drafts are prepared for launch operations.
3. At least 20 forum seed topics are prepared.
4. At least 3 to 5 tools are configured as runnable, external, or documentation-only entries.
5. First AI trading and investing open-source weekly report is ready to publish.
