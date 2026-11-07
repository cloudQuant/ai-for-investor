"""Audit each wave-29 section for citable provenance.

The acceptance protocol says a number without a producing instrument or CI artifact is only a
citation. This walks the drafted section, and for every section that asserts digits, checks that it
also names at least one source: an evidence script/JSON, a workflow run/job id, a commit sha, a
PR number, or a file:line. Sections that fail are the ones I have to fix before the PR opens.
"""

import io
import re
import sys

SECTION = sys.argv[1] if len(sys.argv) > 1 else "/tmp/it204/wave29-section.md"
EVIDENCE_DIR = "/home/yun/Documents/.wt-afi-wave29/docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/evidence/2026-11-06-wave29"

text = io.open(SECTION, encoding="utf-8").read()
parts = re.split(r"(?m)^(#### .*)$", text)

import os

instruments = set(os.listdir(EVIDENCE_DIR))

rows = []
for i in range(1, len(parts), 2):
    title = parts[i].strip()
    body = parts[i + 1] if i + 1 < len(parts) else ""
    has_digits = bool(re.search(r"\d{2,}", body))
    srcs = []
    if re.search(r"evidence/2026-11-06-wave29/[\w.\-]+", body):
        srcs.append("evidence-path")
    for name in instruments:
        if name in body:
            srcs.append(f"instrument:{name}")
    if re.search(r"\b(?:run|作业)\s*\d{8,}|\b\d{10,}\b", body):
        srcs.append("ci-run-id")
    if re.search(r"\b[0-9a-f]{9,40}\b", body):
        srcs.append("sha")
    if re.search(r"#\d{3}", body):
        srcs.append("pr")
    if re.search(r"\.py:\d+|\.yml:\d+|\.json:\d+|\.md:\d+", body):
        srcs.append("file:line")
    if re.search(r"[\w/.\-]+\.(py|json|csv|md)\b", body):
        srcs.append("named-artifact")
    if re.search(r"/tmp/it204/[\w.\-/]+", body):
        srcs.append("scratch-path")
    rows.append((title[:74], has_digits, sorted(set(srcs))))

weak = [r for r in rows if r[1] and not {"evidence-path","instrument","ci-run-id","file:line",
        "named-artifact","sha"} & set(x.split(":")[0] for x in r[2])]
bad = [r for r in rows if r[1] and not r[2]]
print(f"sections={len(rows)}  with-numbers={sum(1 for r in rows if r[1])}  WITHOUT any source handle={len(bad)}\n")
for t, _, _ in bad:
    print("  MISSING SOURCE:", t)
print("\nWEAK sections (numbers, but only a PR handle as source):")
for t, _, sr in weak:
    print("   ", t, "->", sr)
print("\nper-section sources:")
for t, d, s in rows:
    print(f"  {'NUM ' if d else '     '}{t[:60]:62} -> {', '.join(x.split(':')[1] if x.startswith('instrument') else x for x in s)[:80]}")
