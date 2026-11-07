"""Upper-bound the resolvable share of the `accepts_var_kwargs` bucket, read-only.

The census says 886 of 1048 armed tasks land in `accepts_var_kwargs` and calls that
"unverifiable statically, not proven safe". AC11 needs a ceiling, not a hope: of those, how many
forward `**kwargs` to a single, literally-named callee that exists in the tree (or in the installed
akshare), and how many are dynamic / multi-site / second-hop and therefore stay unverifiable?

This is a shape count over source text -- it does not claim any task binds, and it deliberately
reports the classes it cannot decide rather than guessing them.
"""

from __future__ import annotations

import argparse
import ast
import collections
import io
import json
import os
import sys


def entrypoints(tree: ast.Module):
    """Functions that take **kwargs, whether run()/fetch_data()/main()."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.args.kwarg:
            yield node


def forwarded_calls(func):
    """Calls inside `func` passing **kwargs, as (callee_kind, name)."""
    out = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not any(kw.arg is None for kw in node.keywords):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and isinstance(f.ctx, ast.Load):
            out.append(("attr", f"{f.value.id}.{f.attr}"))
        elif isinstance(f, ast.Attribute):
            out.append(("attr_dynamic_base", None))
        elif isinstance(f, ast.Name):
            out.append(("name", f.id))
        else:
            out.append(("other", None))
    return out


def module_defines(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", default="/home/yun/Documents/ai-for-investor/src/backend/app/data_fetch/scripts")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    classes = collections.Counter()
    examples = collections.defaultdict(list)
    for root, _dirs, files in os.walk(args.scripts):
        if "__pycache__" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, args.scripts)
            try:
                text = io.open(path, encoding="utf-8").read()
                tree = ast.parse(text)
            except Exception:  # noqa: BLE001
                classes["unparsed_file"] += 1
                continue
            eps = list(entrypoints(tree))
            if not eps:
                classes["no_kwargs_entrypoint"] += 1
                continue
            calls = []
            for ep in eps:
                calls.extend(forwarded_calls(ep))
            if not calls:
                classes["accepts_kwargs_but_forwards_nothing"] += 1
                examples["accepts_kwargs_but_forwards_nothing"].append(rel)
                continue
            literal = [c for c in calls if c[1]]
            dynamic = [c for c in calls if not c[1]]
            if dynamic:
                classes["forwards_through_dynamic_callee"] += 1
                examples["forwards_through_dynamic_callee"].append(rel)
                continue
            names = {c[1].split(".")[-1] for c in literal}
            if len(calls) > 1 or len(names) > 1:
                classes["forwards_to_multiple_callees"] += 1
                examples["forwards_to_multiple_callees"].append(rel)
                continue
            callee = next(iter(names))
            if callee in module_defines(tree):
                classes["forwards_to_single_local_callee"] += 1
            else:
                classes["forwards_to_single_external_name"] += 1
                examples["forwards_to_single_external_name"].append(f"{rel} -> {callee}")

    doc = {
        "scripts_root": args.scripts,
        "classes": dict(classes),
        "decidable_now": classes["forwards_to_single_local_callee"],
        "needs_external_signature": classes["forwards_to_single_external_name"],
        "unverifiable_by_shape": (
            classes["forwards_through_dynamic_callee"]
            + classes["forwards_to_multiple_callees"]
            + classes["accepts_kwargs_but_forwards_nothing"]
        ),
        "sample_external_targets": sorted(set(examples["forwards_to_single_external_name"]))[:12],
        "meaning": ("Shape counts only. 'forwards_to_single_local_callee' can be decided by reading the "
                    "callee's def in the same file; 'external_name' needs the installed akshare signature; "
                    "the rest is genuinely dynamic and stays unverifiable. Nothing here proves a task binds."),
    }
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(text)
        print(text, file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
