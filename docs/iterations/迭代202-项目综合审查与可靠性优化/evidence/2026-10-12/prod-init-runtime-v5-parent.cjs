'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const OUTPUT_DIR = '/tmp/ai-investor-iter200-202-20261012.afLb99';
const SOURCE_ENV = '/tmp/iter202-d12-compose.env';
const APP_ENV = '/tmp/iter202-prod-signal-parent-v5.env';
const RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v5-parent.receipt.md');
const FILTERED_LOG = path.join(OUTPUT_DIR, 'prod-init-runtime-v5-parent.filtered.log');
const PG_CONTAINER = 'iter202-d12-postgres-1';
const NETWORK = 'iter202-d12_backtrader_dev';
const APP_CONTAINER = 'iter202-prod-signal-parent-v5';
const PROD_IMAGE = 'iter202-d14-backend:20261012-source-final';
const DEV_IMAGE = 'iter202-d12-backend-logdir:20261012-final';
const DEV_IMAGE_ID = 'sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc';
const WATCHDOG_MS = 900_000;
const POLL_MS = 5_000;
const MAX_OUTPUT_BYTES = 64 * 1024 * 1024;
const secrets = new Set();
let outputReady = false;
let appRunAttempted = false;
let startEpochMs = 0;
let productionImageId = '';

const INSPECT_APP_CONFIG =
  '{{.Id}}|{{.Image}}|{{.State.Status}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|' +
  '{{json .HostConfig.PortBindings}}|{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}';
const INSPECT_APP_STATE =
  '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|' +
  '{{.State.ExitCode}}|{{.State.OOMKilled}}';
const INSPECT_STOPPED_STATE = '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}';

const ALLOWED_DOCKER_ARGV = [
  ['image', 'inspect', '--format', '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Cmd}}', PROD_IMAGE],
  ['image', 'inspect', '--format', '{{.Id}}', DEV_IMAGE],
  ['network', 'inspect', '--format', '{{.Name}}|{{.Driver}}|{{.Internal}}', NETWORK],
  ['inspect', '--format', '{{.State.Status}}', PG_CONTAINER],
  [
    'inspect', '--format', `{{if index .NetworkSettings.Networks "${NETWORK}"}}attached{{else}}missing{{end}}`, PG_CONTAINER,
  ],
  ['container', 'ls', '--all', '--quiet', '--filter', `name=^/${APP_CONTAINER}$`],
  ['exec', PG_CONTAINER, 'sh', '-c', 'printf "%s\\n%s\\n" "$POSTGRES_DB" "$POSTGRES_USER"'],
  [
    'exec', '-i', PG_CONTAINER, 'sh', '-c',
    'exec psql -X -qAt -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
  ],
  [
    'exec', PG_CONTAINER, 'sh', '-c',
    'exec pg_dump --schema-only --no-owner --no-privileges --username "$POSTGRES_USER" "$POSTGRES_DB"',
  ],
  [
    'run', '--detach', '--name', APP_CONTAINER, '--init', '--network', NETWORK,
    '--health-retries', '5', '--env-file', APP_ENV, PROD_IMAGE,
  ],
  ['inspect', '--format', INSPECT_APP_CONFIG, APP_CONTAINER],
  ['inspect', '--format', INSPECT_APP_STATE, APP_CONTAINER],
  ['exec', '-i', APP_CONTAINER, 'python', '-'],
  [
    'run', '--rm', '--network', NETWORK, '--entrypoint', 'curl', DEV_IMAGE,
    '--fail', '--silent', '--show-error', '--max-time', '20',
    '--write-out', '\\n__HTTP_STATUS__=%{http_code}\\n',
    `http://${APP_CONTAINER}:8000/api/v1/health`,
  ],
  ['stop', '--time', '35', APP_CONTAINER],
  ['logs', '--timestamps', APP_CONTAINER],
  ['inspect', '--format', INSPECT_STOPPED_STATE, APP_CONTAINER],
  [
    'inspect', '--format',
    '{{.Id}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|' +
      '{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}',
    APP_CONTAINER,
  ],
];
const ALLOWED_ARGV_KEYS = new Set(ALLOWED_DOCKER_ARGV.map((args) => JSON.stringify(args)));

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

function appendFilteredLog(text) {
  if (outputReady && text) {
    fs.appendFileSync(FILTERED_LOG, `${redact(text)}\n`, { encoding: 'utf8', mode: 0o600 });
  }
}

