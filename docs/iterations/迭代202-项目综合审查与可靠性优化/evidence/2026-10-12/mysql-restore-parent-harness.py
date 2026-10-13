"""Run a disposable, real-MySQL backup/restore acceptance check.

This driver is intentionally not self-executing during preparation. It invokes
the repository's Docker scripts only when a reviewer runs it explicitly.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_NAME = "iter202-restore-parent"
DATABASE_NAME = "iter202_restore_parent"
BACKUP_SCRIPT_RELATIVE = Path("scripts/ops/docker_mysql_backup.sh")
RESTORE_SCRIPT_RELATIVE = Path("scripts/ops/docker_mysql_restore.sh")
MYSQL_READY_SCRIPT = (
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; '
    "until mysql --protocol=TCP --host=127.0.0.1 --user=root "
    '--database="$MYSQL_DATABASE" --batch --skip-column-names '
    "-e 'SELECT 1' >/dev/null 2>&1; do sleep 2; done"
)
MYSQL_CLIENT_SCRIPT = (
    'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; '
    'exec mysql --user=root --database="$MYSQL_DATABASE" '
    "--batch --raw --skip-column-names"
)


class HarnessError(RuntimeError):
    """Raised when an acceptance precondition or assertion fails."""


@dataclass
class CommandRecord:
    name: str
    argv: list[str]
    started_at_utc: str
    finished_at_utc: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def find_repository_root() -> Path:
    starts = [Path.cwd(), *Path.cwd().parents]
    known_root = Path("/Users/yunjinqi/Documents/new_projects/ai-for-investor")
    if known_root not in starts:
        starts.append(known_root)
    for candidate in starts:
        if (candidate / BACKUP_SCRIPT_RELATIVE).is_file() and (
            candidate / RESTORE_SCRIPT_RELATIVE
        ).is_file():
            return candidate.resolve()
    raise HarnessError("Could not locate the repository backup and restore scripts.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_private_file(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    os.chmod(path, 0o600)


def output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class Harness:
    def __init__(self, log_path: Path, secret: str) -> None:
        self.log_path = log_path
        self.secret = secret
        self.commands: list[CommandRecord] = []
        self.checks: list[dict[str, object]] = []
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)

    def redact(self, value: str) -> str:
        return value.replace(self.secret, "[REDACTED]")

    def _save_command(self, record: CommandRecord) -> None:
        self.commands.append(record)
        safe_record = asdict(record)
        line = json.dumps(safe_record, ensure_ascii=False, sort_keys=True)
        if self.secret in line:
            raise HarnessError(
                "A command record unexpectedly contains the generated secret."
            )
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
        os.chmod(self.log_path, 0o600)

    def run(
        self,
        name: str,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        input_text: str | None = None,
        timeout_seconds: int = 180,
    ) -> CommandRecord:
        started_at = utc_now()
        safe_argv = [self.redact(str(argument)) for argument in argv]
        try:
            completed = subprocess.run(
                list(argv),
                cwd=REPOSITORY_ROOT,
                env=env,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            record = CommandRecord(
                name=name,
                argv=safe_argv,
                started_at_utc=started_at,
                finished_at_utc=utc_now(),
                exit_code=None,
                stdout=self.redact(output_text(exc.stdout))[-4000:],
                stderr=self.redact(output_text(exc.stderr))[-4000:],
                timed_out=True,
            )
            self._save_command(record)
            return record
        except OSError as exc:
            record = CommandRecord(
                name=name,
                argv=safe_argv,
                started_at_utc=started_at,
                finished_at_utc=utc_now(),
                exit_code=None,
                stdout="",
                stderr=self.redact(f"{type(exc).__name__}: {exc}"),
            )
            self._save_command(record)
            return record

        record = CommandRecord(
            name=name,
            argv=safe_argv,
            started_at_utc=started_at,
            finished_at_utc=utc_now(),
            exit_code=completed.returncode,
            stdout=self.redact(completed.stdout)[-4000:],
            stderr=self.redact(completed.stderr)[-4000:],
        )
        self._save_command(record)
        return record

    def expect_exit(self, record: CommandRecord, expected: int) -> None:
        if record.exit_code != expected:
            details = record.stderr.strip() or record.stdout.strip()
            raise HarnessError(
                f"{record.name} exited {record.exit_code}; expected {expected}. {details[-800:]}"
            )
        self.checks.append(
            {
                "name": f"{record.name} exit code",
                "result": "PASS",
                "observed": record.exit_code,
            }
        )


def private_environment(
    temporary_env_file: Path,
    compose_file: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    for key in ("DB_NAME", "MYSQL_ROOT_PASSWORD", "RESTORE_ALLOW_DESTRUCTIVE"):
        environment.pop(key, None)
    environment.update(
        {
            "ENV_FILE_RELATIVE_PATH": str(temporary_env_file.resolve()),
            "COMPOSE_BASE_FILE": str(compose_file.resolve()),
            # The backup and restore scripts default this variable to prod.yml
            # with :-, so use the private fixture file rather than an empty value.
            "COMPOSE_FILE": str(compose_file.resolve()),
            "COMPOSE_PROJECT_NAME": PROJECT_NAME,
        }
    )
    return environment


def compose_prefix(env_file: Path, compose_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(REPOSITORY_ROOT),
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        str(env_file.resolve()),
        "-f",
        str(compose_file.resolve()),
        "-f",
        str(compose_file.resolve()),
    ]


def read_project_resources(
    harness: Harness, kind: str, env: dict[str, str]
) -> list[str]:
    if kind == "containers":
        argv = [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT_NAME}",
        ]
    elif kind == "volumes":
        argv = [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT_NAME}",
        ]
    elif kind == "networks":
        argv = [
            "docker",
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT_NAME}",
        ]
    else:
        raise HarnessError(f"Unsupported Docker resource kind: {kind}")
    record = harness.run(f"list project {kind}", argv, env=env, timeout_seconds=30)
    harness.expect_exit(record, 0)
    return [line.strip() for line in record.stdout.splitlines() if line.strip()]


def scan_gzip_for_database(backup_path: Path, database_name: str) -> None:
    marker = f"-- Current Database: `{database_name}`".encode()
    overlap = b""
    found = False
    with gzip.open(backup_path, "rb") as stream:
        while block := stream.read(1024 * 1024):
            window = overlap + block
            if marker in window:
                found = True
            overlap = window[-len(marker) :]
    if not found:
        raise HarnessError(
            "The gzip dump does not contain the configured database marker."
        )


def verify_backup_artifact(
    harness: Harness,
    backup_path: Path,
    env: dict[str, str],
) -> dict[str, object]:
    checksum_path = Path(f"{backup_path}.sha256")
    for artifact in (backup_path, checksum_path):
        if not artifact.is_file():
            raise HarnessError(f"Backup artifact is missing: {artifact.name}")
        mode = stat.S_IMODE(artifact.stat().st_mode)
        if mode != 0o600:
            raise HarnessError(f"{artifact.name} mode is {mode:04o}; expected 0600.")

    gzip_check = harness.run(
        "gzip integrity check",
        ["gzip", "-t", str(backup_path)],
        env=env,
        timeout_seconds=60,
    )
    harness.expect_exit(gzip_check, 0)
    scan_gzip_for_database(backup_path, DATABASE_NAME)

    actual_hash = sha256_file(backup_path)
    checksum_fields = (
        checksum_path.read_text(encoding="utf-8").strip().split(maxsplit=1)
    )
    if len(checksum_fields) != 2:
        raise HarnessError("The backup SHA-256 sidecar has an invalid format.")
    sidecar_hash, sidecar_name = checksum_fields
    if sidecar_name.lstrip("*") != backup_path.name:
        raise HarnessError("The backup SHA-256 sidecar names a different file.")
    if not re.fullmatch(r"[0-9a-f]{64}", sidecar_hash) or sidecar_hash != actual_hash:
        raise HarnessError("The backup SHA-256 sidecar does not match the archive.")

    harness.checks.append(
        {
            "name": "backup gzip, database marker, SHA-256, and file modes",
            "result": "PASS",
        }
    )
    return {
        "sha256": actual_hash,
        "size_bytes": backup_path.stat().st_size,
        "archive_mode": "0600",
        "checksum_mode": "0600",
        "database_marker_valid": True,
    }


REPOSITORY_ROOT = Path("/Users/yunjinqi/Documents/new_projects/ai-for-investor")


def main() -> int:
    global REPOSITORY_ROOT

    try:
        REPOSITORY_ROOT = find_repository_root()
    except HarnessError as exc:
        print(f"HARNESS BLOCKED: {exc}")
        return 2

    backup_script = REPOSITORY_ROOT / BACKUP_SCRIPT_RELATIVE
    restore_script = REPOSITORY_ROOT / RESTORE_SCRIPT_RELATIVE
    source_hashes_at_start = {
        "docker_mysql_backup.sh": sha256_file(backup_script),
        "docker_mysql_restore.sh": sha256_file(restore_script),
    }
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}-{secrets.token_hex(3)}"
    output_directory = Path(__file__).resolve().parent
    receipt_path = output_directory / f"mysql-restore-parent-receipt-{run_id}.json"
    log_path = output_directory / f"mysql-restore-parent-log-{run_id}.jsonl"

    secret = secrets.token_urlsafe(48)
    harness = Harness(log_path, secret)
    temporary_directory: Path | None = None
    project_owned = False
    compose: list[str] = []
    environment: dict[str, str] = {}
    readback_values: dict[str, str | None] = {
        "after_guarded_restore": None,
        "after_authorized_restore": None,
    }
    destructive_scope: dict[str, object] = {
        "authorized": False,
        "self_owned_ephemeral_database_only": True,
        "database_name": DATABASE_NAME,
    }
    receipt: dict[str, object] = {
        "schema": "mysql-restore-parent-harness/v1",
        "status": "FAIL",
        "project_name": PROJECT_NAME,
        "database_name": DATABASE_NAME,
        "started_at_utc": utc_now(),
        "receipt_path": str(receipt_path),
        "log_path": str(log_path),
        "source_sha256_at_start": source_hashes_at_start,
        "image_id": None,
        "mysql_version": None,
        "backup_artifact": None,
        "readback_values": readback_values,
        "destructive_restore_scope": destructive_scope,
        "commands": [],
        "checks": harness.checks,
        "errors": [],
    }
    errors: list[str] = []

    try:
        temporary_directory = Path(
            tempfile.mkdtemp(prefix="iter202-restore-parent-", dir="/tmp")
        )
        os.chmod(temporary_directory, 0o700)
        env_file = temporary_directory / "mysql.env"
        compose_file = temporary_directory / "compose.yml"
        backup_path = temporary_directory / "acceptance.sql.gz"
        write_private_file(
            env_file,
            f"DB_NAME={DATABASE_NAME}\nMYSQL_ROOT_PASSWORD={secret}\n",
        )
        compose_text = """\
