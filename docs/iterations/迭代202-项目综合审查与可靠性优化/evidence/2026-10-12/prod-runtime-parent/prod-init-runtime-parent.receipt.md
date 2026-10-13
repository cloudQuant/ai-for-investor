# Isolated production init / signal forwarding runtime receipt

Harness started at 2026-10-12T11:53:08.415Z UTC.
Receipt: /tmp/ai-investor-iter200-202-20261012.afLb99/prod-init-runtime-parent.receipt.md
Application log: /tmp/ai-investor-iter200-202-20261012.afLb99/prod-init-runtime-parent.logs.txt
Source Compose env input: /tmp/iter202-d12-compose.env; its contents are never logged.
POSTGRES_DB validated with iter202_ prefix: iter202_dev_d12.
- inspect approved production image: started 2026-10-12T11:53:08.422Z; finished 2026-10-12T11:53:08.741Z; rc=0; command="docker" "image" "inspect" "--format" "{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Cmd}}" "iter202-d14-backend:20261012-init-final"
Production image readback: id=sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9; platform=linux/arm64; cmd=["sh","-c","exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile -"].
- inspect cached curl peer image: started 2026-10-12T11:53:08.742Z; finished 2026-10-12T11:53:09.107Z; rc=0; command="docker" "image" "inspect" "--format" "{{.Id}}" "iter202-d12-backend-logdir:20261012-final"
Curl peer image readback: id=sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc; network-only, no mounts or ports.
- inspect existing isolated network: started 2026-10-12T11:53:09.114Z; finished 2026-10-12T11:53:09.259Z; rc=0; command="docker" "network" "inspect" "--format" "{{.Name}}|{{.Driver}}|{{.Internal}}" "iter202-d12_backtrader_dev"
- inspect existing isolated PostgreSQL state: started 2026-10-12T11:53:09.260Z; finished 2026-10-12T11:53:12.487Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}" "iter202-d12-postgres-1"
- verify PostgreSQL network attachment: started 2026-10-12T11:53:12.494Z; finished 2026-10-12T11:53:16.180Z; rc=0; command="docker" "inspect" "--format" "{{if index .NetworkSettings.Networks \"iter202-d12_backtrader_dev\"}}attached{{else}}missing{{end}}" "iter202-d12-postgres-1"
- ensure target app container name is unused: started 2026-10-12T11:53:16.183Z; finished 2026-10-12T11:53:16.820Z; rc=0; command="docker" "container" "ls" "--all" "--quiet" "--filter" "name=^/iter202-prod-signal-parent$"
- read PostgreSQL fixture database identity: started 2026-10-12T11:53:16.821Z; finished 2026-10-12T11:53:20.520Z; rc=0; command="docker" "exec" "iter202-d12-postgres-1" "sh" "-c" "printf \"%s\\n%s\\n\" \"$POSTGRES_DB\" \"$POSTGRES_USER\""
PostgreSQL container confirms the same isolated database: iter202_dev_d12; user value omitted.
Generated application env file with mode 0600: /tmp/iter202-prod-signal-parent.env; contents are not logged.
- create least-privilege runtime role and verify grants: started 2026-10-12T11:53:20.540Z; finished 2026-10-12T11:53:23.903Z; rc=0; command="docker" "exec" "-i" "iter202-d12-postgres-1" "sh" "-c" "exec psql -X -qAt -v ON_ERROR_STOP=1 --username \"$POSTGRES_USER\" --dbname \"$POSTGRES_DB\"" [stdin: SQL role/grant script; SCRAM verifier redacted and never logged]
Runtime role verified: {"database":"iter202_dev_d12","runtime_role":"iter202_prod_runtime_04372c8df3c453d8","login":true,"superuser":false,"create_database":false,"create_role":false,"replication":false,"bypass_rls":false,"database_connect":true,"database_create":false,"schema_usage":true,"schema_create":false,"tables_dml":true,"tables_checked":154,"sequences_usage_select":true,"sequences_checked":7}.
Runtime role receives public schema USAGE, existing-table SELECT/INSERT/UPDATE/DELETE, and existing-sequence USAGE/SELECT; database CONNECT is verified as available, with no explicit CONNECT grant, database/schema CREATE, or elevated role attributes.
- capture pre-start schema-only fingerprint: started 2026-10-12T11:53:23.905Z; finished 2026-10-12T11:53:28.025Z; rc=0; command="docker" "exec" "iter202-d12-postgres-1" "sh" "-c" "exec pg_dump --schema-only --no-owner --no-privileges --username \"$POSTGRES_USER\" \"$POSTGRES_DB\""
  schema_only_dump_raw_sha256=f7b7a11bb299dfe07c5c305592e3a13e5eb3d462a430d4e4428bc4e1ac325f10; normalized_sha256=e03443bccdb970ffb4594960829a889aa6e33f53aeb5cfa896060cf34fb97f3a; bytes=430859; normalization=remove only PostgreSQL \restrict and \unrestrict metadata command lines (random tokens); no table data captured or persisted.
