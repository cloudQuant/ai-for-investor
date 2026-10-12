'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const OUTPUT_DIR = '/tmp/ai-investor-iter200-202-20261012.afLb99';
const V2_RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v2-parent.receipt.md');
const RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v3-parent.receipt.md');
const APP_LOG = path.join(OUTPUT_DIR, 'prod-init-runtime-v3-parent.logs.txt');
const PG_CONTAINER = 'iter202-d12-postgres-1';
const NETWORK = 'iter202-d12_backtrader_dev';
const APP_CONTAINER = 'iter202-prod-signal-parent-v2';
const PROD_IMAGE = 'iter202-d14-backend:20261012-init-final';
const PROD_IMAGE_ID =
  'sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9';
const DEV_IMAGE = 'iter202-d12-backend-logdir:20261012-final';
const DEV_IMAGE_ID =
  'sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc';
const MAX_OUTPUT_BYTES = 64 * 1024 * 1024;
const secrets = new Set();
let outputReady = false;
let startEpochMs = 0;
let appStopAttempted = false;

function utcNow() {
  return new Date().toISOString();
}

function redact(value) {
  let text = String(value ?? '');
  for (const secret of secrets) {
    if (secret.length >= 6) text = text.split(secret).join('[REDACTED]');
  }
  text = text.replace(
    /([a-z][a-z0-9+.-]*:\/\/[^:\s/@]+:)[^@\s/]+(@)/gi,
    '$1[REDACTED]$2',
  );
  text = text.replace(
    /((?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL)[A-Z0-9_]*\s*[=:]\s*)[^\s,;]+/gi,
    '$1[REDACTED]',
  );
  return text;
}

function appendReceipt(text) {
  if (outputReady) {
    fs.appendFileSync(RECEIPT, `${redact(text)}\n`, { encoding: 'utf8', mode: 0o600 });
  }
}

function appendLog(text) {
  if (outputReady && text) {
    fs.appendFileSync(APP_LOG, redact(text), { encoding: 'utf8', mode: 0o600 });
  }
}

