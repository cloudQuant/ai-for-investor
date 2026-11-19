#!/usr/bin/env python3
"""Iteration 205 WP07 — complexity ratchet.

Fails when the backend grows beyond the reviewed complexity baseline.  The
baseline records both the worst block and the number of blocks at/above CC 50.
Use ``--update`` only after an intentional decomposition lowers the count.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("complexity_baseline.json")
TARGET = ROOT / "src" / "backend" / "app"


def _measure() -> tuple[int, int]:
    proc = subprocess.run(
        [sys.executable, "-m", "radon", "cc", str(TARGET), "-j", "-s"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    worst = 0
    count = 0
    for blocks in data.values():
        for block in blocks:
            complexity = int(block.get("complexity") or 0)
            worst = max(worst, complexity)
            if complexity >= 50:
                count += 1
    return worst, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    worst, count = _measure()
    if args.update:
        BASELINE.write_text(
            json.dumps(
                {"max_cc": worst, "count_cc_ge_50": count},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"complexity baseline updated: max_cc={worst} count_cc_ge_50={count}")
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = []
    if worst > int(baseline["max_cc"]):
        failures.append(f"max CC {worst} > baseline {baseline['max_cc']}")
    if count > int(baseline["count_cc_ge_50"]):
        failures.append(
            f"CC>=50 count {count} > baseline {baseline['count_cc_ge_50']}"
        )
    if failures:
        print("complexity budget exceeded:", "; ".join(failures), file=sys.stderr)
        return 1
    print(f"complexity budget OK (max_cc={worst}, count_cc_ge_50={count})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
