"""Build a faithful mirror of CI's mypy environment and re-measure the collection plane in it.

Why this exists: CI runs Python 3.11 and installs `config/requirements-dev.lock`
(pandas 3.0.3, no pandas-stubs, types-pymysql + types-pytz, akshare 1.18.97). The venv used all wave
was Python 3.13 with pandas 2.3.3 + pandas-stubs and no types-pymysql. Same command, same mypy
version, same 1108 files -- but CI read 101 errors on dev `0a4c5ab31` where that venv read 159.
Every plane number in this wave therefore has to be re-labelled by environment, and the bookable one
is the CI-environment reading. This script produces it.
"""

import os
import subprocess
import sys

REPO = "/home/yun/Documents/ai-for-investor"
VENV = "/tmp/it204/venv-ci"
LOG = "/tmp/it204/venv-ci-setup.log"


def run(cmd, cwd=REPO, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                       env=e, timeout=3000)
    with open(LOG, "a") as fh:
        fh.write(f"$ {cmd if isinstance(cmd,str) else ' '.join(cmd)}\n")
        fh.write((r.stdout[-2000:] if r.returncode == 0 else r.stderr[-2000:]) + "\n")
    return r


def main():
    py311 = sys.executable if sys.version_info[:2] == (3, 11) else "/home/yun/.local/bin/python3.11"
    if not os.path.exists(py311):
        py311 = "/home/yun/anaconda3/envs/py311/bin/python"
    print("using interpreter:", py311, run("--version", ) if False else "")
    r = run([py311, "--version"])
    print("interpreter:", r.stdout.strip() or r.stderr.strip())

    if not os.path.isdir(VENV):
        r = run([py311, "-m", "venv", VENV])
        print("venv create rc:", r.returncode, (r.stderr[-300:] if r.returncode else ""))
    pip = os.path.join(VENV, "bin", "python")
    r = run([pip, "-m", "pip", "install", "--upgrade", "pip"])
    print("pip upgrade rc:", r.returncode)
    r = run([pip, "-m", "pip", "install", "--requirement", "config/requirements-dev.lock"])
    print("lock install rc:", r.returncode, (r.stderr[-500:] if r.returncode else ""))
    if r.returncode:
        return 1
    r = run([pip, "-m", "pip", "install", "--no-deps", "-e", "."], cwd=os.path.join(REPO, "src", "backend"))
    print("editable install rc:", r.returncode, (r.stderr[-400:] if r.returncode else ""))
    for name in ("mypy", "pandas", "numpy", "akshare", "types-pytz", "types-pymysql", "pandas-stubs"):
        out = run([pip, "-m", "pip", "show", name]).stdout.splitlines()
        ver = next((l.split(":")[1].strip() for l in out if l.startswith("Version:")), "ABSENT")
        print(f"  {name}={ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
