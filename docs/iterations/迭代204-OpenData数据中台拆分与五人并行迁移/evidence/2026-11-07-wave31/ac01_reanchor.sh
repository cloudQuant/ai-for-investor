#!/usr/bin/env bash
# AC01 re-anchor: regenerate the migration inventory's per-file SHA-256 anchors from the merged
# dev tree, then prove the result. Run only when no open PR still edits src/backend/app/data_fetch.
set -eu
WT="${1:?usage: ac01_reanchor.sh <clean worktree at dev head>}"
PY="/home/yun/Documents/ai-for-investor/src/backend/.venv/bin/python"
TOOL="$WT/src/backend/scripts/ops/refresh_script_migration_inventory.py"
CSV_REL="docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/script_migration_inventory.csv"
OUT=/tmp/it204/ac01-reanchor
mkdir -p "$OUT"

echo "== head: $(git -C "$WT" rev-parse HEAD)"
echo "== check (before)"
PYTHONPATH="$WT/src/backend" "$PY" "$TOOL" --repo-root "$WT" --check \
  --snapshot-commit 29afaeb47 --json-out "$OUT/check-before.json" | tail -4

echo "== emit"
PYTHONPATH="$WT/src/backend" "$PY" "$TOOL" --repo-root "$WT" --emit \
  --snapshot-commit 29afaeb47 --out "$OUT/script_migration_inventory.csv" \
  --json-out "$OUT/emit.json" | tail -4

echo "== install emitted csv over the tracked one"
cp "$OUT/script_migration_inventory.csv" "$WT/$CSV_REL"

echo "== check (after)"
PYTHONPATH="$WT/src/backend" "$PY" "$TOOL" --repo-root "$WT" --check \
  --snapshot-commit 29afaeb47 --json-out "$OUT/check-after.json" | tail -5

echo "== rows: $(wc -l < "$WT/$CSV_REL")"
echo "== git diff stat:"
git -C "$WT" diff --stat -- "$CSV_REL"
