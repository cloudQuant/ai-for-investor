'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const OUTPUT_DIR = '/tmp/ai-investor-iter200-202-20261012.afLb99';
const V2_RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v2-parent.receipt.md');
const V3_RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v3-parent.receipt.md');
const V3_LOG = path.join(OUTPUT_DIR, 'prod-init-runtime-v3-parent.logs.txt');
const RECEIPT = path.join(OUTPUT_DIR, 'prod-init-runtime-v4-readback-parent.receipt.md');
const FILTERED_LOG = path.join(OUTPUT_DIR, 'prod-init-runtime-v4-readback-parent.logs.txt');
const PG_CONTAINER = 'iter202-d12-postgres-1';
const NETWORK = 'iter202-d12_backtrader_dev';
const APP_CONTAINER = 'iter202-prod-signal-parent-v2';
const PROD_IMAGE = 'iter202-d14-backend:20261012-init-final';
const PROD_IMAGE_ID =
  'sha256:c26c5cc1791a8e27ce9612dc3e093fade4a402425fab525686c000e710ea3ba9';
const MAX_OUTPUT_BYTES = 64 * 1024 * 1024;
let outputReady = false;
let startedAt = 0;

function utcNow() {
  return new Date().toISOString();
}

function appendReceipt(message) {
  if (outputReady) {
    fs.appendFileSync(RECEIPT, String(message) + '\n', { encoding: 'utf8', mode: 0o600 });
  }
}

function appendFiltered(message) {
  if (outputReady) {
    fs.appendFileSync(FILTERED_LOG, String(message) + '\n', { encoding: 'utf8', mode: 0o600 });
  }
}

