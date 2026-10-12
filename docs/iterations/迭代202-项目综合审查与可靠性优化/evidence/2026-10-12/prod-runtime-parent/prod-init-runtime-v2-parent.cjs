'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const OUTPUT_DIR = '/tmp/ai-investor-iter200-202-20261012.afLb99';
const SOURCE_ENV = '/tmp/iter202-d12-compose.env';
const APP_ENV = '/tmp/iter202-prod-signal-parent-v2.env';
const RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v2-parent.receipt.md');
const APP_LOG = path.join(OUTPUT_DIR, 'prod-init-runtime-v2-parent.logs.txt');
const PG_CONTAINER = 'iter202-d12-postgres-1';
const NETWORK = 'iter202-d12_backtrader_dev';
const APP_CONTAINER = 'iter202-prod-signal-parent-v2';
const PROD_IMAGE = 'iter202-d14-backend:20261012-init-final';
const PROD_IMAGE_ID =
  'sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9';
const DEV_IMAGE = 'iter202-d12-backend-logdir:20261012-final';
const DEV_IMAGE_ID =
  'sha256:73504cd1d070ec665e3e476bbefbf11d50377ed51f626fe8da9057a27b7ad4cc';
const WATCHDOG_MS = 300_000;
const POLL_MS = 3_000;
const MAX_OUTPUT_BYTES = 64 * 1024 * 1024;
const secrets = new Set();
let outputReady = false;
let appRunAttempted = false;
let lastAppLogSnapshot = { stdout: '', stderr: '' };
let startEpochMs = 0;

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
  if (!outputReady) return;
  fs.appendFileSync(RECEIPT, `${redact(text)}\n`, { encoding: 'utf8', mode: 0o600 });
}

function appendLog(text) {
  if (!outputReady || !text) return;
  fs.appendFileSync(APP_LOG, redact(text), { encoding: 'utf8', mode: 0o600 });
}

function combinedOutput(result) {
  const stdout = result.stdout ?? '';
  const stderr = result.stderr ?? '';
  if (!stderr) return stdout;
  if (!stdout) return stderr;
  return `${stdout}\n[stderr stream]\n${stderr}`;
}

function initializeOutputs() {
  process.umask(0o077);
  fs.mkdirSync(OUTPUT_DIR, { recursive: true, mode: 0o700 });
  for (const target of [RECEIPT, APP_LOG]) {
    if (fs.existsSync(target)) {
      throw new Error(`Refusing to overwrite existing evidence file: ${target}`);
    }
  }
  fs.writeFileSync(
    RECEIPT,
    '# Isolated production init / signal forwarding runtime receipt (v2)\n\n',
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  fs.writeFileSync(
    APP_LOG,
    `# Redacted v2 container log capture; started ${utcNow()} UTC\n`,
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  outputReady = true;
  startEpochMs = Date.now();
  appendReceipt(`Harness started at ${utcNow()} UTC.`);
  appendReceipt(`Receipt: ${RECEIPT}`);
  appendReceipt(`Application log: ${APP_LOG}`);
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
    timeout: options.timeoutMs ?? 30_000,
    env: process.env,
  });
  const finished = utcNow();
  const rc = result.status === null ? `null(signal=${result.signal ?? 'unknown'})` : result.status;
  const command = renderedCommand(binary, args, options.stdinDescription);
  appendReceipt(
    `- ${stage}: started ${started}; finished ${finished}; rc=${rc}; command=${command}`,
  );
  if (result.error) appendReceipt(`  spawn_error=${result.error.message}`);
  if (result.status !== 0 && options.logFailure !== false) {
    appendLog(`\n[${stage} command failure at ${finished}; rc=${rc}]\n${combinedOutput(result) || result.error?.message || ''}\n`);
  }
  return {
    status: result.status,
    signal: result.signal,
    error: result.error,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
    started,
    finished,
    rc,
  };
}

function requireSuccess(result, stage) {
  if (result.status !== 0) {
    throw new Error(`${stage} failed with rc=${result.rc}`);
  }
  return result;
}