Pre-start schema-only fingerprint: e03443bccdb970ffb4594960829a889aa6e33f53aeb5cfa896060cf34fb97f3a.
- start isolated production runtime container: started 2026-10-12T11:53:28.032Z; finished 2026-10-12T11:53:31.535Z; rc=0; command="docker" "run" "--detach" "--name" "iter202-prod-signal-parent" "--init" "--network" "iter202-d12_backtrader_dev" "--health-retries" "5" "--env-file" "/tmp/iter202-prod-signal-parent.env" "iter202-d14-backend:20261012-init-final"
Started only iter202-prod-signal-parent; container_id=932de58b13721493e18b98ceef326db5d4ba6a668b2aac79d0b673a6e1b3f33b; no host port, mount, or command override.
- verify app container isolation and command: started 2026-10-12T11:53:31.543Z; finished 2026-10-12T11:53:31.837Z; rc=0; command="docker" "inspect" "--format" "{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}" "iter202-prod-signal-parent"
  readback: init=true; network=iter202-d12_backtrader_dev; ports={}; mounts=[]; image=iter202-d14-backend:20261012-init-final; command=["sh","-c","exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile -"]
Readiness watchdog started at 2026-10-12T11:53:31.838Z UTC; budget=300000ms.
- poll app state and health: started 2026-10-12T11:53:31.838Z; finished 2026-10-12T11:53:31.905Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent"
- capture application logs: started 2026-10-12T11:53:31.905Z; finished 2026-10-12T11:53:32.004Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:53:35.026Z; finished 2026-10-12T11:53:35.273Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent"
- capture application logs: started 2026-10-12T11:53:35.276Z; finished 2026-10-12T11:53:35.573Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:53:38.585Z; finished 2026-10-12T11:53:39.093Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent"
- capture application logs: started 2026-10-12T11:53:39.093Z; finished 2026-10-12T11:53:39.239Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:53:42.242Z; finished 2026-10-12T11:53:42.595Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent"
- capture application logs: started 2026-10-12T11:53:42.595Z; finished 2026-10-12T11:53:42.751Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent"
  observed health=starting; ready_messages=0; readonly_revision_checks=0.
- poll app state and health: started 2026-10-12T11:53:45.774Z; finished 2026-10-12T11:53:45.985Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}" "iter202-prod-signal-parent"
Final result: FAIL at 2026-10-12T11:53:45.987Z UTC; elapsed_ms=37572; error=Application container stopped before healthy state: {"status":"exited","health":"unhealthy","exitCode":"1","oomKilled":"false"}..
- failure evidence: capture target app logs: started 2026-10-12T11:53:45.988Z; finished 2026-10-12T11:53:46.199Z; rc=0; command="docker" "logs" "--timestamps" "iter202-prod-signal-parent"
- failure evidence: inspect target app state: started 2026-10-12T11:53:46.200Z; finished 2026-10-12T11:53:46.287Z; rc=0; command="docker" "inspect" "--format" "{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}" "iter202-prod-signal-parent"
  failure_container_state=exited|1|false|true|iter202-d12_backtrader_dev; container remains preserved.
No target app container removal or database cleanup was attempted. Evidence files remain mode 0600.