function initializeOutputs() {
  process.umask(0o077);
  fs.mkdirSync(OUTPUT_DIR, { recursive: true, mode: 0o700 });
  for (const filename of [RECEIPT, APP_LOG]) {
    if (fs.existsSync(filename)) throw new Error(`Refusing to overwrite v3 evidence: ${filename}`);
  }
  fs.writeFileSync(
    RECEIPT,
    '# Isolated production runtime resume receipt (v3)\n\n',
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  fs.writeFileSync(
    APP_LOG,
    `# v3 filtered runtime/shutdown evidence; started ${utcNow()} UTC\n`,
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  outputReady = true;
  startEpochMs = Date.now();
  appendReceipt(`Harness started at ${utcNow()} UTC; it will resume, then stop, only ${APP_CONTAINER}.`);
  appendReceipt(`Receipt: ${RECEIPT}`);
  appendReceipt(`Filtered evidence log: ${APP_LOG}`);
}

function combinedOutput(result) {
  const stdout = result.stdout ?? '';
  const stderr = result.stderr ?? '';
  if (!stderr) return stdout;
  if (!stdout) return stderr;
  return `${stdout}\n[stderr stream]\n${stderr}`;
}

function renderedCommand(binary, args, stdinDescription) {
  const command = [binary, ...args].map((arg) => JSON.stringify(String(arg))).join(' ');
  return stdinDescription ? `${command} [stdin: ${stdinDescription}]` : command;
}

function runStage(stage, binary, args, options = {}) {
  const started = utcNow();
  const result = spawnSync(binary, args, {
    encoding: 'utf8',
    input: options.input,
    maxBuffer: MAX_OUTPUT_BYTES,
    timeout: options.timeoutMs ?? 45_000,
    env: process.env,
  });
  const finished = utcNow();
  const rc = result.status === null ? `null(signal=${result.signal ?? 'unknown'})` : result.status;
  appendReceipt(
    `- ${stage}: started ${started}; finished ${finished}; rc=${rc}; command=${renderedCommand(binary, args, options.stdinDescription)}`,
  );
  if (result.error) appendReceipt(`  spawn_error=${result.error.message}`);
  if (result.status !== 0 && options.keepFailureOutput !== false) {
    appendLog(`\n[${stage} failed at ${finished}; rc=${rc}]\n${combinedOutput(result)}\n`);
  }
  return {
    status: result.status,
    signal: result.signal,
    error: result.error,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
    rc,
    started,
    finished,
  };
}

function requireSuccess(result, stage) {
  if (result.status !== 0) throw new Error(`${stage} failed with rc=${result.rc}.`);
  return result;
}

function readV2Baseline() {
  const stats = fs.lstatSync(V2_RECEIPT);
  if (!stats.isFile() || stats.isSymbolicLink() || (stats.mode & 0o777) !== 0o600) {
    throw new Error('The v2 receipt must be a regular mode-0600 file.');
  }
  const contents = fs.readFileSync(V2_RECEIPT, 'utf8');
  const database = contents.match(/^POSTGRES_DB validated with iter202_ prefix: ([A-Za-z0-9_]+)\.$/m)?.[1];
  const permissionText = contents.match(/^Runtime role verified: (\{.*\})\.$/m)?.[1];
  const preStartFingerprint = contents.match(
    /^Pre-start schema-only fingerprint: ([a-f0-9]{64})\.$/m,
  )?.[1];
  const containerId = contents.match(
    /^Started only iter202-prod-signal-parent-v2; container_id=([a-f0-9]{64});/m,
  )?.[1];
  if (!database || !/^iter202_[A-Za-z0-9_]+$/.test(database)) {
    throw new Error('The v2 receipt has no guarded iter202_ database identity.');
  }
  if (!permissionText || !preStartFingerprint || !containerId) {
    throw new Error('The v2 receipt is missing the runtime role, pre-start schema hash, or container ID.');
  }
  const permissions = JSON.parse(permissionText);
  if (permissions.database !== database || !/^iter202_prod_runtime_v2_[a-f0-9]{16}$/.test(permissions.runtime_role)) {
    throw new Error('The v2 receipt runtime role/database identity is invalid.');
  }
  const receiptHash = crypto.createHash('sha256').update(contents).digest('hex');
  appendReceipt(
    `Loaded v2 baseline receipt sha256=${receiptHash}; database=${database}; runtime_role=${permissions.runtime_role}; container_id=${containerId}.`,
  );
  appendReceipt(`Pre-start normalized schema fingerprint from v2 receipt: ${preStartFingerprint}.`);
  return { database, permissions, preStartFingerprint, containerId };
}

function schemaDumpCommand() {
  return [
    'exec',
    PG_CONTAINER,
    'sh',
    '-c',
    'exec pg_dump --schema-only --no-owner --no-privileges --username "$POSTGRES_USER" "$POSTGRES_DB"',
  ];
}

function captureSchemaFingerprint(stage) {
  const result = runStage(stage, 'docker', schemaDumpCommand(), { timeoutMs: 45_000 });
  requireSuccess(result, stage);
  const dump = result.stdout;
  const raw = crypto.createHash('sha256').update(dump).digest('hex');
  const normalized = dump.replace(/^\\(?:restrict|unrestrict)\s+\S+\s*\r?\n/gm, '');
  const normalizedHash = crypto.createHash('sha256').update(normalized).digest('hex');
  appendReceipt(
    `  schema_only_dump_raw_sha256=${raw}; normalized_sha256=${normalizedHash}; bytes=${Buffer.byteLength(dump)}; normalization=remove only PostgreSQL \\restrict and \\unrestrict metadata command lines; no table data retained.`,
  );
  return normalizedHash;
}

function inspectApprovedImages() {
  const prod = runStage('verify approved production image digest and platform', 'docker', [
    'image',
    'inspect',
    '--format',
    '{{.Id}}|{{.Os}}|{{.Architecture}}',
    PROD_IMAGE,
  ]);
  requireSuccess(prod, 'verify production image');
  const [id, osName, architecture] = prod.stdout.trim().split('|');
  if (id !== PROD_IMAGE_ID || osName !== 'linux' || architecture !== 'arm64') {
    throw new Error('The production image digest or platform differs from the approved final image.');
  }
  appendReceipt(`Production image verified: id=${id}; platform=${osName}/${architecture}.`);

  const peer = runStage('verify cached independent HTTP peer image', 'docker', [
    'image',
    'inspect',
    '--format',
    '{{.Id}}',
    DEV_IMAGE,
  ]);
  requireSuccess(peer, 'verify cached peer image');
  if (peer.stdout.trim() !== DEV_IMAGE_ID) throw new Error('The cached dev peer image digest changed.');
  appendReceipt(`Independent curl peer image verified: id=${peer.stdout.trim()}.`);
}

function verifyInternalNetwork() {
  const network = runStage('verify isolated network driver and Internal flag', 'docker', [
    'network',
    'inspect',
    '--format',
    '{{.Name}}|{{.Driver}}|{{.Internal}}',
    NETWORK,
  ]);
  requireSuccess(network, 'verify isolated network');
  if (network.stdout.trim() !== `${NETWORK}|bridge|true`) {
    throw new Error('The existing app network is not the expected internal bridge network.');
  }
  appendReceipt(`Isolated network verified: ${network.stdout.trim()}.`);

  const pgState = runStage('verify existing PostgreSQL container is running', 'docker', [
    'inspect',
    '--format',
    '{{.State.Status}}',
    PG_CONTAINER,
  ]);
  requireSuccess(pgState, 'verify PostgreSQL state');
  if (pgState.stdout.trim() !== 'running') throw new Error('The designated PostgreSQL fixture is not running.');

  const pgNetwork = runStage('verify PostgreSQL network attachment', 'docker', [
    'inspect',
    '--format',
    `{{if index .NetworkSettings.Networks "${NETWORK}"}}attached{{else}}missing{{end}}`,
    PG_CONTAINER,
  ]);
  requireSuccess(pgNetwork, 'verify PostgreSQL network attachment');
  if (pgNetwork.stdout.trim() !== 'attached') {
    throw new Error('The existing PostgreSQL fixture is no longer attached to the isolated network.');
  }
}

function inspectLiveApp(baseline) {
  const result = runStage('verify existing v2 app container image, init, network, health, and mounts', 'docker', [
    'inspect',
    '--format',
    '{{.Id}}|{{.Image}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}',
    APP_CONTAINER,
  ]);
  requireSuccess(result, 'inspect existing v2 app container');
  const fields = result.stdout.trim().split('|');
  if (fields.length !== 12) throw new Error('The app container inspection returned malformed fields.');
  const [id, imageId, state, health, exitCode, oomKilled, init, network, ports, mounts, imageTag, command] = fields;
  if (id !== baseline.containerId) throw new Error('The live v2 container ID differs from its receipt.');
  if (imageId !== PROD_IMAGE_ID || imageTag !== PROD_IMAGE) throw new Error('The live v2 app image changed.');
  if (state !== 'running' || health !== 'healthy' || oomKilled !== 'false') {
    throw new Error(`Expected an already-running healthy app; state=${state}, health=${health}, oom=${oomKilled}.`);
  }
  if (init !== 'true' || network !== NETWORK) throw new Error('The live app init/network configuration changed.');
  if (ports !== 'null' && ports !== '{}') throw new Error('The live app unexpectedly publishes host ports.');
  if (mounts !== '[]') throw new Error('The live app unexpectedly has mounts.');
  if (!command.includes('exec gunicorn app.main:app')) throw new Error('The live app command no longer execs Gunicorn.');
  appendReceipt(
    `Live container verified: id=${id}; image=${imageTag}/${imageId}; state=${state}; health=${health}; oom=${oomKilled}; init=${init}; network=${network}; ports=${ports}; mounts=${mounts}; command=${command}.`,
  );
}

function buildPermissionQuery(role) {
  return [
    '\\set ON_ERROR_STOP on',
    `\\set runtime_role ${role}`,
    [
      'SELECT json_build_object(',
      "'database', current_database(),",
      "'runtime_role', r.rolname,",
      "'login', r.rolcanlogin,",
      "'superuser', r.rolsuper,",
      "'create_database', r.rolcreatedb,",
      "'create_role', r.rolcreaterole,",
      "'replication', r.rolreplication,",
      "'bypass_rls', r.rolbypassrls,",
      "'database_connect', has_database_privilege(r.oid, current_database(), 'CONNECT'),",
      "'database_create', has_database_privilege(r.oid, current_database(), 'CREATE'),",
      "'schema_usage', has_schema_privilege(r.oid, 'public', 'USAGE'),",
      "'schema_create', has_schema_privilege(r.oid, 'public', 'CREATE'),",
      "'tables_dml', COALESCE((SELECT bool_and(",
      "has_table_privilege(r.oid, c.oid, 'SELECT') AND",
      "has_table_privilege(r.oid, c.oid, 'INSERT') AND",
      "has_table_privilege(r.oid, c.oid, 'UPDATE') AND",
      "has_table_privilege(r.oid, c.oid, 'DELETE'))",
      "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace",
      "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')), true),",
      "'tables_checked', (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')),",
      "'sequences_usage_select', COALESCE((SELECT bool_and(",
      "has_sequence_privilege(r.oid, c.oid, 'USAGE') AND",
      "has_sequence_privilege(r.oid, c.oid, 'SELECT'))",
      "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace",
      "WHERE n.nspname = 'public' AND c.relkind = 'S'), true),",
      "'sequences_checked', (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'S')",
      ")::text FROM pg_roles r WHERE r.rolname = :'runtime_role';",
    ].join('\n'),
    '',
  ].join('\n');
}

function parsePermissionJson(stdout) {
  const line = stdout.split(/\r?\n/).map((item) => item.trim()).find((item) => item.startsWith('{'));
  if (!line) throw new Error('The existing runtime role verification returned no JSON row.');
  return JSON.parse(line);
}

function verifyRolePermissions(baseline) {
  const dbName = runStage('verify PostgreSQL fixture database identity', 'docker', [
    'exec',
    PG_CONTAINER,
    'sh',
    '-c',
    'printf "%s\\n" "$POSTGRES_DB"',
  ]);
  requireSuccess(dbName, 'verify PostgreSQL database identity');
  if (dbName.stdout.trim() !== baseline.database) throw new Error('PostgreSQL database identity differs from v2 receipt.');

  const result = runStage('read-only verify existing runtime role permissions', 'docker', [
    'exec',
    '-i',
    PG_CONTAINER,
    'sh',
    '-c',
    'exec psql -X -qAt -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
  ], {
    input: buildPermissionQuery(baseline.permissions.runtime_role),
    stdinDescription: 'read-only PostgreSQL catalog privilege query; no role or grant changes',
  });
  requireSuccess(result, 'verify runtime role permissions');
  const current = parsePermissionJson(result.stdout);
  const keys = [
    'database', 'runtime_role', 'login', 'superuser', 'create_database', 'create_role',
    'replication', 'bypass_rls', 'database_connect', 'database_create', 'schema_usage',
    'schema_create', 'tables_dml', 'tables_checked', 'sequences_usage_select', 'sequences_checked',
  ];
  for (const key of keys) {
    if (current[key] !== baseline.permissions[key]) {
      throw new Error(`Runtime role permission drift detected in ${key}.`);
    }
  }
  const mustBeTrue = ['login', 'database_connect', 'schema_usage', 'tables_dml', 'sequences_usage_select'];
  const mustBeFalse = ['superuser', 'create_database', 'create_role', 'replication', 'bypass_rls', 'database_create', 'schema_create'];
  if (mustBeTrue.some((key) => current[key] !== true) || mustBeFalse.some((key) => current[key] !== false)) {
    throw new Error('The existing runtime role no longer satisfies its least-privilege flags.');
  }
  appendReceipt(`Existing runtime role permission check is read-only and unchanged: ${JSON.stringify(current)}.`);
}

const PROCESS_TREE_PROBE = String.raw`
import json
import os
from pathlib import Path

def read_cmd(pid):
    try:
        data = (Path('/proc') / str(pid) / 'cmdline').read_bytes()
        return ' '.join(part.decode('utf-8', 'replace') for part in data.split(b'\0') if part)
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return ''

def read_info(pid):
    status = (Path('/proc') / str(pid) / 'status').read_text(errors='replace')
    name = next((line[6:] for line in status.splitlines() if line.startswith('Name:')), '')
    parent = next((line.split()[1] for line in status.splitlines() if line.startswith('PPid:')), '0')
    try:
        cwd = os.readlink(f'/proc/{pid}/cwd')
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        cwd = ''
    return {'pid': pid, 'ppid': int(parent), 'name': name.strip(), 'cmd': read_cmd(pid), 'cwd': cwd}

infos = {}
for item in Path('/proc').iterdir():
    if item.name.isdigit():
        try:
            infos[int(item.name)] = read_info(int(item.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
pid1 = infos.get(1, {'pid': 1, 'ppid': 0, 'name': '', 'cmd': '', 'cwd': ''})
children = sorted((p for p in infos.values() if p['ppid'] == 1 and p['pid'] != os.getpid()), key=lambda p: p['pid'])
masters = [p for p in children if 'gunicorn' in p['cmd'].lower() and 'app.main:app' in p['cmd']]
master = masters[0] if len(masters) == 1 else None
healthchecks = [p for p in children if p['name'].lower().startswith('python') and 'urllib.request.urlopen' in p['cmd'] and '/health' in p['cmd']]
unexpected = [p for p in children if p not in masters and p not in healthchecks]
workers = sorted((p for p in infos.values() if master and p['ppid'] == master['pid']), key=lambda p: p['pid'])
print(json.dumps({'pid1': pid1, 'pid1_children': children, 'master': master, 'workers': workers, 'healthcheck_children': healthchecks, 'unexpected_pid1_children': unexpected}, sort_keys=True))
`;

function inspectProcessTree() {
  const result = runStage('re-read audited PID 1 and Gunicorn process tree', 'docker', [
    'exec', '-i', APP_CONTAINER, 'python', '-',
  ], { input: PROCESS_TREE_PROBE, stdinDescription: 'read-only /proc PID/command probe' });
  requireSuccess(result, 'inspect process tree');
  const line = result.stdout.split(/\r?\n/).map((item) => item.trim()).find((item) => item.startsWith('{'));
  if (!line) throw new Error('The process probe returned no JSON summary.');
  const report = JSON.parse(line);
  if (!/(?:tini|docker-init|\/dev\/init)/i.test(report.pid1?.cmd ?? '')) {
    throw new Error('PID 1 is not the expected Docker init/tini process.');
  }
  if (!report.master || report.unexpected_pid1_children?.length !== 0 || report.workers?.length !== 2) {
    throw new Error('PID tree no longer shows one direct Gunicorn master and exactly two workers.');
  }
  if (report.workers.some((worker) => !/gunicorn|app\.main:app/i.test(worker.cmd))) {
    throw new Error('A Gunicorn child does not identify as an application worker.');
  }
  const workerPids = report.workers.map((worker) => worker.pid).sort((a, b) => a - b);
  const minimal = {
    pid1: report.pid1,
    master: report.master,
    workers: report.workers,
    healthcheck_children: report.healthcheck_children,
    worker_pids: workerPids,
  };
  appendReceipt(`Audited process tree re-read: ${JSON.stringify(minimal)}.`);
  appendLog(`[audited PID tree] ${JSON.stringify(minimal)}\n`);
  return { report, workerPids };
}

const LOG_PROBE = String.raw`
import json
import sys
from pathlib import Path
from app.config import get_settings

settings = get_settings()
base = Path(sys.argv[1])
log_dir = Path(settings.LOG_DIR).expanduser()
if not log_dir.is_absolute():
    log_dir = base / log_dir
log_dir = log_dir.resolve()
files = sorted(p for p in log_dir.glob('app_*.log') if p.is_file())
events = {
    'revision_verified_pids': [],
    'application_ready_pids': [],
}
event_names = {
    'Database migration revision verified (startup performed no DDL)': 'revision_verified_pids',
    'Application ready - accepting requests': 'application_ready_pids',
}
event_rows = []
parse_errors = 0
for log_file in files:
    try:
        with log_file.open('r', encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    parse_errors += 1
                    continue
                record = entry.get('record', entry)
                message = record.get('message', entry.get('message', ''))
                kind = event_names.get(message)
                if not kind:
                    continue
                process = record.get('process') or {}
                pid = process.get('id')
                if isinstance(pid, int):
                    events[kind].append(pid)
                    event_rows.append({'file': log_file.name, 'kind': kind, 'pid': pid})
    except (OSError, PermissionError):
        continue
for key in events:
    events[key] = sorted(set(events[key]))
print(json.dumps({
    'log_dir': str(log_dir),
    'files': [p.name for p in files],
    'event_pids': events,
    'event_rows': event_rows,
    'parse_errors': parse_errors,
}, sort_keys=True))
`;

function verifyAppFileLogs(workerPids, workerCwd) {
  const cwdSet = new Set(workerCwd);
  if (cwdSet.size !== 1 || !workerCwd[0]) throw new Error('Application workers have inconsistent/unknown cwd.');
  const result = runStage('extract allowlisted startup/revision messages from app log files', 'docker', [
    'exec', '-i', APP_CONTAINER, 'python', '-', workerCwd[0],
  ], { input: LOG_PROBE, stdinDescription: 'allowlisted structured log message/PID counters only; no log lines dumped' });
  requireSuccess(result, 'extract startup and revision messages');
  const line = result.stdout.split(/\r?\n/).map((item) => item.trim()).find((item) => item.startsWith('{'));
  if (!line) throw new Error('The application file log probe returned no JSON summary.');
  const summary = JSON.parse(line);
  const expected = [...workerPids].sort((a, b) => a - b);
  for (const key of ['revision_verified_pids', 'application_ready_pids']) {
    const observed = summary.event_pids?.[key] ?? [];
    if (JSON.stringify(observed) !== JSON.stringify(expected)) {
      throw new Error(`Application file-log evidence ${key} did not match the two live worker PIDs.`);
    }
  }
  appendReceipt(
    `Application file-log summary: log_dir=${summary.log_dir}; files=${JSON.stringify(summary.files)}; ` +
      `revision_verified_pids=${JSON.stringify(summary.event_pids.revision_verified_pids)}; ` +
      `application_ready_pids=${JSON.stringify(summary.event_pids.application_ready_pids)}; ` +
      `allowlisted_event_rows=${JSON.stringify(summary.event_rows)}; ignored_nonjson_line_count=${summary.parse_errors}.`,
  );
  appendLog(`[allowlisted app file-log summary] ${JSON.stringify(summary)}\n`);
}

function extractUvicornEventPids(logText, event) {
  const patterns = {
    server_started: /^\S.*?\[(\d+)\] \[INFO\] Started server process \[(\d+)\]\s*$/,
    startup_complete: /^\S.*?\[(\d+)\] \[INFO\] Application startup complete\.\s*$/,
    shutdown_complete: /^\S.*?\[(\d+)\] \[INFO\] Application shutdown complete\.\s*$/,
  };
  const pattern = patterns[event];
  if (!pattern) throw new Error(`Unsupported allowlisted Uvicorn event: ${event}.`);
  const pids = [];
  for (const line of logText.split(/\r?\n/)) {
    const match = line.match(pattern);
    if (!match) continue;
    const pid = Number(match[1]);
    if (event === 'server_started' && Number(match[2]) !== pid) continue;
    pids.push(pid);
  }
  return [...new Set(pids)].sort((a, b) => a - b);
}

function verifyDockerStartupLogs(workerPids) {
  const logs = runStage('read container stdout and stderr for Uvicorn startup markers', 'docker', [
    'logs', '--timestamps', APP_CONTAINER,
  ], { timeoutMs: 30_000, keepFailureOutput: false });
  requireSuccess(logs, 'capture app startup logs');
  const all = combinedOutput(logs);
  const expected = [...workerPids].sort((a, b) => a - b);
  const startedPids = extractUvicornEventPids(all, 'server_started');
  const startupCompletePids = extractUvicornEventPids(all, 'startup_complete');
  if (JSON.stringify(startedPids) !== JSON.stringify(expected) ||
      JSON.stringify(startupCompletePids) !== JSON.stringify(expected)) {
    throw new Error('Combined stdout/stderr Uvicorn startup markers did not match the two current worker PIDs.');
  }
  const evidence = {
    uvicorn_server_started_pids: startedPids,
    uvicorn_startup_complete_pids: startupCompletePids,
    expected_worker_pids: expected,
  };
  appendReceipt(`Container stdout/stderr startup evidence: ${JSON.stringify(evidence)}.`);
  appendLog(`[allowlisted container startup markers] ${JSON.stringify(evidence)}\n`);
}

function requestIndependentHealth() {
  const result = runStage('request API health through independent internal-network peer', 'docker', [
    'run', '--rm', '--network', NETWORK, '--entrypoint', 'curl', DEV_IMAGE,
    '--fail', '--silent', '--show-error', '--max-time', '20',
    '--write-out', '\\n__HTTP_STATUS__=%{http_code}\\n',
    `http://${APP_CONTAINER}:8000/api/v1/health`,
  ], { timeoutMs: 30_000 });
  requireSuccess(result, 'request independent API health');
  const marker = result.stdout.match(/(?:^|\n)__HTTP_STATUS__=(\d{3})\s*$/);
  if (!marker || Number(marker[1]) !== 200) throw new Error('The independent peer did not receive HTTP 200.');
  const response = JSON.parse(result.stdout.slice(0, marker.index).trim());
  if (response.status !== 'healthy' || response.database !== 'healthy') {
    throw new Error('The API health JSON did not report healthy application and database states.');
  }
  const safe = { status: response.status, database: response.database, version: response.version };
  appendReceipt(`Independent internal-network peer health response: HTTP 200; ${JSON.stringify(safe)}.`);
  appendLog(`[independent health peer] HTTP 200 ${JSON.stringify(safe)}\n`);
}

function stopAndVerifyGracefulShutdown(workerPids) {
  const stop = runStage('stop existing v2 app with 35-second grace period', 'docker', [
    'stop', '--time', '35', APP_CONTAINER,
  ], { timeoutMs: 50_000 });
  appStopAttempted = true;
  requireSuccess(stop, 'stop app with 35-second grace period');

  const logs = runStage('read container logs and extract shutdown markers', 'docker', [
    'logs', '--timestamps', APP_CONTAINER,
  ], { timeoutMs: 30_000, keepFailureOutput: false });
  requireSuccess(logs, 'capture stopped app logs');
  const all = combinedOutput(logs);
  const workerExitPids = [...all.matchAll(/Worker exiting \(pid:\s*(\d+)\)/g)]
    .map((match) => Number(match[1]))
    .filter((pid, index, values) => values.indexOf(pid) === index)
    .sort((a, b) => a - b);
  const masterShutdown = /Shutting down: Master/i.test(all);
  const forcedKill = /SIGKILL|did not exit in time|force.?kill/i.test(all);
  const shutdownCompletePids = extractUvicornEventPids(all, 'shutdown_complete');

  const state = runStage('verify stopped app exit code and OOM status', 'docker', [
    'inspect',
    '--format',
    '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}',
    APP_CONTAINER,
  ]);
  requireSuccess(state, 'verify stopped app state');
  const [status, exitCode, oomKilled] = state.stdout.trim().split('|');
  if (status !== 'exited' || exitCode !== '0' || oomKilled !== 'false') {
    throw new Error(`App container did not stop cleanly: status=${status}; exit=${exitCode}; oom=${oomKilled}.`);
  }
  const expectedWorkers = [...workerPids].sort((a, b) => a - b);
  if (JSON.stringify(workerExitPids) !== JSON.stringify(expectedWorkers) ||
      JSON.stringify(shutdownCompletePids) !== JSON.stringify(expectedWorkers) ||
      !masterShutdown || forcedKill) {
    throw new Error('Gunicorn logs do not prove both workers and the master exited gracefully.');
  }
  const evidence = {
    status,
    exitCode,
    oomKilled,
    worker_exit_pids: workerExitPids,
    uvicorn_shutdown_complete_pids: shutdownCompletePids,
    expected_worker_pids: expectedWorkers,
    master_shutdown: masterShutdown,
    forced_kill_marker: forcedKill,
  };
  appendReceipt(`Graceful shutdown evidence: ${JSON.stringify(evidence)}; app container retained.`);
  appendLog(`[filtered shutdown markers] ${JSON.stringify(evidence)}\n`);
}

function runAcceptance() {
  const baseline = readV2Baseline();
  inspectApprovedImages();
  verifyInternalNetwork();
  inspectLiveApp(baseline);
  verifyRolePermissions(baseline);
  const { report, workerPids } = inspectProcessTree();
  verifyDockerStartupLogs(workerPids);
  verifyAppFileLogs(workerPids, report.workers.map((worker) => worker.cwd));
  requestIndependentHealth();
  stopAndVerifyGracefulShutdown(workerPids);
  const afterFingerprint = captureSchemaFingerprint('capture post-shutdown schema-only fingerprint');
  appendReceipt(`Post-shutdown normalized schema fingerprint: ${afterFingerprint}.`);
  if (afterFingerprint !== baseline.preStartFingerprint) {
    throw new Error('Schema fingerprint changed between the v2 pre-start baseline and post-shutdown.');
  }
  appendReceipt('Schema fingerprint matches the v2 pre-start baseline; no app schema DDL was observed.');
  appendReceipt(`Final result: PASS at ${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; v2 app container is stopped and preserved.`);
  process.stdout.write(`PASS: receipt=${RECEIPT}; logs=${APP_LOG}; container=${APP_CONTAINER} (stopped, retained)\n`);
}

function preserveFailureEvidence(error) {
  appendReceipt(`Final result: FAIL at ${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; error=${error?.message ?? String(error)}.`);
  const inspect = runStage('failure evidence: read v2 app container state', 'docker', [
    'inspect',
    '--format',
    '{{.Id}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}',
    APP_CONTAINER,
  ], { timeoutMs: 20_000 });
  if (inspect.status === 0) appendReceipt(`Failure-state readback: ${inspect.stdout.trim()}; no removal/cleanup attempted.`);
  appendReceipt('The harness did not remove the app container, role, env file, v1/v2 receipt, or database data.');
  process.stderr.write(`FAIL: ${redact(error?.message ?? String(error))}; receipt=${RECEIPT}; logs=${APP_LOG}; app container retained.\n`);
}

function main() {
  initializeOutputs();
  try {
    runAcceptance();
  } catch (error) {
    preserveFailureEvidence(error);
    process.exitCode = 1;
  }
}

main();