function parseComposePostgresDb(filename) {
  const stats = fs.lstatSync(filename);
  if (!stats.isFile() || stats.isSymbolicLink()) {
    throw new Error('Compose env input is not a regular non-symlink file.');
  }
  const mode = stats.mode & 0o777;
  if (mode !== 0o600) {
    throw new Error(`Compose env input mode must be 0600; observed ${mode.toString(8)}.`);
  }
  const text = fs.readFileSync(filename, 'utf8');
  const matches = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^POSTGRES_DB\s*=\s*(.*)$/);
    if (!match) continue;
    let value = match[1].trim();
    if (value.startsWith('"') || value.startsWith("'")) {
      const quote = value[0];
      if (value.at(-1) !== quote) {
        throw new Error('POSTGRES_DB has an unmatched quote in the Compose env input.');
      }
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, '').trim();
    }
    if (value.includes('$')) {
      throw new Error('POSTGRES_DB must be a resolved literal in the Compose env input.');
    }
    matches.push(value);
  }
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one POSTGRES_DB assignment; found ${matches.length}.`);
  }
  const database = matches[0];
  if (!/^iter202_[A-Za-z0-9_]+$/.test(database)) {
    throw new Error('POSTGRES_DB must begin with iter202_ and contain only letters, digits, or _.');
  }
  return database;
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
  const generated = {
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
  for (const [name, value] of Object.entries(generated)) {
    if (/SECRET|PASSWORD|TOKEN|API_KEY|DATABASE_URL/.test(name) && value.length >= 6) {
      secrets.add(value);
    }
  }
  secrets.add(password);
  return generated;
}

function writeAppEnv(env) {
  const contents = Object.entries(env)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n') + '\n';
  const fd = fs.openSync(APP_ENV, 'wx', 0o600);
  try {
    fs.writeFileSync(fd, contents, { encoding: 'utf8' });
    fs.fchmodSync(fd, 0o600);
  } finally {
    fs.closeSync(fd);
  }
  const mode = fs.statSync(APP_ENV).mode & 0o777;
  if (mode !== 0o600) throw new Error(`Generated env file mode is not 0600: ${mode.toString(8)}.`);
  appendReceipt(`Generated application env file with mode 0600: ${APP_ENV}; contents are not logged.`);
}

function psqlCommandArgs() {
  return [
    'exec',
    '-i',
    PG_CONTAINER,
    'sh',
    '-c',
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
  const candidate = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line.startsWith('{') && line.endsWith('}'));
  if (!candidate) throw new Error('Runtime role verification returned no JSON row.');
  return JSON.parse(candidate);
}

function assertRuntimePermissions(value, expectedDatabase, expectedRole) {
  const requiredTrue = [
    'login',
    'database_connect',
    'schema_usage',
    'tables_dml',
    'sequences_usage_select',
  ];
  const requiredFalse = [
    'superuser',
    'create_database',
    'create_role',
    'replication',
    'bypass_rls',
    'database_create',
    'schema_create',
  ];
  if (value.database !== expectedDatabase || value.runtime_role !== expectedRole) {
    throw new Error('Runtime role verification database or role did not match the requested fixture.');
  }
  for (const key of requiredTrue) {
    if (value[key] !== true) throw new Error(`Runtime role permission check failed: ${key} is not true.`);
  }
  for (const key of requiredFalse) {
    if (value[key] !== false) throw new Error(`Runtime role permission check failed: ${key} is not false.`);
  }
  if (!Number.isInteger(value.tables_checked) || value.tables_checked < 1) {
    throw new Error('Runtime role privilege check did not cover any existing public tables.');
  }
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
  const result = runStage(stage, 'docker', schemaDumpCommand(), {
    timeoutMs: 45_000,
    logFailure: true,
  });
  requireSuccess(result, stage);
  const dump = Buffer.from(result.stdout, 'utf8');
  const rawFingerprint = crypto.createHash('sha256').update(dump).digest('hex');
  const normalizedDump = dump
    .toString('utf8')
    .replace(/^\\(?:restrict|unrestrict)\s+\S+\s*\r?\n/gm, '');
  const normalizedFingerprint = crypto.createHash('sha256').update(normalizedDump).digest('hex');
  appendReceipt(
    `  schema_only_dump_raw_sha256=${rawFingerprint}; normalized_sha256=${normalizedFingerprint}; bytes=${dump.length}; normalization=remove only PostgreSQL \\restrict and \\unrestrict metadata command lines (random tokens); no table data captured or persisted.`,
  );
  return normalizedFingerprint;
}

function appendNewAppLogSnapshot() {
  const result = runStage('capture application logs', 'docker', ['logs', '--timestamps', APP_CONTAINER], {
    timeoutMs: 20_000,
    logFailure: true,
  });
  requireSuccess(result, 'capture application logs');
  const current = { stdout: result.stdout ?? '', stderr: result.stderr ?? '' };
  const deltas = [];
  for (const stream of ['stdout', 'stderr']) {
    const previous = lastAppLogSnapshot[stream];
    if (current[stream] === previous) continue;
    if (current[stream].startsWith(previous)) {
      deltas.push(`[${stream}]\n${current[stream].slice(previous.length)}`);
    } else {
      deltas.push(`[${stream} snapshot reset at ${utcNow()} UTC]\n${current[stream]}`);
    }
  }
  const delta = deltas.join('\n');
  if (delta) appendLog(`\n${delta}\n`);
  lastAppLogSnapshot = current;
  return combinedOutput(current);
}

function countMatches(text, regex) {
  return [...text.matchAll(regex)].length;
}

function inspectAppRuntime() {
  const format =
    '{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|' +
    '{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}';
  const result = runStage('verify app container isolation and command', 'docker', [
    'inspect',
    '--format',
    format,
    APP_CONTAINER,
  ]);
  requireSuccess(result, 'verify app container isolation and command');
  const fields = result.stdout.trim().split('|');
  if (fields.length < 6) throw new Error('Container isolation inspection was malformed.');
  const [init, network, ports, mounts, image, command] = fields;
  if (init !== 'true') throw new Error('Application container does not have Docker init enabled.');
  if (network !== NETWORK) throw new Error(`Application container network mismatch: ${network}.`);
  if (ports !== 'null' && ports !== '{}') throw new Error('Application container unexpectedly publishes host ports.');
  if (mounts !== '[]') throw new Error('Application container unexpectedly has mounts.');
  if (image !== PROD_IMAGE) throw new Error('Application container image tag differs from the approved image.');
  if (!command.includes('exec gunicorn app.main:app')) {
    throw new Error('Application container command does not exec Gunicorn directly.');
  }
  appendReceipt(`  readback: init=${init}; network=${network}; ports=${ports}; mounts=${mounts}; image=${image}; command=${command}`);
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
pid1_children = sorted(
    (p for p in infos.values() if p['ppid'] == 1 and p['pid'] != os.getpid()),
    key=lambda p: p['pid'],
)
masters = [p for p in pid1_children if 'gunicorn' in p['cmd'].lower() and 'app.main:app' in p['cmd']]
master = masters[0] if len(masters) == 1 else None
healthchecks = [
    p for p in pid1_children
    if p['name'].lower().startswith('python')
    and 'urllib.request.urlopen' in p['cmd']
    and '/health' in p['cmd']
]
unexpected_pid1_children = [p for p in pid1_children if p not in masters and p not in healthchecks]
workers = sorted(
    (p for p in infos.values() if master and p['ppid'] == master['pid']),
    key=lambda p: p['pid'],
)
print(json.dumps({
    'pid1': pid1,
    'pid1_children': pid1_children,
    'master': master,
    'workers': workers,
    'healthcheck_children': healthchecks,
    'unexpected_pid1_children': unexpected_pid1_children,
}, sort_keys=True))
`;