name: iter202-restore-parent
services:
  mysql:
    image: mysql:8.0
    restart: "no"
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}
      MYSQL_DATABASE: ${DB_NAME:?DB_NAME is required}
    volumes:
      - mysql_data:/var/lib/mysql
volumes:
  mysql_data:
"""
        write_private_file(compose_file, compose_text)
        environment = private_environment(env_file, compose_file)
        compose = compose_prefix(env_file, compose_file)

        for resource_kind in ("containers", "volumes", "networks"):
            existing = read_project_resources(harness, resource_kind, environment)
            if existing:
                raise HarnessError(
                    f"The required fresh Compose project already has {resource_kind}; "
                    "refusing to reuse or delete pre-existing resources."
                )
        harness.checks.append(
            {"name": "fresh isolated Compose project", "result": "PASS"}
        )

        # Mark ownership before `up`: a failed start can still leave our container or volume.
        project_owned = True
        up = harness.run(
            "start disposable MySQL 8 service",
            compose + ["up", "--detach", "mysql"],
            env=environment,
            timeout_seconds=240,
        )
        harness.expect_exit(up, 0)

        ready = harness.run(
            "wait for MySQL readiness",
            compose + ["exec", "--no-TTY", "mysql", "sh", "-ec", MYSQL_READY_SCRIPT],
            env=environment,
            timeout_seconds=240,
        )
        harness.expect_exit(ready, 0)

        container_query = harness.run(
            "read MySQL container ID",
            compose + ["ps", "--quiet", "mysql"],
            env=environment,
            timeout_seconds=30,
        )
        harness.expect_exit(container_query, 0)
        container_ids = [
            line.strip() for line in container_query.stdout.splitlines() if line.strip()
        ]
        if len(container_ids) != 1:
            raise HarnessError(
                "Expected exactly one MySQL container in the disposable project."
            )
        image_query = harness.run(
            "read MySQL image ID",
            ["docker", "inspect", "--format", "{{.Image}}", container_ids[0]],
            env=environment,
            timeout_seconds=30,
        )
        harness.expect_exit(image_query, 0)
        image_id = image_query.stdout.strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise HarnessError("Docker did not return a valid MySQL image ID.")
        receipt["image_id"] = image_id

        project_volumes = read_project_resources(harness, "volumes", environment)
        if len(project_volumes) != 1:
            raise HarnessError(
                "Expected exactly one temporary Compose-managed MySQL volume."
            )
        receipt["temporary_volume"] = project_volumes[0]

        def mysql_query(sql: str, name: str) -> str:
            result = harness.run(
                name,
                compose
                + ["exec", "--no-TTY", "mysql", "sh", "-ec", MYSQL_CLIENT_SCRIPT],
                env=environment,
                input_text=sql.rstrip() + "\n",
                timeout_seconds=60,
            )
            harness.expect_exit(result, 0)
            return result.stdout.strip()

        mysql_version = mysql_query("SELECT VERSION();", "verify MySQL server version")
        if not mysql_version.startswith("8.0."):
            raise HarnessError(
                f"Expected MySQL 8.0; received version {mysql_version!r}."
            )
        receipt["mysql_version"] = mysql_version
        harness.checks.append({"name": "MySQL 8.0 server", "result": "PASS"})

        mysql_query(
            "CREATE TABLE acceptance_receipt ("
            "id INT NOT NULL PRIMARY KEY, receipt_value VARCHAR(16) NOT NULL"
            ") ENGINE=InnoDB;\n"
            "INSERT INTO acceptance_receipt (id, receipt_value) VALUES (1, 'before');",
            "create before database row",
        )
        initial_value = mysql_query(
            "SELECT receipt_value FROM acceptance_receipt WHERE id = 1;",
            "read before database row",
        )
        if initial_value != "before":
            raise HarnessError(
                f"Expected the initial database row to be 'before', got {initial_value!r}."
            )

        backup = harness.run(
            "create MySQL backup",
            ["bash", str(backup_script), str(backup_path)],
            env=environment,
            timeout_seconds=240,
        )
        harness.expect_exit(backup, 0)
        receipt["backup_artifact"] = verify_backup_artifact(
            harness, backup_path, environment
        )

        duplicate_backup = harness.run(
            "reject duplicate backup path",
            ["bash", str(backup_script), str(backup_path)],
            env=environment,
            timeout_seconds=60,
        )
        harness.expect_exit(duplicate_backup, 2)

        changed_value = mysql_query(
            "UPDATE acceptance_receipt SET receipt_value = 'after' WHERE id = 1;\n"
            "SELECT receipt_value FROM acceptance_receipt WHERE id = 1;",
            "change row after backup",
        )
        if changed_value != "after":
            raise HarnessError(
                f"Expected the changed database row to be 'after', got {changed_value!r}."
            )

        guarded_environment = environment.copy()
        guarded_environment.pop("RESTORE_ALLOW_DESTRUCTIVE", None)
        guarded_restore = harness.run(
            "refuse restore without destructive authorization",
            ["bash", str(restore_script), str(backup_path)],
            env=guarded_environment,
            timeout_seconds=60,
        )
        harness.expect_exit(guarded_restore, 2)
        after_guard = mysql_query(
            "SELECT receipt_value FROM acceptance_receipt WHERE id = 1;",
            "verify guarded restore preserved after row",
        )
        readback_values["after_guarded_restore"] = after_guard
        if after_guard != "after":
            raise HarnessError(
                "A restore without authorization changed the database row."
            )

        # The only destructive target is the database created above in this fresh project.
        if DATABASE_NAME != "iter202_restore_parent" or not project_owned:
            raise HarnessError(
                "The destructive restore target is not the harness-owned test database."
            )
        authorized_environment = environment.copy()
        authorized_environment["RESTORE_ALLOW_DESTRUCTIVE"] = "YES"
        destructive_scope["authorized"] = True
        authorized_restore = harness.run(
            "restore harness-owned disposable database",
            ["bash", str(restore_script), str(backup_path)],
            env=authorized_environment,
            timeout_seconds=240,
        )
        harness.expect_exit(authorized_restore, 0)
        restored_value = mysql_query(
            "SELECT receipt_value FROM acceptance_receipt WHERE id = 1;",
            "verify restored before row",
        )
        readback_values["after_authorized_restore"] = restored_value
        if restored_value != "before":
            raise HarnessError(
                f"Expected restored database row 'before', got {restored_value!r}."
            )
        harness.checks.append(
            {"name": "authorized restore recovered pre-backup row", "result": "PASS"}
        )

    except KeyboardInterrupt:
        errors.append("Harness interrupted by operator.")
    except (HarnessError, OSError, subprocess.SubprocessError, ValueError) as exc:
        errors.append(harness.redact(f"{type(exc).__name__}: {exc}"))
    finally:
        if project_owned and compose and environment:
            cleanup = harness.run(
                "remove only the disposable Compose project and its volumes",
                compose + ["down", "--volumes", "--remove-orphans"],
                env=environment,
                timeout_seconds=180,
            )
            if cleanup.exit_code != 0:
                errors.append(f"Compose cleanup failed with exit {cleanup.exit_code}.")
            for resource_kind in ("containers", "volumes", "networks"):
                try:
                    remaining = read_project_resources(
                        harness, resource_kind, environment
                    )
                except (HarnessError, OSError, subprocess.SubprocessError) as exc:
                    errors.append(
                        harness.redact(
                            f"Could not verify project {resource_kind} cleanup: {type(exc).__name__}: {exc}"
                        )
                    )
                    continue
                if remaining:
                    errors.append(
                        f"Disposable project still has {resource_kind} after cleanup: {remaining}."
                    )

        if temporary_directory is not None and temporary_directory.exists():
            try:
                resolved_tmp = temporary_directory.resolve()
                if resolved_tmp.parent != Path(
                    "/tmp"
                ).resolve() or not resolved_tmp.name.startswith(
                    "iter202-restore-parent-"
                ):
                    raise HarnessError(
                        "Refusing to remove a temporary path outside the harness scope."
                    )
                shutil.rmtree(resolved_tmp)
            except (HarnessError, OSError) as exc:
                errors.append(
                    harness.redact(f"Temporary fixture cleanup failed: {exc}")
                )

        try:
            source_hashes_at_finish = {
                "docker_mysql_backup.sh": sha256_file(backup_script),
                "docker_mysql_restore.sh": sha256_file(restore_script),
            }
            if source_hashes_at_finish != source_hashes_at_start:
                errors.append(
                    "Backup or restore source changed while the harness was running."
                )
            receipt["source_sha256"] = source_hashes_at_finish
        except (OSError, HarnessError) as exc:
            errors.append(harness.redact(f"Could not read final source hashes: {exc}"))

        receipt["status"] = "PASS" if not errors else "FAIL"
        receipt["finished_at_utc"] = utc_now()
        receipt["commands"] = [asdict(command) for command in harness.commands]
        receipt["checks"] = harness.checks
        receipt["errors"] = errors
        receipt_text = (
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if secret in receipt_text:
            receipt["status"] = "FAIL"
            receipt["errors"] = [
                *errors,
                "Generated secret was redacted from the receipt.",
            ]
            receipt_text = (
                json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
            receipt_text = receipt_text.replace(secret, "[REDACTED]")
        try:
            receipt_tmp_path = receipt_path.with_suffix(".json.tmp")
            write_private_file(receipt_tmp_path, receipt_text)
            os.replace(receipt_tmp_path, receipt_path)
            os.chmod(receipt_path, 0o600)
        except (OSError, TypeError, ValueError) as exc:
            errors.append(harness.redact(f"Could not write receipt: {exc}"))
            print(f"HARNESS FAIL: {errors[-1]}")
            return 1

    print(f"Harness result: {receipt['status']}")
    print(f"Sanitized receipt: {receipt_path}")
    print(f"Sanitized command log: {log_path}")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
