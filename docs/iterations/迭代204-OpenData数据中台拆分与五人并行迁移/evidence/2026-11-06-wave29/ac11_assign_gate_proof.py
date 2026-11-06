"""Prove the AC11 assignment gate works end-to-end, and prove that nothing here is an assignment.

Reproduces wave-29 section 23. It exercises the three states the tool can reach:

  review_missing_reviewer_name  blank reviewer is refused -> the gate is real
  review_stale_for_sha256       one drifted file hash is refused -> bindings are per-file
  assigned                      a name + matching disposition/sha is accepted

The accepted case uses the literal string ``PROOF-NOT-A-HUMAN`` as the reviewer. That is deliberate:
it demonstrates the mechanism without producing anything that could be cited as a human approval.
Every output goes under ``--work-dir`` (default /tmp) and none of it is committed or booked.
Run it only against a scratch out-dir; it never writes the ledger into the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter

TOOL_REL = "src/backend/scripts/ops/assign_script_dispositions.py"


def run_tool(root: str, out_dir: str, review_file: str | None, batch_id: str, limit: int) -> dict:
    cmd = [sys.executable, os.path.join(root, TOOL_REL),
           "--limit", str(limit), "--batch-id", batch_id,
           "--script-listing", "filesystem", "--out-dir", out_dir]
    if review_file:
        cmd += ["--review-file", review_file]
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise SystemExit(f"tool failed rc={r.returncode}: {r.stderr[-400:]}")
    return json.load(open(os.path.join(out_dir, "script_disposition_ledger.json")))


def inbatch(document):
    return [row for row in document["rows"] if row.get("in_batch") == "yes"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/yun/Documents/.wt-afi-disp",
                    help="worktree containing the #286 disposition tool")
    ap.add_argument("--work-dir", default="/tmp/it204/ac11-proof")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    work = args.work_dir
    os.makedirs(work, exist_ok=True)
    out = {"batch_limit": args.limit, "root": args.root}

    step1 = run_tool(args.root, os.path.join(work, "s1"), None, "AC11-proof-01", args.limit)
    proposed = [r for r in inbatch(step1) if r["decision_state"] == "proposed"]
    out["step1_proposed"] = len(proposed)

    def review_records(reviewer: str, stale_first: bool = False):
        recs = []
        for idx, row in enumerate(proposed):
            recs.append({
                "path": row["path"], "reviewer": reviewer, "decision": "approve",
                "disposition": row["disposition"],
                "file_sha256": ("0" * 64) if (stale_first and idx == 0) else row["sha256"],
                "reviewed_at_utc": "2026-11-06T16:02:00Z",
            })
        return {"reviews": recs}

    # A. blank reviewer must be refused
    blank = os.path.join(work, "review-blank.json")
    json.dump(review_records(""), open(blank, "w"))
    step2 = run_tool(args.root, os.path.join(work, "s2-blank"), blank, "AC11-proof-01", args.limit)
    out["blank_reviewer_states"] = dict(Counter(r["decision_state"] for r in inbatch(step2)))

    # B. a non-human marker should reach `assigned` -- mechanism proof only
    named = os.path.join(work, "review-named.json")
    json.dump(review_records("PROOF-NOT-A-HUMAN"), open(named, "w"))
    step3 = run_tool(args.root, os.path.join(work, "s3-named"), named, "AC11-proof-01", args.limit)
    out["named_marker_states"] = dict(Counter(r["decision_state"] for r in inbatch(step3)))
    out["decided_by_sample"] = inbatch(step3)[0]["decided_by"]

    # C. one stale file hash should not take the whole batch with it
    stale = os.path.join(work, "review-stale.json")
    json.dump(review_records("PROOF-NOT-A-HUMAN", stale_first=True), open(stale, "w"))
    step4 = run_tool(args.root, os.path.join(work, "s4-stale"), stale, "AC11-proof-01", args.limit)
    out["one_stale_sha_states"] = dict(Counter(r["decision_state"] for r in inbatch(step4)))

    out["meaning"] = ("`assigned` here is produced by a fake reviewer string and lives only in --work-dir. "
                      "It shows the signing path is not broken; it is not evidence that anyone approved "
                      "a disposition. The real ratio stays 0 until a named human signs.")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
