# Isolated production init / signal forwarding runtime receipt (v2)

Harness started at 2026-10-12T11:56:00.795Z UTC.
Receipt: /tmp/ai-investor-iter200-202-20261012.afLb99/prod-init-runtime-v2-parent.receipt.md
Application log: /tmp/ai-investor-iter200-202-20261012.afLb99/prod-init-runtime-v2-parent.logs.txt
Source Compose env input: /tmp/iter202-d12-compose.env; its contents are never logged.
POSTGRES_DB validated with iter202_ prefix: iter202_dev_d12.
- inspect approved production image: started 2026-10-12T11:56:00.801Z; finished 2026-10-12T11:56:01.121Z; rc=0; command="docker" "image" "inspect" "--format" "{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Cmd}}" "iter202-d14-backend:20261012-init-final"
Production image readback: id=sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9; platform=linux/arm64; cmd=["sh","-c","exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile -"].
- inspect cached curl peer image: started 2026-10-12T11:56:01.122Z; finished 2026-10-12T11:56:01.218Z; rc=0; command="docker" "image" "inspect" "--format" "{{.Id}}" "iter202-d12-backend-logdir:20261012-final"
Curl peer image readback: id=sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc; network-only, no mounts or ports.
- inspect existing isolated network: started 2026-10-12T11:56:01.219Z; finished 2026-10-12T11:56:01.257Z; rc=0; command="docker" "network" "inspect" "--format" "{{.Name}}|{{.Driver}}|{{.Internal}}" "iter202-d12_backtrader_dev"
- inspect existing isolated PostgreSQL state: started 2026-10-12T11:56:01.258Z; finished 2026-10-12T11:56:04.552Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}" "iter202-d12-postgres-1"
- verify PostgreSQL network attachment: started 2026-10-12T11:56:04.555Z; finished 2026-10-12T11:56:07.974Z; rc=0; command="docker" "inspect" "--format" "{{if index .NetworkSettings.Networks \"iter202-d12_backtrader_dev\"}}attached{{else}}missing{{end}}" "iter202-d12-postgres-1"
- ensure target app container name is unused: started 2026-10-12T11:56:07.974Z; finished 2026-10-12T11:56:08.053Z; rc=0; command="docker" "container" "ls" "--all" "--quiet" "--filter" "name=^/iter202-prod-signal-parent-v2$"
- read PostgreSQL fixture database identity: started 2026-10-12T11:56:08.054Z; finished 2026-10-12T11:56:11.217Z; rc=0; command="docker" "exec" "iter202-d12-postgres-1" "sh" "-c" "printf \"%s\\n%s\\n\" \"$POSTGRES_DB\" \"$POSTGRES_USER\""
PostgreSQL container confirms the same isolated database: iter202_dev_d12; user value omitted.
Generated application env file with mode 0600: /tmp/iter202-prod-signal-parent-v2.env; contents are not logged.
- create least-privilege runtime role and verify grants: started 2026-10-12T11:56:11.225Z; finished 2026-10-12T11:56:14.788Z; rc=0; command="docker" "exec" "-i" "iter202-d12-postgres-1" "sh" "-c" "exec psql -X -qAt -v ON_ERROR_STOP=1 --username \"$POSTGRES_USER\" --dbname \"$POSTGRES_DB\"" [stdin: SQL role/grant script; SCRAM verifier redacted and never logged]
Runtime role verified: {"database":"iter202_dev_d12","runtime_role":"iter202_prod_runtime_v2_bdede6017ca3151d","login":true,"superuser":false,"create_database":false,"create_role":false,"replication":false,"bypass_rls":false,"database_connect":true,"database_create":false,"schema_usage":true,"schema_create":false,"tables_dml":true,"tables_checked":154,"sequences_usage_select":true,"sequences_checked":7}.
Runtime role receives public schema USAGE, existing-table SELECT/INSERT/UPDATE/DELETE, and existing-sequence USAGE/SELECT; database CONNECT is verified as available, with no explicit CONNECT grant, database/schema CREATE, or elevated role attributes.
- capture pre-start schema-only fingerprint: started 2026-10-12T11:56:14.792Z; finished 2026-10-12T11:56:18.613Z; rc=0; command="docker" "exec" "iter202-d12-postgres-1" "sh" "-c" "exec pg_dump --schema-only --no-owner --no-privileges --username \"$POSTGRES_USER\" \"$POSTGRES_DB\""
  schema_only_dump_raw_sha256=c9a40fa9f23715367429e01850ba8e07b0fbba76e3414e3c81b1738ffb65957d; normalized_sha256=e03443bccdb970ffb4594960829a889aa6e33f53aeb5cfa896060cf34fb97f3a; bytes=430859; normalization=remove only PostgreSQL \restrict and \unrestrict metadata command lines (random tokens); no table data captured or persisted.