function combinedOutput(result) {
  const stdout = result.stdout ?? '';
  const stderr = result.stderr ?? '';
  if (!stderr) return stdout;
  if (!stdout) return stderr;
  return `${stdout}\n[stderr stream]\n${stderr}`;
}

function renderedCommand(args, stdinDescription) {
  const command = ['docker', ...args].map((arg) => JSON.stringify(String(arg))).join(' ');
  return stdinDescription ? `${command} [stdin: ${stdinDescription}]` : command;
}

function assertAllowedDockerArgv(args) {
  if (!ALLOWED_ARGV_KEYS.has(JSON.stringify(args))) {
    throw new Error(`Refusing unapproved Docker argv: ${JSON.stringify(args)}.`);
  }
}

function runStage(stage, args, options = {}) {
  assertAllowedDockerArgv(args);
  const started = utcNow();
  const result = spawnSync('docker', args, {
    encoding: 'utf8',
    input: options.input,
    maxBuffer: MAX_OUTPUT_BYTES,
    timeout: options.timeoutMs ?? 45_000,
    env: process.env,
  });
  const finished = utcNow();
  const rc = result.status === null ? `null(signal=${result.signal ?? 'unknown'})` : result.status;
  appendReceipt(
    `- ${stage}: started ${started}; finished ${finished}; rc=${rc}; command=${renderedCommand(args, options.stdinDescription)}`,
  );
  if (result.error) appendReceipt(`  spawn_error=${result.error.message}`);
  if (result.status !== 0 && options.logFailure !== false) {
    appendFilteredLog(
      `[${stage} failed at ${finished}; rc=${rc}] ${combinedOutput(result) || result.error?.message || ''}`,
    );
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

function initializeOutputs() {
  process.umask(0o077);
  fs.mkdirSync(OUTPUT_DIR, { recursive: true, mode: 0o700 });
  for (const filename of [RECEIPT, FILTERED_LOG, APP_ENV]) {
    if (fs.existsSync(filename)) throw new Error(`Refusing to overwrite existing v5 artifact: ${filename}`);
  }
  fs.writeFileSync(
    RECEIPT,
    '# Isolated production source-final runtime receipt (v5)\n\n',
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  fs.writeFileSync(
    FILTERED_LOG,
    `# v5 allowlisted startup/shutdown evidence; started ${utcNow()} UTC\n`,
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  outputReady = true;
  startEpochMs = Date.now();
  appendReceipt(`Harness started at ${utcNow()} UTC; target container=${APP_CONTAINER}; target image=${PROD_IMAGE}.`);
  appendReceipt(`Receipt=${RECEIPT}; filtered_log=${FILTERED_LOG}; env_file=${APP_ENV}.`);
  appendReceipt(
    'Shutdown evidence follows the previously inspected Gunicorn 26.0.0 and Uvicorn 0.47.0 semantics: worker lifespan completion plus Finished server process, then master shutdown; Worker exiting is deliberately not a required marker.',
  );
}

function parseComposePostgresDb(filename) {
  const stats = fs.lstatSync(filename);
  if (!stats.isFile() || stats.isSymbolicLink() || (stats.mode & 0o777) !== 0o600) {
    throw new Error('Compose env input must be a regular non-symlink mode-0600 file.');
  }
  const values = [];
  for (const rawLine of fs.readFileSync(filename, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^POSTGRES_DB\s*=\s*(.*)$/);
    if (!match) continue;
    let value = match[1].trim();
    if (value.startsWith('"') || value.startsWith("'")) {
      const quote = value[0];
      if (value.at(-1) !== quote) throw new Error('POSTGRES_DB has unmatched quotes.');
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, '').trim();
    }
    if (value.includes('$')) throw new Error('POSTGRES_DB must be a resolved literal.');
    values.push(value);
  }
  if (values.length !== 1 || !/^iter202_[A-Za-z0-9_]+$/.test(values[0] ?? '')) {
    throw new Error('Expected exactly one iter202_-prefixed POSTGRES_DB in the protected Compose env.');
  }
  return values[0];
}

function makeScramVerifier(password) {
  const salt = crypto.randomBytes(16);
  const saltedPassword = crypto.pbkdf2Sync(password, salt, 4096, 32, 'sha256');
  const clientKey = crypto.createHmac('sha256', saltedPassword).update('Client Key').digest();
  const storedKey = crypto.createHash('sha256').update(clientKey).digest();
  const serverKey = crypto.createHmac('sha256', saltedPassword).update('Server Key').digest();
  return `SCRAM-SHA-256$4096:${salt.toString('base64')}$${storedKey.toString('base64')}:${serverKey.toString('base64')}`;
}

function makeRuntimeEnvironment(database, role, password) {
  const databaseUrl =
    `postgresql+asyncpg://${encodeURIComponent(role)}:${encodeURIComponent(password)}` +
    `@${PG_CONTAINER}:5432/${encodeURIComponent(database)}`;
  const env = {
    APP_NAME: 'ai-for-investor',
    DEBUG: 'false',
    SECRET_KEY: crypto.randomBytes(48).toString('hex'),
    JWT_SECRET_KEY: crypto.randomBytes(48).toString('hex'),
    ADMIN_PASSWORD: crypto.randomBytes(48).toString('hex'),
    JWT_ALGORITHM: 'HS256',
    DATABASE_TYPE: 'postgresql',
    DATABASE_URL: databaseUrl,
    HOST: '0.0.0.0',
    PORT: '8000',
    WEB_CONCURRENCY: '2',
    DB_AUTO_CREATE_SCHEMA: 'false',
    DB_AUTO_CREATE_DEFAULT_ADMIN: 'false',
    SEED_DATA: 'false',
    MARKET_DATA_THS_ENABLED: 'false',
    MARKET_DATA_THS_SCHEDULER_ENABLED: 'false',
    MARKET_DATA_ONLINE_FETCH_ENABLED: 'false',
    MARKET_DATA_QUERY_V2_ENABLED: 'false',
    MARKET_DATA_OPENDATA_ENABLED: 'false',
    THS_API_KEY: '',
    AKSHARE_DATA_DATABASE_URL: '',
  };
  for (const [name, value] of Object.entries(env)) {
    if (/SECRET|PASSWORD|TOKEN|API_KEY|DATABASE_URL/.test(name) && value.length >= 6) secrets.add(value);
  }
  secrets.add(password);
  return env;
}

function writeAppEnv(env) {
  const body = Object.entries(env).map(([key, value]) => `${key}=${value}`).join('\n') + '\n';
  const fd = fs.openSync(APP_ENV, 'wx', 0o600);
  try {
    fs.writeFileSync(fd, body, { encoding: 'utf8' });
    fs.fchmodSync(fd, 0o600);
  } finally {
    fs.closeSync(fd);
  }
  if ((fs.statSync(APP_ENV).mode & 0o777) !== 0o600) {
    throw new Error('Generated application env file does not have mode 0600.');
  }
  appendReceipt(`Generated runtime env mode=0600 at ${APP_ENV}; values are never printed.`);
  appendReceipt(
    `Runtime gates: DEBUG=${env.DEBUG}; DATABASE_TYPE=${env.DATABASE_TYPE}; ` +
      `DB_AUTO_CREATE_SCHEMA=${env.DB_AUTO_CREATE_SCHEMA}; ` +
      `DB_AUTO_CREATE_DEFAULT_ADMIN=${env.DB_AUTO_CREATE_DEFAULT_ADMIN}; ` +
      `WEB_CONCURRENCY=${env.WEB_CONCURRENCY}; market-data/provider flags disabled.`,
  );
}

function psqlArgs() {
  return [
    'exec', '-i', PG_CONTAINER, 'sh', '-c',
    'exec psql -X -qAt -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
  ];
}

function buildRoleSql(role, verifier) {
  return [
    '\\set ON_ERROR_STOP on',
    `\\set runtime_role ${role}`,
    `\\set runtime_verifier ${verifier}`,
    "SELECT format('CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', :'runtime_role', :'runtime_verifier') \\gexec",
    "SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'runtime_role') \\gexec",
    "SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'runtime_role') \\gexec",
    "SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'runtime_role') \\gexec",
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
  const row = stdout.split(/\r?\n/).map((line) => line.trim())
    .find((line) => line.startsWith('{') && line.endsWith('}'));
  if (!row) throw new Error('Runtime-role verification returned no JSON row.');
  return JSON.parse(row);
}

function verifyRuntimePermissions(value, database, role) {
  const truthy = ['login', 'database_connect', 'schema_usage', 'tables_dml', 'sequences_usage_select'];
  const falsy = [
    'superuser', 'create_database', 'create_role', 'replication', 'bypass_rls',
    'database_create', 'schema_create',
  ];
  if (value.database !== database || value.runtime_role !== role) {
    throw new Error('Runtime-role database/role identity differs from the guarded fixture.');
  }
  for (const key of truthy) if (value[key] !== true) throw new Error(`Runtime role check failed: ${key}.`);
  for (const key of falsy) if (value[key] !== false) throw new Error(`Runtime role check failed: ${key}.`);
  if (!Number.isInteger(value.tables_checked) || value.tables_checked < 1) {
    throw new Error('Runtime-role privilege verification covered no existing public tables.');
  }
  const safe = {
    database: value.database,
    runtime_role: value.runtime_role,
    login: value.login,
    superuser: value.superuser,
    create_database: value.create_database,
    create_role: value.create_role,
    replication: value.replication,
    bypass_rls: value.bypass_rls,
    database_connect: value.database_connect,
    database_create: value.database_create,
    schema_usage: value.schema_usage,
    schema_create: value.schema_create,
    tables_dml: value.tables_dml,
    tables_checked: value.tables_checked,
    sequences_usage_select: value.sequences_usage_select,
    sequences_checked: value.sequences_checked,
  };
  appendReceipt(`Least-privilege runtime role verified: ${JSON.stringify(safe)}.`);
  appendReceipt('The app role has no database/schema CREATE or elevated attributes; it has only public USAGE, existing-table DML, and existing-sequence USAGE/SELECT.');
}

function captureSchemaFingerprint(stage) {
  const result = runStage(stage, [
    'exec', PG_CONTAINER, 'sh', '-c',
    'exec pg_dump --schema-only --no-owner --no-privileges --username "$POSTGRES_USER" "$POSTGRES_DB"',
  ], { timeoutMs: 45_000 });
  requireSuccess(result, stage);
  const dump = result.stdout;
  const raw = crypto.createHash('sha256').update(dump).digest('hex');
  const normalizedDump = dump.replace(/^\\(?:restrict|unrestrict)\s+\S+\s*\r?\n/gm, '');
  const normalized = crypto.createHash('sha256').update(normalizedDump).digest('hex');
  appendReceipt(
    `  schema_dump_raw_sha256=${raw}; normalized_sha256=${normalized}; bytes=${Buffer.byteLength(dump)}; normalization removes only random-token PostgreSQL \\restrict/\\unrestrict metadata command lines; dump data is not written to disk.`,
  );
  return normalized;
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
    return {'pid': pid, 'ppid': int(parent), 'name': name.strip(), 'cmd': read_cmd(pid)}

infos = {}
for item in Path('/proc').iterdir():
    if item.name.isdigit():
        try:
            infos[int(item.name)] = read_info(int(item.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
pid1 = infos.get(1, {'pid': 1, 'ppid': 0, 'name': '', 'cmd': ''})
children = sorted((p for p in infos.values() if p['ppid'] == 1 and p['pid'] != os.getpid()), key=lambda p: p['pid'])
masters = [p for p in children if 'gunicorn' in p['cmd'].lower() and 'app.main:app' in p['cmd']]
master = masters[0] if len(masters) == 1 else None
healthchecks = [p for p in children if p['name'].lower().startswith('python') and 'urllib.request.urlopen' in p['cmd'] and '/health' in p['cmd']]
unexpected = [p for p in children if p not in masters and p not in healthchecks]
workers = sorted((p for p in infos.values() if master and p['ppid'] == master['pid']), key=lambda p: p['pid'])
print(json.dumps({'pid1': pid1, 'pid1_children': children, 'master': master, 'workers': workers, 'healthcheck_children': healthchecks, 'unexpected_pid1_children': unexpected}, sort_keys=True))
`;

function parseJsonLine(stdout, description) {
  const line = stdout.split(/\r?\n/).map((item) => item.trim()).find((item) => item.startsWith('{'));
  if (!line) throw new Error(`${description} returned no JSON summary.`);
  return JSON.parse(line);
}

function inspectProcessTree() {
  const result = runStage('inspect init, Gunicorn master, and two workers', [
    'exec', '-i', APP_CONTAINER, 'python', '-',
  ], { input: PROCESS_TREE_PROBE, stdinDescription: 'read-only /proc PID and command probe' });
  requireSuccess(result, 'inspect process tree');
  const report = parseJsonLine(result.stdout, 'Process-tree probe');
  if (!/(?:tini|docker-init|\/dev\/init)/i.test(report.pid1?.cmd ?? '')) {
    throw new Error('Container PID 1 is not Docker init/tini.');
  }
  if (!report.master || report.unexpected_pid1_children?.length !== 0) {
    throw new Error('PID 1 does not directly own exactly one Gunicorn master, apart from approved healthcheck children.');
  }
  if (report.workers?.length !== 2 || report.workers.some((worker) => !/gunicorn|app\.main:app/i.test(worker.cmd))) {
    throw new Error('Expected exactly two Gunicorn application workers under the master.');
  }
  const safe = {
    pid1: report.pid1,
    master: report.master,
    workers: report.workers,
    healthcheck_children: report.healthcheck_children,
  };
  appendReceipt(`Live process tree: ${JSON.stringify(safe)}.`);
  appendFilteredLog(`allowlisted_process_tree=${JSON.stringify(safe)}`);
  return {
    masterPid: report.master.pid,
    workerPids: report.workers.map((worker) => worker.pid).sort((a, b) => a - b),
  };
}

function extractPids(text, regex, embeddedPid = false) {
  const values = [];
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(regex);
    if (!match) continue;
    const loggerPid = Number(match[1]);
    if (embeddedPid && Number(match[2]) !== loggerPid) continue;
    values.push(loggerPid);
  }
  return [...new Set(values)].sort((a, b) => a - b);
}

const STARTUP_COMPLETE = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Application startup complete\.\s*$/;
const STARTED_SERVER = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Started server process \[(\d+)\]\s*$/;
const SHUTDOWN_COMPLETE = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Application shutdown complete\.?\s*$/;
const FINISHED_SERVER = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Finished server process \[(\d+)\]\s*$/;
const MASTER_SIGNAL_TERM = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Handling signal: term\s*$/i;
const MASTER_SHUTDOWN = /^\S.*?\[(\d+)\]\s+\[INFO\]\s+Shutting down: Master\s*$/i;

function readContainerLogs(stage) {
  const result = runStage(stage, ['logs', '--timestamps', APP_CONTAINER], {
    timeoutMs: 30_000,
    logFailure: false,
  });
  requireSuccess(result, stage);
  return combinedOutput(result);
}

async function waitForReadiness() {
  const deadline = Date.now() + WATCHDOG_MS;
  appendReceipt(`Startup watchdog started at ${utcNow()} UTC; budget=${WATCHDOG_MS}ms.`);
  while (Date.now() < deadline) {
    const stateResult = runStage('poll app state and Docker health', [
      'inspect', '--format', INSPECT_APP_STATE, APP_CONTAINER,
    ]);
    requireSuccess(stateResult, 'poll app state and health');
    const [status, health, exitCode, oomKilled] = stateResult.stdout.trim().split('|');
    if (status !== 'running') throw new Error(`App exited before readiness: status=${status}; exit=${exitCode}; oom=${oomKilled}.`);
    if (health === 'unhealthy') throw new Error('Docker healthcheck reached unhealthy.');

    const logs = readContainerLogs('read startup markers from combined stdout/stderr');
    const startedPids = extractPids(logs, STARTED_SERVER, true);
    const readyPids = extractPids(logs, STARTUP_COMPLETE);
    appendReceipt(`  readiness poll: health=${health}; uvicorn_started_pids=${JSON.stringify(startedPids)}; startup_complete_pids=${JSON.stringify(readyPids)}.`);
    if (health === 'healthy' && readyPids.length === 2 && JSON.stringify(readyPids) === JSON.stringify(startedPids)) {
      appendReceipt(`Docker health and both Uvicorn startup-complete events observed at ${utcNow()} UTC.`);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  throw new Error(`Application readiness exceeded the ${WATCHDOG_MS}ms watchdog.`);
}

function inspectAppContainer() {
  const result = runStage('read back app container init/network/ports/mounts/image/command', [
    'inspect', '--format', INSPECT_APP_CONFIG, APP_CONTAINER,
  ]);
  requireSuccess(result, 'inspect app container configuration');
  const fields = result.stdout.trim().split('|');
  if (fields.length !== 9) throw new Error('App configuration inspection returned malformed fields.');
  const [id, imageId, status, init, network, ports, mounts, imageTag, command] = fields;
  if (!/^[a-f0-9]{64}$/i.test(id) || status !== 'running') throw new Error('App container identity/state is invalid.');
  if (imageId !== productionImageId || imageTag !== PROD_IMAGE) throw new Error('App container does not use the inspected source-final image.');
  if (init !== 'true' || network !== NETWORK) throw new Error('App container init/network settings differ from the approved values.');
  if (ports !== 'null' && ports !== '{}') throw new Error('App container unexpectedly publishes host ports.');
  if (mounts !== '[]') throw new Error('App container unexpectedly mounts host paths.');
  if (!command.includes('exec gunicorn app.main:app')) throw new Error('App command does not exec Gunicorn directly.');
  appendReceipt(`App container config: id=${id}; image_id=${imageId}; status=${status}; init=${init}; network=${network}; ports=${ports}; mounts=${mounts}; image=${imageTag}; command=${command}.`);
}

function verifyShutdown(workerPids, masterPid) {
  const logs = readContainerLogs('capture combined stdout/stderr shutdown evidence');
  const signalPids = extractPids(logs, MASTER_SIGNAL_TERM);
  const shutdownPids = extractPids(logs, SHUTDOWN_COMPLETE);
  const finishedPids = extractPids(logs, FINISHED_SERVER, true);
  const masterShutdownPids = extractPids(logs, MASTER_SHUTDOWN);
  const forcedKill = /SIGKILL|did not exit in time|graceful timeout|forced kill|force.kill/i.test(logs);
  const state = runStage('verify final container exit/OOM state', [
    'inspect', '--format', INSPECT_STOPPED_STATE, APP_CONTAINER,
  ]);
  requireSuccess(state, 'verify app stopped state');
  const [status, exitCode, oomKilled] = state.stdout.trim().split('|');
  const expectedWorkers = [...workerPids].sort((a, b) => a - b);
  const evidence = {
    status,
    exit_code: exitCode,
    oom_killed: oomKilled,
    master_pid: masterPid,
    master_term_signal_pids: signalPids,
    application_shutdown_complete_pids: shutdownPids,
    finished_server_process_pids: finishedPids,
    master_shutdown_pids: masterShutdownPids,
    expected_worker_pids: expectedWorkers,
    forced_kill_or_timeout_marker: forcedKill,
  };
  appendReceipt(`Graceful TERM evidence: ${JSON.stringify(evidence)}.`);
  appendFilteredLog(`allowlisted_shutdown_evidence=${JSON.stringify(evidence)}`);
  if (status !== 'exited' || exitCode !== '0' || oomKilled !== 'false') {
    throw new Error(`App did not exit cleanly: status=${status}; exit=${exitCode}; OOM=${oomKilled}.`);
  }
  if (JSON.stringify(signalPids) !== JSON.stringify([masterPid]) ||
      JSON.stringify(shutdownPids) !== JSON.stringify(expectedWorkers) ||
      JSON.stringify(finishedPids) !== JSON.stringify(expectedWorkers) ||
      JSON.stringify(masterShutdownPids) !== JSON.stringify([masterPid]) || forcedKill) {
    throw new Error('TERM shutdown logs do not prove both Uvicorn workers and the Gunicorn master exited cleanly.');
  }
  appendReceipt('Verified both workers emitted Application shutdown complete and Finished server process; master handled TERM and logged shutdown; no Worker exiting message was required.');
}

function verifyNetworkAndPostgres(databaseFromEnv) {
  const network = runStage('verify isolated network is internal bridge', [
    'network', 'inspect', '--format', '{{.Name}}|{{.Driver}}|{{.Internal}}', NETWORK,
  ]);
  requireSuccess(network, 'verify isolated network');
  if (network.stdout.trim() !== `${NETWORK}|bridge|true`) throw new Error('Expected existing internal bridge network was not verified.');

  const pgState = runStage('verify designated PostgreSQL fixture is running', [
    'inspect', '--format', '{{.State.Status}}', PG_CONTAINER,
  ]);
  requireSuccess(pgState, 'verify PostgreSQL fixture state');
  if (pgState.stdout.trim() !== 'running') throw new Error('Designated PostgreSQL fixture is not running.');

  const pgNetwork = runStage('verify PostgreSQL fixture is attached to internal network', [
    'inspect', '--format', `{{if index .NetworkSettings.Networks "${NETWORK}"}}attached{{else}}missing{{end}}`, PG_CONTAINER,
  ]);
  requireSuccess(pgNetwork, 'verify PostgreSQL network attachment');
  if (pgNetwork.stdout.trim() !== 'attached') throw new Error('PostgreSQL fixture is not on the approved internal network.');

  const identity = runStage('read PostgreSQL fixture database identity', [
    'exec', PG_CONTAINER, 'sh', '-c', 'printf "%s\\n%s\\n" "$POSTGRES_DB" "$POSTGRES_USER"',
  ]);
  requireSuccess(identity, 'read PostgreSQL database identity');
  const [database, postgresUser] = identity.stdout.replace(/\r/g, '').trimEnd().split('\n');
  if (!postgresUser || database !== databaseFromEnv || !/^iter202_[A-Za-z0-9_]+$/.test(database)) {
    throw new Error('PostgreSQL identity does not match the one-time iter202_ Compose fixture.');
  }
  appendReceipt(`PostgreSQL fixture identity verified: database=${database}; username omitted.`);
  return database;
}

function verifyImages() {
  const prod = runStage('inspect source-final production image', [
    'image', 'inspect', '--format', '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Cmd}}', PROD_IMAGE,
  ]);
  requireSuccess(prod, 'inspect production image');
  const [imageId, osName, architecture, command] = prod.stdout.trim().split('|');
  if (!/^sha256:[a-f0-9]{64}$/i.test(imageId) || osName !== 'linux' || architecture !== 'arm64') {
    throw new Error('Production image is not a valid linux/arm64 source-final image.');
  }
  if (!command.includes('exec gunicorn app.main:app')) throw new Error('Production image does not exec Gunicorn directly.');
  productionImageId = imageId;
  appendReceipt(`Production source-final image verified: tag=${PROD_IMAGE}; id=${imageId}; platform=${osName}/${architecture}; Config.Cmd=${command}.`);

  const peer = runStage('verify cached internal HTTP peer image', [
    'image', 'inspect', '--format', '{{.Id}}', DEV_IMAGE,
  ]);
  requireSuccess(peer, 'inspect peer image');
  if (peer.stdout.trim() !== DEV_IMAGE_ID) throw new Error('Approved internal HTTP peer image digest changed.');
  appendReceipt(`Internal HTTP peer image verified: tag=${DEV_IMAGE}; id=${DEV_IMAGE_ID}.`);
}

function assertTargetNameUnused() {
  const result = runStage('ensure only v5 target container name is unused', [
    'container', 'ls', '--all', '--quiet', '--filter', `name=^/${APP_CONTAINER}$`,
  ]);
  requireSuccess(result, 'check target container name');
  if (result.stdout.trim()) throw new Error(`Refusing to overwrite existing container ${APP_CONTAINER}.`);
}

function requestIndependentHealth() {
  const result = runStage('request health through an independent network peer', [
    'run', '--rm', '--network', NETWORK, '--entrypoint', 'curl', DEV_IMAGE,
    '--fail', '--silent', '--show-error', '--max-time', '20',
    '--write-out', '\\n__HTTP_STATUS__=%{http_code}\\n',
    `http://${APP_CONTAINER}:8000/api/v1/health`,
  ], { timeoutMs: 30_000 });
  requireSuccess(result, 'request independent health');
  const marker = result.stdout.match(/(?:^|\n)__HTTP_STATUS__=(\d{3})\s*$/);
  if (!marker || Number(marker[1]) !== 200) throw new Error('Independent peer did not receive HTTP 200.');
  const body = result.stdout.slice(0, marker.index).trim();
  let health;
  try {
    health = JSON.parse(body);
  } catch {
    throw new Error('Independent API health response was not JSON.');
  }
  if (health.status !== 'healthy' || health.database !== 'healthy') {
    throw new Error('API health response must report status=healthy and database=healthy.');
  }
  const safe = { status: health.status, database: health.database, version: health.version };
  appendReceipt(`Independent internal-network HTTP health: status=200; ${JSON.stringify(safe)}.`);
  appendFilteredLog(`independent_http_health=${JSON.stringify(safe)}`);
}

async function runAcceptance() {
  appendReceipt(`Protected source Compose env=${SOURCE_ENV}; only POSTGRES_DB is read; no env values are logged.`);
  const guardedDatabase = parseComposePostgresDb(SOURCE_ENV);
  const database = verifyNetworkAndPostgres(guardedDatabase);
  verifyImages();
  assertTargetNameUnused();

  const runtimeRole = `iter202_prod_runtime_v5_${crypto.randomBytes(8).toString('hex')}`;
  const runtimePassword = crypto.randomBytes(48).toString('hex');
  const verifier = makeScramVerifier(runtimePassword);
  secrets.add(verifier);
  const runtimeEnv = makeRuntimeEnvironment(database, runtimeRole, runtimePassword);
  writeAppEnv(runtimeEnv);

  const roleResult = runStage('create isolated least-privilege runtime role and read back flags', psqlArgs(), {
    input: buildRoleSql(runtimeRole, verifier),
    stdinDescription: 'fixture-only role/grant SQL; SCRAM verifier redacted and never logged',
    timeoutMs: 30_000,
  });
  requireSuccess(roleResult, 'create and verify runtime role');
  const permissions = parsePermissionJson(roleResult.stdout);
  verifyRuntimePermissions(permissions, database, runtimeRole);

  const beforeFingerprint = captureSchemaFingerprint('capture pre-start schema-only fingerprint');
  appendReceipt(`Pre-start normalized schema fingerprint=${beforeFingerprint}.`);

  appRunAttempted = true;
  const run = runStage('start one isolated source-final app container', [
    'run', '--detach', '--name', APP_CONTAINER, '--init', '--network', NETWORK,
    '--health-retries', '5', '--env-file', APP_ENV, PROD_IMAGE,
  ], { timeoutMs: 60_000 });
  requireSuccess(run, 'start app container');
  const containerId = run.stdout.trim();
  if (!/^[a-f0-9]{12,64}$/i.test(containerId)) throw new Error('Docker did not return a valid target container ID.');
  appendReceipt(`Started target container=${APP_CONTAINER}; id=${containerId}; no host ports, mounts, or command override.`);
  inspectAppContainer();

  await waitForReadiness();
  const { masterPid, workerPids } = inspectProcessTree();
  const startupLogs = readContainerLogs('verify startup PIDs from merged stdout/stderr');
  const startedPids = extractPids(startupLogs, STARTED_SERVER, true);
  const startupPids = extractPids(startupLogs, STARTUP_COMPLETE);
  if (JSON.stringify(startedPids) !== JSON.stringify(workerPids) ||
      JSON.stringify(startupPids) !== JSON.stringify(workerPids)) {
    throw new Error('Uvicorn startup process markers do not match the two live Gunicorn worker PIDs.');
  }
  appendReceipt(`Uvicorn startup evidence from merged stdout/stderr: started_pids=${JSON.stringify(startedPids)}; startup_complete_pids=${JSON.stringify(startupPids)}; master_pid=${masterPid}.`);
  appendFilteredLog(`allowlisted_startup_pids=${JSON.stringify(startupPids)}; master_pid=${masterPid}`);

  requestIndependentHealth();
  const stop = runStage('send real TERM with a 35-second Docker grace period', [
    'stop', '--time', '35', APP_CONTAINER,
  ], { timeoutMs: 50_000 });
  requireSuccess(stop, 'stop app with 35-second grace period');
  verifyShutdown(workerPids, masterPid);

  const afterFingerprint = captureSchemaFingerprint('capture post-shutdown schema-only fingerprint');
  appendReceipt(`Post-shutdown normalized schema fingerprint=${afterFingerprint}.`);
  if (beforeFingerprint !== afterFingerprint) throw new Error('Runtime startup/shutdown changed the database schema.');
  appendReceipt('Schema-only fingerprint unchanged across production runtime startup/shutdown.');
  appendReceipt(`Final result=PASS; finished=${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; target container is stopped and retained.`);
  process.stdout.write(`PASS: receipt=${RECEIPT}; filtered_log=${FILTERED_LOG}; env=${APP_ENV}; container=${APP_CONTAINER} (stopped, retained)\n`);
}

function preserveFailure(error) {
  appendReceipt(`Final result=FAIL; finished=${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; error=${error?.message ?? String(error)}.`);
  if (appRunAttempted) {
    const logs = runStage('failure evidence: capture target logs with both streams', [
      'logs', '--timestamps', APP_CONTAINER,
    ], { timeoutMs: 30_000, logFailure: false });
    if (logs.status === 0) {
      const all = combinedOutput(logs);
      appendFilteredLog(`failure_allowlisted_startup_pids=${JSON.stringify(extractPids(all, STARTUP_COMPLETE))}; shutdown_pids=${JSON.stringify(extractPids(all, SHUTDOWN_COMPLETE))}`);
    }
    const state = runStage('failure evidence: inspect only the v5 target state', [
      'inspect', '--format',
      '{{.Id}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|' +
        '{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}',
      APP_CONTAINER,
    ], { timeoutMs: 20_000, logFailure: false });
    if (state.status === 0) appendReceipt(`Failure target state=${state.stdout.trim()}; container remains untouched/preserved.`);
  }
  appendReceipt('No pre-existing container or database data was changed beyond the authorized iter202_ runtime-role grant setup; the one-shot curl peer is --rm; no runtime role or target app container cleanup is attempted, and all v5 evidence is retained.');
  process.stderr.write(`FAIL: ${redact(error?.message ?? String(error))}; receipt=${RECEIPT}; filtered_log=${FILTERED_LOG}; target container preserved if created.\n`);
}

function main() {
  initializeOutputs();
  runAcceptance().catch((error) => {
    preserveFailure(error);
    process.exitCode = 1;
  });
}

main();