function initializeOutputs() {
  process.umask(0o077);
  fs.mkdirSync(OUTPUT_DIR, { recursive: true, mode: 0o700 });
  for (const filename of [RECEIPT, FILTERED_LOG]) {
    if (fs.existsSync(filename)) throw new Error('Refusing to overwrite v4 evidence: ' + filename);
  }
  fs.writeFileSync(
    RECEIPT,
    '# Read-only production shutdown/schema readback receipt (v4)\n\n',
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  fs.writeFileSync(
    FILTERED_LOG,
    '# v4 allowlisted readback evidence; started ' + utcNow() + ' UTC\n',
    { encoding: 'utf8', flag: 'wx', mode: 0o600 },
  );
  outputReady = true;
  startedAt = Date.now();
  appendReceipt('Readback-only harness started ' + utcNow() + ' UTC.');
  appendReceipt('The harness will not start, stop, remove, recreate, or modify any container, network, role, database, volume, or image.');
  appendReceipt('It will inspect only stopped container ' + APP_CONTAINER + ' and the existing iter202 PostgreSQL fixture.');
}

function combinedOutput(result) {
  const stdout = result.stdout ?? '';
  const stderr = result.stderr ?? '';
  if (!stderr) return stdout;
  if (!stdout) return stderr;
  return stdout + '\n[stderr stream]\n' + stderr;
}

function renderedCommand(args) {
  return ['docker', ...args].map((value) => JSON.stringify(String(value))).join(' ');
}

function isAllowedPostgresProbe(args) {
  if (args[0] !== 'exec') return true;
  let position = 1;
  if (args[position] === '-i') position += 1;
  if (args[position] !== PG_CONTAINER ||
      args[position + 1] !== 'sh' ||
      args[position + 2] !== '-c' ||
      args.length !== position + 4) {
    return false;
  }
  const command = args[position + 3];
  return command ===
      'exec psql -X -qAt --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "SELECT current_database()"' ||
    command ===
      'exec pg_dump --schema-only --no-owner --no-privileges --username "$POSTGRES_USER" "$POSTGRES_DB"';
}

function runReadOnlyDocker(stage, args, options = {}) {
  const allowed = new Set(['inspect', 'logs', 'network', 'exec']);
  if (!allowed.has(args[0])) throw new Error('Refusing non-readback Docker subcommand: ' + args[0] + '.');
  if (!isAllowedPostgresProbe(args)) {
    throw new Error('Readback harness permits only the exact read-only PostgreSQL identity and schema-only probes.');
  }
  const began = utcNow();
  const result = spawnSync('docker', args, {
    encoding: 'utf8',
    maxBuffer: MAX_OUTPUT_BYTES,
    timeout: options.timeoutMs ?? 45_000,
  });
  const finished = utcNow();
  const rc = result.status === null ? 'null(signal=' + (result.signal ?? 'unknown') + ')' : result.status;
  appendReceipt('- ' + stage + ': started ' + began + '; finished ' + finished +
    '; rc=' + rc + '; command=' + renderedCommand(args) + '.');
  if (result.error) appendReceipt('  spawn_error=' + result.error.message);
  if (result.status !== 0) appendFiltered('[' + stage + ' failed; raw stdout/stderr withheld; rc=' + rc + ']');
  return {
    status: result.status,
    rc,
    stdout: result.stdout ?? '',
    stderr: result.stderr ?? '',
  };
}

function requireSuccess(result, stage) {
  if (result.status !== 0) throw new Error(stage + ' failed with rc=' + result.rc + '.');
  return result;
}

function readEvidenceFile(filename, label) {
  const stats = fs.lstatSync(filename);
  if (!stats.isFile() || stats.isSymbolicLink() || (stats.mode & 0o777) !== 0o600) {
    throw new Error(label + ' must be a regular mode-0600 file.');
  }
  return fs.readFileSync(filename, 'utf8');
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function parseJsonLine(contents, regex, label) {
  const match = contents.match(regex);
  if (!match) throw new Error('Could not read ' + label + ' from the existing receipt.');
  try {
    return JSON.parse(match[1]);
  } catch {
    throw new Error('The existing ' + label + ' evidence is malformed.');
  }
}

function sorted(values) {
  return [...values].sort((left, right) => left - right);
}

function assertExactPidList(actual, expected, label) {
  if (JSON.stringify(sorted(actual)) !== JSON.stringify(sorted(expected))) {
    throw new Error(label + ' PID list does not exactly match the v3 worker snapshot.');
  }
}

function readPriorEvidence() {
  const v2 = readEvidenceFile(V2_RECEIPT, 'v2 baseline receipt');
  const v3 = readEvidenceFile(V3_RECEIPT, 'v3 receipt');
  const v3Log = readEvidenceFile(V3_LOG, 'v3 filtered evidence log');
  const database = v2.match(/^POSTGRES_DB validated with iter202_ prefix: ([A-Za-z0-9_]+)\.$/m)?.[1];
  const baselineHash = v2.match(/^Pre-start schema-only fingerprint: ([a-f0-9]{64})\.$/m)?.[1];
  const containerId = v2.match(
    /^Started only iter202-prod-signal-parent-v2; container_id=([a-f0-9]{64});/m,
  )?.[1];
  if (!database || !/^iter202_[A-Za-z0-9_]+$/.test(database) || !baselineHash || !containerId) {
    throw new Error('The v2 receipt lacks the guarded database, container, or pre-start schema hash.');
  }

  const processTree = parseJsonLine(
    v3,
    /^Audited process tree re-read: (\{.*\})\.$/m,
    'audited process tree',
  );
  if (!Number.isInteger(processTree.master?.pid) || processTree.workers?.length !== 2) {
    throw new Error('The v3 receipt lacks the expected one-master/two-worker PID snapshot.');
  }
  const masterPid = processTree.master.pid;
  const workerPids = sorted(processTree.workers.map((worker) => worker.pid));
  if (workerPids.some((pid) => !Number.isInteger(pid)) || new Set(workerPids).size !== 2 ||
      JSON.stringify(sorted(processTree.worker_pids ?? [])) !== JSON.stringify(workerPids)) {
    throw new Error('The v3 receipt worker PID snapshot is inconsistent.');
  }

  const startup = parseJsonLine(
    v3,
    /^Container stdout\/stderr startup evidence: (\{.*\})\.$/m,
    'container startup PID evidence',
  );
  assertExactPidList(startup.uvicorn_server_started_pids ?? [], workerPids, 'Uvicorn server-start');
  assertExactPidList(startup.uvicorn_startup_complete_pids ?? [], workerPids, 'Uvicorn startup-complete');
  assertExactPidList(startup.expected_worker_pids ?? [], workerPids, 'recorded expected worker');

  const fileLog = v3.match(
    /^Application file-log summary: .*revision_verified_pids=(\[[^\r\n]*?\]); application_ready_pids=(\[[^\r\n]*?\]);/m,
  );
  if (!fileLog) throw new Error('The v3 receipt lacks allowlisted application file-log PID evidence.');
  assertExactPidList(JSON.parse(fileLog[1]), workerPids, 'migration revision file-log');
  assertExactPidList(JSON.parse(fileLog[2]), workerPids, 'application ready file-log');

  const health = parseJsonLine(
    v3,
    /^Independent internal-network peer health response: HTTP 200; (\{.*\})\.$/m,
    'independent HTTP health evidence',
  );
  if (health.status !== 'healthy' || health.database !== 'healthy') {
    throw new Error('The v3 receipt does not show healthy independent HTTP and database checks.');
  }
  if (!v3.includes('error=Gunicorn logs do not prove both workers and the master exited gracefully..')) {
    throw new Error('The v3 receipt does not contain the expected shutdown-marker-only failure.');
  }
  if (!/^- stop existing v2 app with 35-second grace period: .*rc=0;/m.test(v3) ||
      !/^- verify stopped app exit code and OOM status: .*rc=0;/m.test(v3)) {
    throw new Error('The v3 receipt does not prove the stop and container-state readback completed.');
  }
  const v3BaselineHash = v3.match(
    /^Pre-start normalized schema fingerprint from v2 receipt: ([a-f0-9]{64})\.$/m,
  )?.[1];
  if (v3BaselineHash !== baselineHash) throw new Error('The v2/v3 pre-start schema hashes do not match.');

  const evidence = {
    database,
    container_id: containerId,
    pre_start_schema_sha256: baselineHash,
    master_pid: masterPid,
    worker_pids: workerPids,
    v2_receipt_sha256: sha256(v2),
    v3_receipt_sha256: sha256(v3),
    v3_filtered_log_sha256: sha256(v3Log),
  };
  appendReceipt('Prior accepted evidence read-only verified: ' + JSON.stringify(evidence) + '.');
  appendReceipt('Shutdown source review used this exact production image digest: Gunicorn 26.0.0 Arbiter.stop sends SIGTERM and waits before its SIGKILL fallback; Uvicorn 0.47.0 logs Application shutdown complete after lifespan completion and Finished server process after Server.shutdown returns.');
  appendFiltered('[prior evidence hashes and PID allowlist] ' + JSON.stringify(evidence));
  return { database, containerId, baselineHash, masterPid, workerPids };
}

function verifyReadOnlyResources(baseline) {
  const network = runReadOnlyDocker('verify isolated internal network', [
    'network', 'inspect', '--format', '{{.Name}}|{{.Driver}}|{{.Internal}}', NETWORK,
  ]);
  requireSuccess(network, 'inspect isolated network');
  if (network.stdout.trim() !== NETWORK + '|bridge|true') {
    throw new Error('The existing network is not the expected internal bridge.');
  }

  const app = runReadOnlyDocker('read stopped app container identity and state', [
    'inspect', '--format',
    '{{.Id}}|{{.Image}}|{{.State.Status}}|{{.State.Pid}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|{{.HostConfig.Init}}|{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}|{{.Config.Image}}|{{json .Config.Cmd}}',
    APP_CONTAINER,
  ]);
  requireSuccess(app, 'inspect stopped app container');
  const fields = app.stdout.trim().split('|');
  if (fields.length !== 12) throw new Error('Stopped app inspection returned malformed fields.');
  const [id, imageId, status, initPid, exitCode, oomKilled, init, networkMode, ports, mounts, imageTag, command] = fields;
  if (id !== baseline.containerId || imageId !== PROD_IMAGE_ID || imageTag !== PROD_IMAGE) {
    throw new Error('Stopped container identity or production image digest differs from v2/v3 evidence.');
  }
  if (status !== 'exited' || exitCode !== '0' || oomKilled !== 'false') {
    throw new Error('Stopped container is not exited cleanly: status=' + status +
      '; exit=' + exitCode + '; oom=' + oomKilled + '.');
  }
  if (init !== 'true' || networkMode !== NETWORK || (ports !== 'null' && ports !== '{}') || mounts !== '[]') {
    throw new Error('Stopped container init, network, port, or mount configuration differs from v3 snapshot.');
  }
  if (!command.includes('exec gunicorn app.main:app')) throw new Error('Stopped app command no longer execs Gunicorn.');
  appendReceipt('Stopped app state read-only verified: id=' + id + '; image=' + imageTag + '/' + imageId +
    '; state=' + status + '; state_pid=' + initPid + '; exit=' + exitCode + '; oom=' + oomKilled +
    '; init=' + init + '; network=' + networkMode + '; ports=' + ports + '; mounts=' + mounts + '.');

  const pg = runReadOnlyDocker('verify existing PostgreSQL fixture is running', [
    'inspect', '--format', '{{.State.Status}}', PG_CONTAINER,
  ]);
  requireSuccess(pg, 'inspect PostgreSQL fixture');
  if (pg.stdout.trim() !== 'running') throw new Error('The existing PostgreSQL fixture is not running.');
  const pgNetwork = runReadOnlyDocker('verify PostgreSQL fixture remains on isolated network', [
    'inspect', '--format', '{{if index .NetworkSettings.Networks "' + NETWORK + '"}}attached{{else}}missing{{end}}', PG_CONTAINER,
  ]);
  requireSuccess(pgNetwork, 'inspect PostgreSQL network attachment');
  if (pgNetwork.stdout.trim() !== 'attached') {
    throw new Error('PostgreSQL fixture is not attached to the isolated network.');
  }

  const db = runReadOnlyDocker('read current PostgreSQL database identity', [
    'exec', '-i', PG_CONTAINER, 'sh', '-c',
    'exec psql -X -qAt --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "SELECT current_database()"',
  ]);
  requireSuccess(db, 'query PostgreSQL database identity');
  if (db.stdout.trim() !== baseline.database) {
    throw new Error('The live PostgreSQL database differs from the v2 baseline.');
  }
  appendReceipt('Existing PostgreSQL fixture identity verified read-only: database=' + baseline.database + '.');
}

function extractEvents(logText, pattern, nestedPid = false) {
  const events = [];
  const lines = logText.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(pattern);
    if (!match) continue;
    const pid = Number(match[1]);
    if (nestedPid && Number(match[2]) !== pid) continue;
    events.push({ pid, line: index + 1 });
  }
  return events;
}

function eventPids(events) {
  return events.map((event) => event.pid).sort((left, right) => left - right);
}

function verifyStoppedLogs(baseline) {
  const result = runReadOnlyDocker('read stopped container stdout and stderr', [
    'logs', '--timestamps', APP_CONTAINER,
  ], { timeoutMs: 30_000 });
  requireSuccess(result, 'read stopped container logs');
  const logs = combinedOutput(result);
  const masterSignal = extractEvents(logs, /^\S.*?\[(\d+)\] \[INFO\] Handling signal: term\s*$/i);
  const masterShutdown = extractEvents(logs, /^\S.*?\[(\d+)\] \[INFO\] Shutting down: Master\s*$/i);
  const appShutdown = extractEvents(logs, /^\S.*?\[(\d+)\] \[INFO\] Application shutdown complete\.\s*$/i);
  const serverFinished = extractEvents(
    logs,
    /^\S.*?\[(\d+)\] \[INFO\] Finished server process \[(\d+)\]\s*$/i,
    true,
  );
  const workerExitPids = extractEvents(logs, /Worker exiting \(pid:\s*(\d+)\)/i).map((event) => event.pid);
  const forcedMarker =
    /SIGKILL|did not exit in time|force.?kill|WORKER TIMEOUT|timeout graceful shutdown exceeded|Application shutdown failed|Worker\s*\(pid:\s*\d+\) exited with code [1-9]\d*/i.test(logs);

  assertExactPidList(eventPids(masterSignal), [baseline.masterPid], 'Gunicorn master TERM handling');
  assertExactPidList(eventPids(masterShutdown), [baseline.masterPid], 'Gunicorn master shutdown');
  assertExactPidList(eventPids(appShutdown), baseline.workerPids, 'Uvicorn application shutdown-complete');
  assertExactPidList(eventPids(serverFinished), baseline.workerPids, 'Uvicorn finished-server');
  if (forcedMarker) throw new Error('Stopped container logs contain timeout, failed shutdown, or forced-kill markers.');
  const shutdownLineByPid = new Map(appShutdown.map((event) => [event.pid, event.line]));
  const finishedLineByPid = new Map(serverFinished.map((event) => [event.pid, event.line]));
  if (masterSignal[0].line >= Math.min(...appShutdown.map((event) => event.line)) ||
      baseline.workerPids.some((pid) => shutdownLineByPid.get(pid) >= finishedLineByPid.get(pid)) ||
      Math.max(...serverFinished.map((event) => event.line)) >= masterShutdown[0].line) {
    throw new Error('Read-only shutdown event order does not show signal, both app shutdowns, server finishes, then master exit.');
  }

  const evidence = {
    master_pid: baseline.masterPid,
    master_term_handled_pids: eventPids(masterSignal),
    application_shutdown_complete_pids: eventPids(appShutdown),
    finished_server_pids: eventPids(serverFinished),
    master_shutdown_pids: eventPids(masterShutdown),
    event_line_order: {
      master_term: masterSignal[0].line,
      application_shutdown_complete: appShutdown.map((event) => ({ pid: event.pid, line: event.line })),
      finished_server: serverFinished.map((event) => ({ pid: event.pid, line: event.line })),
      master_shutdown: masterShutdown[0].line,
    },
    worker_exiting_log_pids: workerExitPids,
    worker_exiting_marker_required: false,
    forced_or_failed_shutdown_marker: forcedMarker,
  };
  appendReceipt('Stopped-container allowlisted shutdown evidence: ' + JSON.stringify(evidence) + '.');
  appendFiltered('[allowlisted stopped-container shutdown markers] ' + JSON.stringify(evidence));
}

function captureSchemaFingerprint(baselineHash) {
  const dump = runReadOnlyDocker('capture current schema-only fingerprint', [
    'exec', PG_CONTAINER, 'sh', '-c',
    'exec pg_dump --schema-only --no-owner --no-privileges --username "$POSTGRES_USER" "$POSTGRES_DB"',
  ], { timeoutMs: 60_000 });
  requireSuccess(dump, 'capture schema-only fingerprint');
  const rawHash = sha256(dump.stdout);
  const normalized = dump.stdout.replace(/^\\(?:restrict|unrestrict)\s+\S+\s*\r?\n/gm, '');
  const normalizedHash = sha256(normalized);
  appendReceipt('Schema-only readback: raw_sha256=' + rawHash +
    '; normalized_sha256=' + normalizedHash + '; bytes=' + Buffer.byteLength(dump.stdout) +
    '; normalization=remove only PostgreSQL \\restrict and \\unrestrict metadata command lines; no table data retained.');
  if (normalizedHash !== baselineHash) {
    throw new Error('Current normalized schema fingerprint differs from the v2 pre-start baseline.');
  }
  appendReceipt('Schema fingerprint matches v2 pre-start baseline: ' + normalizedHash + '.');
}

function runReadback() {
  const baseline = readPriorEvidence();
  verifyReadOnlyResources(baseline);
  verifyStoppedLogs(baseline);
  captureSchemaFingerprint(baseline.baselineHash);
  appendReceipt('Interpretation: Uvicorn lifecycle shutdown/finished events are matched to both snapshotted worker PIDs; Gunicorn master shutdown and clean container exit complete the readback. The missing optional Worker exiting log line is not a required gate.');
  appendReceipt('Final result: PASS at ' + utcNow() + ' UTC; elapsed_ms=' + (Date.now() - startedAt) +
    '; readback only; stopped v3 app and historical v3 evidence preserved.');
  process.stdout.write('PASS: receipt=' + RECEIPT + '; filtered_log=' + FILTERED_LOG + '; no resources changed\n');
}

function main() {
  initializeOutputs();
  try {
    runReadback();
  } catch (error) {
    appendReceipt('Final result: FAIL at ' + utcNow() + ' UTC; elapsed_ms=' + (Date.now() - startedAt) +
      '; error=' + (error?.message ?? String(error)) + '.');
    appendReceipt('No container, network, image, role, database, volume, environment file, or v2/v3 evidence was changed or removed.');
    process.stderr.write('FAIL: ' + (error?.message ?? String(error)) +
      '; receipt=' + RECEIPT + '; filtered_log=' + FILTERED_LOG + '\n');
    process.exitCode = 1;
  }
}

main();

