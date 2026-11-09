#!/usr/bin/env python3
"""Classify OpenData's unbound akshare endpoints into provider-family buckets.

Why this exists: the migration plan's B0.0 step needs a candidate binding table
before "877 missing providers" can be turned into effort. This produces the two
numbers that matter (how many endpoints fit an existing akshare family, how many
need a new model) and the per-endpoint rows behind them, so a reviewer can check
the arithmetic instead of trusting a paragraph.

Inputs are both read-only:
  --catalog          docs/afi204-migration-catalog.json (default: git show origin/dev:...)
  --disposition-ledger  script_disposition_ledger.json from assign_script_dispositions.py

Output: JSON on stdout (or --out), plus a human summary on stderr.

The family classification is heuristic by construction: `asset_family` comes from
the disposition ledger, and the family -> domain mapping is the explicit table
below. It is a review bucket, not an assignment.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys

# Only families with an akshare provider model today are mapped; everything else
# is reported as "needs a new model" rather than quietly dropped.
FAMILY_TO_EXISTING_DOMAINS = {
    "bond": ["bond_daily"],
    "fund": ["fund_etf_daily"],
    "futures": ["futures_daily"],
    "index": ["index_daily", "index_constituent"],
    "option": ["option_daily"],
    "stock": ["stock_daily", "stock_action"],
}


def normalise_script_path(path: str | None) -> str:
    """Reduce both catalog and ledger paths to the data_fetch/scripts-relative form."""
    value = (path or "").replace("\\", "/")
    return re.sub(r"^.*?data_fetch/scripts/", "", value)


def load_catalog(path: str | None) -> dict:
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    out = subprocess.run(
        ["git", "-C", "/home/yun/Documents/opendata", "show",
         "origin/dev:docs/afi204-migration-catalog.json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def load_ledger_rows(path: str) -> list[dict]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = data.get("rows") if isinstance(data, dict) else data
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise SystemExit("disposition ledger does not expose a row list")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=None)
    parser.add_argument("--disposition-ledger", required=True)
    parser.add_argument("--out", default="-")
    parser.add_argument("--include-rows", action="store_true",
                        help="embed the per-endpoint classification rows (large)")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    files = catalog["files"]
    endpoints = catalog["provider_endpoint_catalog"]
    models = catalog["opendata_provider_models"]
    rows = load_ledger_rows(args.disposition_ledger)

    family_by_path = {
        normalise_script_path(row.get("path")): row.get("asset_family") for row in rows
    }

    # function -> families of the AFI scripts that call it
    families_by_function: dict[str, set[str]] = collections.defaultdict(set)
    for entry in files:
        family = family_by_path.get(normalise_script_path(entry.get("source_path")))
        if not family:
            continue
        for call in entry.get("calls") or []:
            function = call.get("function")
            if function:
                families_by_function[function].add(family)

    unbound = [endpoint for endpoint in endpoints if not endpoint.get("target_models")]
    buckets: collections.Counter[str] = collections.Counter()
    rows_out: list[dict] = []
    for endpoint in unbound:
        function = endpoint.get("function")
        families = sorted(families_by_function.get(function, set()))
        if not families:
            bucket = "no_calling_file"
            target_domains: list[str] = []
        elif len(families) > 1:
            bucket = "multi_family"
            target_domains = []
        elif families[0] in FAMILY_TO_EXISTING_DOMAINS:
            bucket = "fits_existing_akshare_family"
            target_domains = FAMILY_TO_EXISTING_DOMAINS[families[0]]
        else:
            bucket = "needs_new_model"
            target_domains = []
        buckets[bucket] += 1
        rows_out.append(
            {
                "function": function,
                "status": endpoint.get("status"),
                "endpoint_readiness": endpoint.get("runtime_verification"),
                "source_script_count": len(endpoint.get("source_scripts") or []),
                "source_scripts_sample": (endpoint.get("source_scripts") or [])[:3],
                "families": families,
                "bucket": bucket,
                "candidate_domains": target_domains,
            }
        )

    family_counts = collections.Counter(
        row["families"][0] for row in rows_out if len(row["families"]) == 1
    )
    models_by_source = collections.Counter(model.get("source") for model in models)
    document = {
        "endpoints_total": len(endpoints),
        "endpoints_bound_to_a_model": len(endpoints) - len(unbound),
        "endpoints_unbound": len(unbound),
        "provider_models_total": len(models),
        "provider_models_by_source": dict(models_by_source.most_common()),
        "buckets": dict(buckets.most_common()),
        "unbound_by_family": dict(family_counts.most_common()),
        "family_to_existing_domains": FAMILY_TO_EXISTING_DOMAINS,
    }
    if args.include_rows:
        document["rows"] = rows_out
    text = json.dumps(document, indent=2, ensure_ascii=False)
    if args.out == "-":
        print(text)
    else:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(
        "unbound={unbound} fits_existing={fits} needs_new={new} multi={multi} no_caller={none} "
        "akshare_models={ak} of {total} models -> {out}".format(
            unbound=len(unbound),
            fits=buckets["fits_existing_akshare_family"],
            new=buckets["needs_new_model"],
            multi=buckets["multi_family"],
            none=buckets["no_calling_file"],
            ak=models_by_source.get("akshare", 0),
            total=len(models),
            out=args.out,
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