Pre-start schema-only fingerprint: e03443bccdb970ffb4594960829a889aa6e33f53aeb5cfa896060cf34fb97f3a.
- start isolated production runtime container: started 2026-10-12T11:56:18.621Z; finished 2026-10-12T11:56:20.045Z; rc=0; command="docker" "run" "--detach" "--name" "iter202-prod-signal-parent-v2" "--init" "--network" "iter202-d12_backtrader_dev" "--health-retries" "5" "--env-file" "/tmp/iter202-prod-signal-parent-v2.env" "iter202-d14-backend:20261012-init-final"
Started only iter202-prod-signal-parent-v2; container_id=47de4a2697b80cd4f979ddfb0516ef560ca841c233b37a1c907ac3ec6ee7d4d4; no host port, mount, or command override.
- verify app container isolation and command: started 2026-10-12T11:56:20.047Z; finished 2026-10-12T11:56:20.159Z; rc=0; command="docker" "inspect" "--format" "{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}" "iter202-prod-signal-parent-v2"
  readback: init=true; network=iter202-d12_backtrader_dev; ports={}; mounts=[]; image=iter202-d14-backend:20261012-init-final; command=["sh","-c","exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile -"]
Readiness watchdog started at 2026-10-12T11:56:20.161Z UTC; budget=300000ms.
- poll app state and health: started 2026-10-12T11:56:20.161Z; finished 2026-10-12T11:56:20.265Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:20.265Z; finished 2026-10-12T11:56:20.363Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:23.372Z; finished 2026-10-12T11:56:23.653Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:23.653Z; finished 2026-10-12T11:56:24.206Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:27.220Z; finished 2026-10-12T11:56:27.478Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:27.480Z; finished 2026-10-12T11:56:27.768Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:30.784Z; finished 2026-10-12T11:56:31.397Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:31.400Z; finished 2026-10-12T11:56:31.732Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:34.750Z; finished 2026-10-12T11:56:35.307Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:35.309Z; finished 2026-10-12T11:56:35.992Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:39.025Z; finished 2026-10-12T11:56:41.523Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:41.525Z; finished 2026-10-12T11:56:43.136Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:46.220Z; finished 2026-10-12T11:56:46.547Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:46.548Z; finished 2026-10-12T11:56:46.892Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:49.894Z; finished 2026-10-12T11:56:50.272Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:50.273Z; finished 2026-10-12T11:56:50.489Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:53.511Z; finished 2026-10-12T11:56:53.715Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:53.715Z; finished 2026-10-12T11:56:53.815Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:56:56.820Z; finished 2026-10-12T11:56:57.043Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:56:57.045Z; finished 2026-10-12T11:56:57.159Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:00.165Z; finished 2026-10-12T11:57:00.347Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:00.348Z; finished 2026-10-12T11:57:00.438Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:03.455Z; finished 2026-10-12T11:57:04.219Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:04.220Z; finished 2026-10-12T11:57:04.723Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:07.738Z; finished 2026-10-12T11:57:08.291Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:08.298Z; finished 2026-10-12T11:57:09.133Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:12.272Z; finished 2026-10-12T11:57:12.654Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:12.655Z; finished 2026-10-12T11:57:12.992Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:16.003Z; finished 2026-10-12T11:57:16.367Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:16.368Z; finished 2026-10-12T11:57:16.554Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:19.579Z; finished 2026-10-12T11:57:19.941Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:19.941Z; finished 2026-10-12T11:57:20.254Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:23.263Z; finished 2026-10-12T11:57:23.554Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:23.554Z; finished 2026-10-12T11:57:23.734Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:26.739Z; finished 2026-10-12T11:57:27.089Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:27.090Z; finished 2026-10-12T11:57:27.440Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:30.454Z; finished 2026-10-12T11:57:31.089Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:31.090Z; finished 2026-10-12T11:57:31.555Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:34.562Z; finished 2026-10-12T11:57:35.105Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:35.105Z; finished 2026-10-12T11:57:35.428Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:38.432Z; finished 2026-10-12T11:57:38.784Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:38.791Z; finished 2026-10-12T11:57:39.046Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:42.654Z; finished 2026-10-12T11:57:44.379Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:44.390Z; finished 2026-10-12T11:57:47.099Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:50.128Z; finished 2026-10-12T11:57:51.047Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:51.253Z; finished 2026-10-12T11:57:53.103Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:56.114Z; finished 2026-10-12T11:57:56.663Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:57:56.668Z; finished 2026-10-12T11:57:56.908Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:57:59.958Z; finished 2026-10-12T11:58:00.489Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:00.491Z; finished 2026-10-12T11:58:00.652Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:03.666Z; finished 2026-10-12T11:58:04.094Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:04.095Z; finished 2026-10-12T11:58:04.173Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:07.187Z; finished 2026-10-12T11:58:07.422Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:07.422Z; finished 2026-10-12T11:58:07.797Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:10.820Z; finished 2026-10-12T11:58:11.554Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:11.565Z; finished 2026-10-12T11:58:12.110Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:15.133Z; finished 2026-10-12T11:58:15.788Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:15.788Z; finished 2026-10-12T11:58:16.035Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:19.051Z; finished 2026-10-12T11:58:19.433Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:19.454Z; finished 2026-10-12T11:58:19.851Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:22.879Z; finished 2026-10-12T11:58:23.164Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:23.165Z; finished 2026-10-12T11:58:23.341Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:26.345Z; finished 2026-10-12T11:58:26.642Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:26.642Z; finished 2026-10-12T11:58:26.829Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:29.837Z; finished 2026-10-12T11:58:30.163Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:30.164Z; finished 2026-10-12T11:58:30.467Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:33.471Z; finished 2026-10-12T11:58:33.779Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:33.779Z; finished 2026-10-12T11:58:34.181Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:37.196Z; finished 2026-10-12T11:58:37.533Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:37.538Z; finished 2026-10-12T11:58:37.752Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:40.763Z; finished 2026-10-12T11:58:41.660Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:41.665Z; finished 2026-10-12T11:58:42.650Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:45.740Z; finished 2026-10-12T11:58:48.570Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:48.572Z; finished 2026-10-12T11:58:49.466Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:52.476Z; finished 2026-10-12T11:58:52.751Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:52.752Z; finished 2026-10-12T11:58:52.920Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:58:56.181Z; finished 2026-10-12T11:58:57.582Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:58:57.583Z; finished 2026-10-12T11:58:58.125Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:01.129Z; finished 2026-10-12T11:59:01.504Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:01.509Z; finished 2026-10-12T11:59:01.689Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:04.795Z; finished 2026-10-12T11:59:06.026Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:06.029Z; finished 2026-10-12T11:59:06.336Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:09.348Z; finished 2026-10-12T11:59:09.695Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:09.695Z; finished 2026-10-12T11:59:10.011Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:13.016Z; finished 2026-10-12T11:59:13.722Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:13.727Z; finished 2026-10-12T11:59:14.260Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:17.265Z; finished 2026-10-12T11:59:18.014Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:18.049Z; finished 2026-10-12T11:59:18.764Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:21.772Z; finished 2026-10-12T11:59:22.161Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:22.161Z; finished 2026-10-12T11:59:22.445Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:25.449Z; finished 2026-10-12T11:59:25.989Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:25.997Z; finished 2026-10-12T11:59:26.281Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:29.289Z; finished 2026-10-12T11:59:30.115Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:30.116Z; finished 2026-10-12T11:59:30.781Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:33.796Z; finished 2026-10-12T11:59:34.345Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:34.346Z; finished 2026-10-12T11:59:34.565Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:37.571Z; finished 2026-10-12T11:59:38.498Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:38.499Z; finished 2026-10-12T11:59:41.065Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:44.069Z; finished 2026-10-12T11:59:44.449Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:44.451Z; finished 2026-10-12T11:59:44.617Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:47.641Z; finished 2026-10-12T11:59:47.935Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:47.935Z; finished 2026-10-12T11:59:48.207Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:51.212Z; finished 2026-10-12T11:59:51.472Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:51.472Z; finished 2026-10-12T11:59:51.677Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:54.729Z; finished 2026-10-12T11:59:54.980Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:54.980Z; finished 2026-10-12T11:59:55.176Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:59:58.187Z; finished 2026-10-12T11:59:58.537Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T11:59:58.538Z; finished 2026-10-12T11:59:59.026Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:02.048Z; finished 2026-10-12T12:00:02.141Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:02.141Z; finished 2026-10-12T12:00:02.196Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:05.201Z; finished 2026-10-12T12:00:05.440Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:05.442Z; finished 2026-10-12T12:00:05.604Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:08.609Z; finished 2026-10-12T12:00:08.690Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:08.690Z; finished 2026-10-12T12:00:08.782Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:11.791Z; finished 2026-10-12T12:00:12.097Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:12.098Z; finished 2026-10-12T12:00:12.236Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:15.238Z; finished 2026-10-12T12:00:15.401Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:15.402Z; finished 2026-10-12T12:00:15.568Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:18.573Z; finished 2026-10-12T12:00:18.895Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:18.896Z; finished 2026-10-12T12:00:19.005Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:22.007Z; finished 2026-10-12T12:00:22.131Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:22.138Z; finished 2026-10-12T12:00:22.293Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:25.295Z; finished 2026-10-12T12:00:25.412Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:25.413Z; finished 2026-10-12T12:00:25.473Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:28.477Z; finished 2026-10-12T12:00:28.606Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:28.607Z; finished 2026-10-12T12:00:28.779Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:31.784Z; finished 2026-10-12T12:00:31.894Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:31.894Z; finished 2026-10-12T12:00:31.993Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:34.999Z; finished 2026-10-12T12:00:35.188Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:35.189Z; finished 2026-10-12T12:00:35.287Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:38.291Z; finished 2026-10-12T12:00:38.632Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:38.633Z; finished 2026-10-12T12:00:38.831Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:41.895Z; finished 2026-10-12T12:00:42.211Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:42.212Z; finished 2026-10-12T12:00:42.377Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:45.380Z; finished 2026-10-12T12:00:45.475Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:45.475Z; finished 2026-10-12T12:00:45.559Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:48.564Z; finished 2026-10-12T12:00:48.821Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:48.822Z; finished 2026-10-12T12:00:49.001Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:52.006Z; finished 2026-10-12T12:00:52.301Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:52.302Z; finished 2026-10-12T12:00:52.428Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:55.436Z; finished 2026-10-12T12:00:55.731Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:00:55.733Z; finished 2026-10-12T12:00:55.953Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:00:59.391Z; finished 2026-10-12T12:01:00.295Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:00.299Z; finished 2026-10-12T12:01:00.665Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:01:03.751Z; finished 2026-10-12T12:01:05.788Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:05.789Z; finished 2026-10-12T12:01:06.037Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:01:09.047Z; finished 2026-10-12T12:01:09.208Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:09.208Z; finished 2026-10-12T12:01:09.322Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:01:12.326Z; finished 2026-10-12T12:01:12.363Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:12.363Z; finished 2026-10-12T12:01:12.391Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:01:15.392Z; finished 2026-10-12T12:01:15.430Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:15.430Z; finished 2026-10-12T12:01:15.452Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T12:01:18.454Z; finished 2026-10-12T12:01:18.487Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent-v2"
- capture application logs: started 2026-10-12T12:01:18.488Z; finished 2026-10-12T12:01:18.528Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
  observed health=healthy; ready_messages=0; readonly_revision_checks=0.
Final result: FAIL at 2026-10-12T12:01:21.534Z UTC; elapsed_ms=320739; error=Application readiness exceeded the 300000ms watchdog..
- failure evidence: capture target app logs: started 2026-10-12T12:01:21.534Z; finished 2026-10-12T12:01:21.568Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent-v2"
- failure evidence: inspect target app state: started 2026-10-12T12:01:21.569Z; finished 2026-10-12T12:01:21.602Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}" "iter202-prod-signal-parent-v2"
  failure_container_state=running|0|false|true|iter202-d12_backtrader_dev; container remains preserved.
No target app container removal or database cleanup was attempted. Evidence files remain mode 0600.
