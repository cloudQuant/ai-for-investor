#!/usr/bin/env python3
"""Execute the real "Install gitleaks" step body against a flaky local release host.

Both step bodies are read verbatim from a workflow file (the pre-fix one is taken
from origin/dev), then only the download URL, the scratch paths, and the two
lines that assume `/usr/local/bin` is on PATH are rewritten. The runner's shell
(bash -eo pipefail) is used, so the exit codes are the step's own.
"""

from __future__ import annotations

import argparse
import http.server
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile
import threading
import time

import yaml

REAL_URL = (
    "https://github.com/gitleaks/gitleaks/releases/download/"
    "v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
)


def build_archive(path: pathlib.Path, version: str) -> None:
    staging = path.parent / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    binary = staging / "gitleaks"
    binary.write_text(
        f'#!/bin/sh\necho "gitleaks version {version}"\n', encoding="utf-8"
    )
    binary.chmod(0o755)
    with tarfile.open(path, "w:gz") as handle:
        handle.add(binary, arcname="gitleaks")


class FlakyHandler(http.server.BaseHTTPRequestHandler):
    attempts: dict[str, int] = {}
    archive: pathlib.Path
    mode: str

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.attempts[self.path] = self.attempts.get(self.path, 0) + 1
        count = self.attempts[self.path]
        if self.mode == "always500":
            self.send_error(500, "release host down")
            return
        body = self.archive.read_bytes()
        if self.mode == "flaky" and count == 1:
            # Lie about Content-Length, write half the body, hang up: a truncated stream.
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) * 3))
            self.end_headers()
            self.wfile.write(body[: len(body) // 2])
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def step_body(workflow_path: pathlib.Path) -> str:
    doc = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == "Install gitleaks":
                return str(step["run"])
    raise AssertionError(f"Install gitleaks step not found in {workflow_path}")


def localize(body: str, url: str, work: pathlib.Path) -> str:
    text = body.replace(REAL_URL, url)
    text = text.replace("/tmp/gitleaks.tar.gz", f"{work}/gitleaks.tar.gz")
    text = text.replace("| tar -xz -C /tmp gitleaks", f"| tar -xz -C {work} gitleaks")
    text = text.replace("-C /tmp gitleaks", f"-C {work} gitleaks")
    text = text.replace(
        "sudo mv /tmp/gitleaks /usr/local/bin/gitleaks",
        f"mv {work}/gitleaks {work}/bin/gitleaks",
    )
    # The runner installs into /usr/local/bin, which is on PATH; the sandbox
    # keeps the binary in work/bin, so call it by path on the last line.
    text = text.replace(
        "gitleaks version",
        f"{work}/bin/gitleaks version",
    )
    text = text.replace("--retry-delay 3", "--retry-delay 1")
    if "127.0.0.1" not in text:
        raise AssertionError("step body did not get its URL rewritten")
    return text


def run(script: str, label: str, work: pathlib.Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    (work / "bin").mkdir(exist_ok=True)
    proc = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", script],
        capture_output=True,
        text=True,
        timeout=240,
    )
    merged = (proc.stdout + proc.stderr).strip().splitlines()
    binary = work / "bin" / "gitleaks"
    reported = ""
    if binary.exists():
        reported = subprocess.run(
            [str(binary), "version"], capture_output=True, text=True
        ).stdout.strip()
    return {
        "case": label,
        "exit_code": proc.returncode,
        "binary_installed": binary.exists(),
        "gitleaks_version_output": reported,
        "last_output_lines": merged[-3:],
    }


def step_body_from_ref(ref: str, repo: pathlib.Path) -> str:
    """Read the pre-fix step body straight from a git object, no scratch copy."""
    text = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:.github/workflows/ci.yml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    doc = yaml.load(text, Loader=yaml.BaseLoader)
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == "Install gitleaks":
                return str(step["run"])
    raise AssertionError(f"Install gitleaks step not found at {ref}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True, help="workflow holding the fixed step")
    ap.add_argument(
        "--before-ref",
        required=True,
        help="git ref whose ci.yml still holds the pre-fix step",
    )
    ap.add_argument(
        "--repo", default=".", help="git repository to read --before-ref from"
    )
    ap.add_argument("--root", default="/tmp/it204/gitleaks-sim")
    args = ap.parse_args()

    root = pathlib.Path(args.root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    archive = root / "release.tar.gz"
    build_archive(archive, "8.30.1")

    bodies = {
        "after fix": step_body(pathlib.Path(args.workflow)),
        "before fix": step_body_from_ref(args.before_ref, pathlib.Path(args.repo)),
    }
    results = []
    attempts = {}
    for mode in ("clean", "flaky", "always500"):
        FlakyHandler.attempts = {}
        FlakyHandler.archive = archive
        FlakyHandler.mode = mode
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FlakyHandler)
        url = f"http://127.0.0.1:{server.server_address[1]}/gitleaks.tar.gz"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for tag, body in bodies.items():
                work = root / f"{mode}-{tag.replace(' ', '')}"
                results.append(run(localize(body, url, work), f"{mode} / {tag}", work))
                attempts[f"{mode} / {tag}"] = dict(FlakyHandler.attempts)
                FlakyHandler.attempts = {}
        finally:
            server.shutdown()
            server.server_close()

    print(
        json.dumps(
            {
                "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "workflow_under_test": args.workflow,
                "before_ref": args.before_ref,
                "shell": "bash -eo pipefail (the runner's default for run steps)",
                "results": results,
                "requests_per_case": attempts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