function inspectProcessTree() {
  const result = runStage('inspect PID 1, Gunicorn master, and workers', 'docker', [
    'exec',
    APP_CONTAINER,
    'python',
    '-c',
    PROCESS_TREE_PROBE,
  ]);
  requireSuccess(result, 'inspect process tree');
  const line = result.stdout.split(/\r?\n/).map((item) => item.trim()).find((item) => item.startsWith('{'));
  if (!line) throw new Error('Container process probe returned no JSON.');
  const report = JSON.parse(line);
  const pid1Command = report.pid1?.cmd ?? '';
  if (!/(?:tini|docker-init|\/dev\/init)/i.test(pid1Command)) {
    throw new Error('PID 1 is not the Docker init/tini process.');
  }
  if (!report.master || report.unexpected_pid1_children?.length !== 0) {
    throw new Error('PID 1 does not directly own exactly one Gunicorn master (excluding only its known healthcheck and the probe itself).');
  }
  if (report.workers?.length !== 2) {
    throw new Error(`Expected exactly two Gunicorn worker children; observed ${report.workers?.length ?? 0}.`);
  }
  if (report.workers.some((worker) => !/gunicorn|app\.main:app/i.test(worker.cmd))) {
    throw new Error('A direct Gunicorn master child did not identify as an application worker.');
  }
  const safeJson = redact(JSON.stringify(report));
  appendReceipt(`  process_tree=${safeJson}`);
  appendLog(`\n[PID tree at ${utcNow()} UTC]\n${safeJson}\n`);
  return report;
}

