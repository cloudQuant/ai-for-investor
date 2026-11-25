import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OPS_DIR = PROJECT_ROOT / "scripts" / "ops"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_restart_fails_when_backend_exits_after_initial_pid_check(tmp_path: Path) -> None:
    """A delayed FastAPI startup failure must make the restart command fail."""
    ops_dir = tmp_path / "scripts" / "ops"
    ops_dir.mkdir(parents=True)
    for script_name in ("restart_app.sh", "start_app.sh"):
        shutil.copy2(OPS_DIR / script_name, ops_dir / script_name)

    _write_executable(ops_dir / "stop_app.sh", "#!/bin/bash\nexit 0\n")
    (tmp_path / "src" / "backend").mkdir(parents=True)
    (tmp_path / "src" / "frontend").mkdir(parents=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    _write_executable(
        fake_python,
        """#!/bin/bash
if [ "${1:-}" = "--version" ]; then
    echo "Python 3.11.0"
    exit 0
fi
if [ "${1:-}" = "-c" ]; then
    exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "uvicorn" ]; then
    sleep 4
    echo "database connection refused" >&2
    exit 1
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "setsid",
        '#!/bin/bash\nexec "$@"\n',
    )
    _write_executable(
        fake_bin / "node",
        "#!/bin/bash\necho 'v20.0.0'\n",
    )
    _write_executable(fake_bin / "npm", "#!/bin/bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "PYTHON_BIN": str(fake_python),
            "BACKEND_PORT": str(_available_local_port()),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )
    result = subprocess.run(
        ["bash", str(ops_dir / "restart_app.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert "后端服务" in result.stdout


@pytest.mark.parametrize("host", [None, "0.0.0.0"])
def test_start_app_preserves_dotenv_app_env_and_cleans_up_orphans(
    tmp_path: Path, host: str | None
) -> None:
    """Unspecified APP_ENV/DEBUG must not inject APP_ENV=development over .env."""
    ops_dir = tmp_path / "scripts" / "ops"
    ops_dir.mkdir(parents=True)
    shutil.copy2(OPS_DIR / "start_app.sh", ops_dir / "start_app.sh")
    (tmp_path / "src" / "backend").mkdir(parents=True)
    (tmp_path / "src" / "backend" / ".env").write_text(
        "APP_ENV=production\nDEBUG=false\n",
        encoding="utf-8",
    )

    env_capture = tmp_path / "uvicorn_env.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    _write_executable(
        fake_python,
        f"""#!/bin/bash
if [ "${{1:-}}" = "--version" ]; then
    echo "Python 3.11.0"
    exit 0
fi
if [ "${{1:-}}" = "-c" ]; then
    exit 0
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "uvicorn" ]; then
    printf 'APP_ENV=%s\nDEBUG=%s\nHOST=%s\nARGS=%s\n' "${{APP_ENV-<unset>}}" "${{DEBUG-<unset>}}" "${{HOST-<unset>}}" "$*" > "{env_capture}"
    sleep 15
    exit 0
fi
exit 0
""",
    )
    _write_executable(fake_bin / "setsid", '#!/bin/bash\nexec "$@"\n')
    _write_executable(fake_bin / "node", "#!/bin/bash\necho 'v20.0.0'\n")
    _write_executable(fake_bin / "npm", "#!/bin/bash\nexit 0\n")
    _write_executable(
        fake_bin / "curl",
        '#!/bin/bash\necho \'{"status":"ok","database":"connected"}\'\n',
    )

    clean_env = {k: v for k, v in os.environ.items() if k not in {"APP_ENV", "DEBUG", "HOST"}}
    if host is not None:
        clean_env["HOST"] = host
    clean_env.update(
        {
            "PYTHON_BIN": str(fake_python),
            "BACKEND_PORT": str(_available_local_port()),
            "BACKEND_STARTUP_TIMEOUT_SECONDS": "5",
            "PATH": f"{fake_bin}{os.pathsep}{clean_env['PATH']}",
        }
    )

    proc = subprocess.run(
        ["bash", str(ops_dir / "start_app.sh")],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    # Clean up the simulated background python process spawned by start_app.sh
    pid_file = tmp_path / ".pids" / "backend.pid"
    if pid_file.is_file():
        try:
            os.kill(int(pid_file.read_text().strip()), 9)
        except OSError:
            pass

    assert proc.returncode == 0, proc.stdout + proc.stderr
    captured = env_capture.read_text(encoding="utf-8")
    assert "APP_ENV=<unset>" in captured
    assert "DEBUG=<unset>" in captured
    expected_host = host or "127.0.0.1"
    assert f"HOST={expected_host}\n" in captured
    assert f"--host {expected_host} --port " in captured
    assert "前端目录不存在" in proc.stdout


def test_stop_app_survives_stale_pid_files(tmp_path: Path) -> None:
    """stop_app.sh handles missing PIDs cleanly and removes stale pid files."""
    ops_dir = tmp_path / "scripts" / "ops"
    ops_dir.mkdir(parents=True)
    shutil.copy2(OPS_DIR / "stop_app.sh", ops_dir / "stop_app.sh")
    pid_dir = tmp_path / ".pids"
    pid_dir.mkdir()
    (pid_dir / "backend.pid").write_text("99999999\n", encoding="utf-8")
    (pid_dir / "frontend.pid").write_text("99999998\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(ops_dir / "stop_app.sh")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (pid_dir / "backend.pid").exists()
    assert not (pid_dir / "frontend.pid").exists()


def test_validate_docker_env_strips_quotes_and_supports_skip_mysql(tmp_path: Path) -> None:
    """Quoted values parse properly, weak DB passwords fail, and --skip-mysql-check works."""
    import sys

    env_file = tmp_path / ".env"
    env_file.write_text(
        'SECRET_KEY="' + "s" * 40 + '"\n'
        'JWT_SECRET_KEY="' + "j" * 40 + '"\n'
        "ADMIN_PASSWORD=StrongAdminPass!2026\n"
        "DB_PASSWORD=StrongDbPass!2026\n"
        "DATABASE_URL=mysql+aiomysql://u:p@mysql:3306/db\n",
        encoding="utf-8",
    )
    validator = OPS_DIR / "validate_docker_env.py"
    ok = subprocess.run(
        [sys.executable, str(validator), "--env-file", str(env_file), "--skip-mysql-check"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr

    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace("StrongDbPass!2026", "admin123"),
        encoding="utf-8",
    )
    weak = subprocess.run(
        [sys.executable, str(validator), "--env-file", str(env_file), "--skip-mysql-check"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert weak.returncode == 1
    assert "DB_PASSWORD" in weak.stdout


def test_check_complexity_budget_refuses_update_without_guard() -> None:
    """check_complexity_budget.py --update fails closed without ALLOW_BASELINE_UPDATE=1."""
    import sys

    env = {k: v for k, v in os.environ.items() if k != "ALLOW_BASELINE_UPDATE"}
    script = PROJECT_ROOT / "scripts" / "ci" / "check_complexity_budget.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--update"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 2
    assert "ALLOW_BASELINE_UPDATE=1" in proc.stderr
