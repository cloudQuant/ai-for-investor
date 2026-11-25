#!/usr/bin/env python3
"""Scan the current Git-tracked working tree with gitleaks."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]


def _copy_tracked_tree(root: Path, destination: Path) -> int:
    files = _tracked_files(root)
    if not files:
        raise RuntimeError("no Git-tracked files found")
    for relative in files:
        source = root / relative
        target = destination / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if shutil.which("gitleaks") is None:
        print("gitleaks executable not found", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="afi-gitleaks-tracked-") as temporary:
        scan_root = Path(temporary) / "tree"
        scan_root.mkdir()
        tracked_count = _copy_tracked_tree(root, scan_root)
        report = args.report.resolve() if args.report else Path(temporary) / "report.json"
        proc = subprocess.run(
            [
                "gitleaks",
                "dir",
                str(scan_root),
                "--config",
                str(root / ".gitleaks-tracked.toml"),
                "--gitleaks-ignore-path",
                str(root / ".gitleaksignore"),
                "--report-format",
                "json",
                "--report-path",
                str(report),
                "--redact",
                "--no-banner",
                "--exit-code",
                "1",
            ],
            cwd=root,
            check=False,
        )
        findings = json.loads(report.read_text("utf-8")) if report.exists() else []
        for finding in findings:
            finding["File"] = str(Path(finding["File"]).relative_to(scan_root))
            if isinstance(finding.get("Fingerprint"), str):
                finding["Fingerprint"] = finding["Fingerprint"].replace(
                    f"{scan_root}/", ""
                )
        report.write_text(json.dumps(findings, ensure_ascii=False, indent=2) + "\n", "utf-8")
        audited_keys: set[tuple[str, str, int]] = set()
        ignore_path = root / ".gitleaksignore"
        if ignore_path.is_file():
            for line in ignore_path.read_text("utf-8").splitlines():
                parts = line.strip().split(":")
                if len(parts) == 4 and parts[0] and parts[3].isdigit():
                    audited_keys.add((parts[1], parts[2], int(parts[3])))
        audited_matches = sum(
            (str(item.get("File")), str(item.get("RuleID")), int(item.get("StartLine", 0)))
            in audited_keys
            for item in findings
        )
        print(
            json.dumps(
                {
                    "scope": "git-tracked working tree",
                    "tracked_files": tracked_count,
                    "findings": len(findings),
                    "audited_line_matches": audited_matches,
                    "unclassified_candidates": len(findings) - audited_matches,
                    "report": str(report) if args.report else None,
                },
                ensure_ascii=False,
            )
        )
        for finding in findings:
            print(
                f"{finding.get('File')}:{finding.get('StartLine')}:{finding.get('RuleID')}"
            )
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