function parseContainerState(stdout) {
  const [status, health, exitCode, oomKilled] = stdout.trim().split('|');
  return { status, health, exitCode, oomKilled };
}

async function waitForReadiness() {
  const watchStarted = Date.now();
  const deadline = watchStarted + WATCHDOG_MS;
  appendReceipt(`Readiness watchdog started at ${utcNow()} UTC; budget=${WATCHDOG_MS}ms.`);
  while (Date.now() < deadline) {
    const stateResult = runStage('poll app state and health', 'docker', [
      'inspect',
      '--format',
      '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}',
      APP_CONTAINER,
    ]);
    requireSuccess(stateResult, 'poll app state and health');
    const state = parseContainerState(stateResult.stdout);
    if (state.status !== 'running') {
      throw new Error(`Application container stopped before healthy state: ${JSON.stringify(state)}.`);
    }
    if (state.health === 'unhealthy') {
      throw new Error('Application Docker healthcheck reached unhealthy.');
    }
    const logs = appendNewAppLogSnapshot();
    const readyCount = countMatches(logs, /Application ready - accepting requests/g);
    const readOnlyRevisionCount = countMatches(
      logs,
      /Database migration revision verified \(startup performed no DDL\)/g,
    );
    appendReceipt(
      `  observed health=${state.health}; ready_messages=${readyCount}; readonly_revision_checks=${readOnlyRevisionCount}.`,
    );
    if (state.health === 'healthy' && readyCount >= 2 && readOnlyRevisionCount >= 2) {
      appendReceipt(`Readiness passed at ${utcNow()} UTC.`);
      return logs;
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  throw new Error(`Application readiness exceeded the ${WATCHDOG_MS}ms watchdog.`);
}

function checkGracefulShutdown(logs, state) {
  const workerExitCount = countMatches(logs, /Worker exiting \(pid:/g);
  const appShutdownCount = countMatches(logs, /Application shutdown complete\.?/g);
  const masterShutdown = /Shutting down: Master/i.test(logs);
  const forcedKill = /SIGKILL|did not exit in time|force.?kill/i.test(logs);
  appendReceipt(
    `Shutdown evidence: status=${state.status}; exit_code=${state.exitCode}; oom_killed=${state.oomKilled}; worker_exit_lines=${workerExitCount}; app_shutdown_complete=${appShutdownCount}; master_shutdown=${masterShutdown}; forced_kill_marker=${forcedKill}.`,
  );
  if (state.status !== 'exited' || state.exitCode !== '0' || state.oomKilled !== 'false') {
    throw new Error('Container did not exit cleanly with OOMKilled=false.');
  }
  if (workerExitCount < 2 || appShutdownCount < 2 || !masterShutdown || forcedKill) {
    throw new Error('Graceful shutdown did not prove two worker exits and Gunicorn master shutdown without force-kill.');
  }
}

async function runAcceptance() {
  appendReceipt(`Source Compose env input: ${SOURCE_ENV}; its contents are never logged.`);
  const databaseFromEnv = parseComposePostgresDb(SOURCE_ENV);
  appendReceipt(`POSTGRES_DB validated with iter202_ prefix: ${databaseFromEnv}.`);

  const prodImage = runStage('inspect approved production image', 'docker', [
    'image',
    'inspect',
    '--format',
    '{{.Id}}|{{.Os}}|{{.Architecture}}|{{json .Config.Cmd}}',
    PROD_IMAGE,
  ]);
  requireSuccess(prodImage, 'inspect approved production image');
  const [prodId, prodOs, prodArch, prodCmd] = prodImage.stdout.trim().split('|');
  if (prodId !== PROD_IMAGE_ID || prodOs !== 'linux' || prodArch !== 'arm64') {
    throw new Error('Production image digest/platform differs from the approved final image.');
  }
  if (!prodCmd.includes('exec gunicorn app.main:app')) {
    throw new Error('Production image Config.Cmd is not the approved exec Gunicorn command.');
  }
  appendReceipt(`Production image readback: id=${prodId}; platform=${prodOs}/${prodArch}; cmd=${prodCmd}.`);

  const devImage = runStage('inspect cached curl peer image', 'docker', [
    'image',
    'inspect',
    '--format',
    '{{.Id}}',
    DEV_IMAGE,
  ]);
  requireSuccess(devImage, 'inspect cached curl peer image');
  if (devImage.stdout.trim() !== DEV_IMAGE_ID) {
    throw new Error('Cached development curl peer image digest differs from the approved image.');
  }
  appendReceipt(`Curl peer image readback: id=${devImage.stdout.trim()}; network-only, no mounts or ports.`);

  const networkResult = runStage('inspect existing isolated network', 'docker', [
    'network',
    'inspect',
    '--format',
    '{{.Name}}|{{.Driver}}|{{.Internal}}',
    NETWORK,
  ]);
  requireSuccess(networkResult, 'inspect existing isolated network');
  if (networkResult.stdout.trim() !== `${NETWORK}|bridge|true`) {
    throw new Error('Expected existing internal bridge network was not found.');
  }

  const pgState = runStage('inspect existing isolated PostgreSQL state', 'docker', [
    'inspect',
    '--format',
    '{{.State.Status}}',
    PG_CONTAINER,
  ]);
  requireSuccess(pgState, 'inspect existing isolated PostgreSQL state');
  if (pgState.stdout.trim() !== 'running') throw new Error('The designated PostgreSQL fixture is not running.');

  const pgNetwork = runStage('verify PostgreSQL network attachment', 'docker', [
    'inspect',
    '--format',
    `{{if index .NetworkSettings.Networks "${NETWORK}"}}attached{{else}}missing{{end}}`,
    PG_CONTAINER,
  ]);
  requireSuccess(pgNetwork, 'verify PostgreSQL network attachment');
  if (pgNetwork.stdout.trim() !== 'attached') {
    throw new Error('The designated PostgreSQL fixture is not attached to the isolated network.');
  }

  const nameCheck = runStage('ensure target app container name is unused', 'docker', [
    'container',
    'ls',
    '--all',
    '--quiet',
    '--filter',
    `name=^/${APP_CONTAINER}$`,
  ]);
  requireSuccess(nameCheck, 'ensure target app container name is unused');
  if (nameCheck.stdout.trim()) {
    throw new Error(`Refusing to overwrite existing target container ${APP_CONTAINER}.`);
  }

  const pgIdentity = runStage('read PostgreSQL fixture database identity', 'docker', [
    'exec',
    PG_CONTAINER,
    'sh',
    '-c',
    'printf "%s\\n%s\\n" "$POSTGRES_DB" "$POSTGRES_USER"',
  ]);
  requireSuccess(pgIdentity, 'read PostgreSQL fixture database identity');
  const [database, postgresUser] = pgIdentity.stdout.replace(/\r/g, '').trimEnd().split('\n');
  if (!postgresUser || database !== databaseFromEnv || !/^iter202_[A-Za-z0-9_]+$/.test(database)) {
    throw new Error('PostgreSQL container database identity does not match the guarded Compose fixture.');
  }
  appendReceipt(`PostgreSQL container confirms the same isolated database: ${database}; user value omitted.`);

  const runtimeRole = `iter202_prod_runtime_v2_${crypto.randomBytes(8).toString('hex')}`;
  const runtimePassword = crypto.randomBytes(48).toString('hex');
  const verifier = makeScramVerifier(runtimePassword);
  secrets.add(verifier);
  const env = makeRuntimeEnvironment(database, runtimeRole, runtimePassword);
  writeAppEnv(env);

  const psqlInput = buildRoleSql(runtimeRole, verifier);
  const roleResult = runStage('create least-privilege runtime role and verify grants', 'docker', psqlCommandArgs(), {
    input: psqlInput,
    stdinDescription: 'SQL role/grant script; SCRAM verifier redacted and never logged',
    timeoutMs: 30_000,
  });
  requireSuccess(roleResult, 'create runtime role and verify grants');
  const permissions = parsePermissionJson(roleResult.stdout);
  assertRuntimePermissions(permissions, database, runtimeRole);
  const safePermissions = {
    database: permissions.database,
    runtime_role: permissions.runtime_role,
    login: permissions.login,
    superuser: permissions.superuser,
    create_database: permissions.create_database,
    create_role: permissions.create_role,
    replication: permissions.replication,
    bypass_rls: permissions.bypass_rls,
    database_connect: permissions.database_connect,
    database_create: permissions.database_create,
    schema_usage: permissions.schema_usage,
    schema_create: permissions.schema_create,
    tables_dml: permissions.tables_dml,
    tables_checked: permissions.tables_checked,
    sequences_usage_select: permissions.sequences_usage_select,
    sequences_checked: permissions.sequences_checked,
  };
  appendReceipt(`Runtime role verified: ${JSON.stringify(safePermissions)}.`);
  appendReceipt('Runtime role receives public schema USAGE, existing-table SELECT/INSERT/UPDATE/DELETE, and existing-sequence USAGE/SELECT; database CONNECT is verified as available, with no explicit CONNECT grant, database/schema CREATE, or elevated role attributes.');

  const beforeFingerprint = captureSchemaFingerprint('capture pre-start schema-only fingerprint');
  appendReceipt(`Pre-start schema-only fingerprint: ${beforeFingerprint}.`);

  appRunAttempted = true;
  const run = runStage('start isolated production runtime container', 'docker', [
    'run',
    '--detach',
    '--name',
    APP_CONTAINER,
    '--init',
    '--network',
    NETWORK,
    '--health-retries',
    '5',
    '--env-file',
    APP_ENV,
    PROD_IMAGE,
  ]);
  requireSuccess(run, 'start isolated production runtime container');
  if (!/^[a-f0-9]{12,64}$/i.test(run.stdout.trim())) {
    throw new Error('Docker did not return a valid container ID for the target app container.');
  }
  appendReceipt(`Started only ${APP_CONTAINER}; container_id=${run.stdout.trim()}; no host port, mount, or command override.`);
  inspectAppRuntime();

  let startupLogs = await waitForReadiness();
  inspectProcessTree();

  const curl = runStage('request API health through independent curl peer', 'docker', [
    'run',
    '--rm',
    '--network',
    NETWORK,
    '--entrypoint',
    'curl',
    DEV_IMAGE,
    '--fail',
    '--silent',
    '--show-error',
    '--max-time',
    '20',
    '--write-out',
    '\\n__HTTP_STATUS__=%{http_code}\\n',
    `http://${APP_CONTAINER}:8000/api/v1/health`,
  ], { timeoutMs: 30_000 });
  requireSuccess(curl, 'request API health through independent curl peer');
  const match = curl.stdout.match(/(?:^|\n)__HTTP_STATUS__=(\d{3})\s*$/);
  if (!match) throw new Error('Curl peer did not return an HTTP status marker.');
  const statusCode = Number(match[1]);
  const body = curl.stdout.slice(0, match.index).trim();
  if (statusCode !== 200) throw new Error(`API health endpoint returned HTTP ${statusCode}.`);
  let healthJson;
  try {
    healthJson = JSON.parse(body);
  } catch {
    throw new Error('API health endpoint returned HTTP 200 but its body was not JSON.');
  }
  const safeHealth = redact(JSON.stringify(healthJson));
  if (healthJson.status !== 'healthy' || healthJson.database !== 'healthy') {
    throw new Error('API health JSON must report status=healthy and database=healthy.');
  }
  appendReceipt(`Independent health peer response: HTTP ${statusCode}; JSON=${safeHealth}.`);
  appendLog(`\n[Independent API health response at ${utcNow()} UTC]\nHTTP ${statusCode}\n${safeHealth}\n`);

  const stop = runStage('stop app with 35 second grace period', 'docker', [
    'stop',
    '--time',
    '35',
    APP_CONTAINER,
  ], { timeoutMs: 50_000 });
  requireSuccess(stop, 'stop app with 35 second grace period');
  startupLogs = appendNewAppLogSnapshot();
  const finalInspect = runStage('verify stopped app exit and OOM state', 'docker', [
    'inspect',
    '--format',
    '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}',
    APP_CONTAINER,
  ]);
  requireSuccess(finalInspect, 'verify stopped app exit and OOM state');
  // The shutdown inspection intentionally has only status, exit code, and OOM state.
  const [finalStatus, finalExitCode, finalOomKilled] = finalInspect.stdout.trim().split('|');
  const finalState = {
    status: finalStatus,
    exitCode: finalExitCode,
    oomKilled: finalOomKilled,
  };
  checkGracefulShutdown(startupLogs, finalState);

  const afterFingerprint = captureSchemaFingerprint('capture post-shutdown schema-only fingerprint');
  appendReceipt(`Post-shutdown schema-only fingerprint: ${afterFingerprint}.`);
  if (beforeFingerprint !== afterFingerprint) {
    throw new Error('Application startup/shutdown changed the database schema fingerprint.');
  }
  appendReceipt('Schema-only fingerprint is unchanged across app startup and shutdown.');
  appendReceipt(`Final result: PASS at ${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; app container ${APP_CONTAINER} is stopped but preserved.`);
  process.stdout.write(`PASS: receipt=${RECEIPT}; logs=${APP_LOG}; env_file=${APP_ENV}; container=${APP_CONTAINER} (stopped, retained)\n`);
}

async function preserveFailureEvidence(error) {
  appendReceipt(`Final result: FAIL at ${utcNow()} UTC; elapsed_ms=${Date.now() - startEpochMs}; error=${error?.message ?? String(error)}.`);
  if (appRunAttempted) {
    const logResult = runStage('failure evidence: capture target app logs', 'docker', [
      'logs',
      '--timestamps',
      APP_CONTAINER,
    ], { timeoutMs: 20_000, logFailure: true });
    if (logResult.status === 0) {
      appendLog(`\n[Failure final app log snapshot at ${utcNow()} UTC]\n${combinedOutput(logResult)}`);
    }
    const inspectResult = runStage('failure evidence: inspect target app state', 'docker', [
      'inspect',
      '--format',
      '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}',
      APP_CONTAINER,
    ], { timeoutMs: 20_000, logFailure: true });
    if (inspectResult.status === 0) {
      appendReceipt(`  failure_container_state=${inspectResult.stdout.trim()}; container remains preserved.`);
    }
  }
  appendReceipt(`No target app container removal or database cleanup was attempted. Evidence files remain mode 0600.`);
  process.stderr.write(`FAIL: ${redact(error?.message ?? String(error))}; receipt=${RECEIPT}; logs=${APP_LOG}; container is preserved if it was created.\n`);
}

async function main() {
  initializeOutputs();
  try {
    await runAcceptance();
  } catch (error) {
    await preserveFailureEvidence(error);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  if (outputReady) {
    appendReceipt(`Harness fatal error at ${utcNow()} UTC: ${error?.message ?? String(error)}.`);
  }
  process.stderr.write(`Harness fatal error: ${redact(error?.message ?? String(error))}\n`);
  process.exitCode = 1;
});
