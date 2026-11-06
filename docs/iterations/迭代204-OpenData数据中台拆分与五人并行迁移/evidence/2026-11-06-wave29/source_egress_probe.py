"""Bound what real-source verification can actually prove from this machine, before any of it is booked.

Why this exists: AC11 has 18 rows that need a live source run before a disposition can be decided,
and AC10 needs per-field source comparison. Several of those depend on specific upstream hosts. If a
host is unreachable from here, a "0 rows" result is not a statement about the dataset -- akshare's
wrappers return an empty frame both when the source has nothing and when the request never landed.
So every source claim must be paired with a reachability probe of the exact host it relies on.

Read-only network probes plus upstream akshare calls. Nothing is written to any database.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import time

HOSTS = {
    "push2.eastmoney.com": "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=2&fields=f1,f2&fs=m:1+t:2",
    "82.push2.eastmoney.com": "https://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fields=f1&fs=m:1",
    "datacenter-web.eastmoney.com": "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_FUND_RANK&pageSize=1",
    "data.eastmoney.com": "https://data.eastmoney.com/",
    "hq.sinajs.cn": "https://hq.sinajs.cn/list=sh000001",
}

# The old upstream path akshare still uses for the movie-boxoffice family, versus the one AFI uses.
ENDATA_OLD_POST = "https://www.endata.com.cn/API/GetData/"
AKSHARE_BOXOFFICE = ("movie_boxoffice_daily", "movie_boxoffice_cinema_daily",
                     "movie_boxoffice_cinema_weekly", "movie_boxoffice_weekly",
                     "movie_boxoffice_monthly", "movie_boxoffice_first_week")


def probe_hosts(repeat: int) -> dict:
    import requests

    out = {}
    for name, url in HOSTS.items():
        tries = []
        for _ in range(repeat):
            try:
                r = requests.get(url, timeout=10, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                })
                tries.append([r.status_code, len(r.text)])
            except Exception as exc:  # noqa: BLE001
                tries.append(type(exc).__name__)
            time.sleep(1)
        out[name] = tries
    return out


def probe_endata() -> dict:
    import requests

    res = {}
    try:
        r = requests.post(ENDATA_OLD_POST,
                          data={"id": "", "boxid": "", "tablename": "bo_daily", "dtlist": ""},
                          timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        res["old_post"] = {"status": r.status_code, "len": len(r.text), "head": r.text[:80]}
    except Exception as exc:  # noqa: BLE001
        res["old_post"] = f"{type(exc).__name__}: {str(exc)[:80]}"
    return res


def probe_akshare(dates) -> dict:
    import akshare as ak

    out = {"akshare_version": getattr(ak, "__version__", "?"), "functions": {}}
    for name in AKSHARE_BOXOFFICE:
        fn = getattr(ak, name, None)
        if fn is None:
            out["functions"][name] = "ABSENT_IN_INSTALLED_AKSHARE"
            continue
        obs = {}
        try:
            params = inspect.signature(fn).parameters
        except Exception:  # noqa: BLE001
            params = {}
        if "date" in params:
            for d in dates:
                try:
                    df = fn(date=d)
                    obs[d] = int(df.shape[0])
                except Exception as exc:  # noqa: BLE001
                    obs[d] = f"{type(exc).__name__}"
                time.sleep(0.5)
        else:
            try:
                df = fn()
                obs["no-arg"] = int(df.shape[0])
            except Exception as exc:  # noqa: BLE001
                obs["no-arg"] = f"{type(exc).__name__}"
        out["functions"][name] = obs

    # controls: prove egress works at all, so an empty frame cannot be blamed on the network
    ctrl = {}
    try:
        ctrl["stock_zh_index_daily(sh000001)"] = int(ak.stock_zh_index_daily(symbol="sh000001").shape[0])
    except Exception as exc:  # noqa: BLE001
        ctrl["stock_zh_index_daily(sh000001)"] = type(exc).__name__
    try:
        ctrl["macro_china_ppi"] = int(ak.macro_china_ppi().shape[0])
    except Exception as exc:  # noqa: BLE001
        ctrl["macro_china_ppi"] = type(exc).__name__
    out["controls_proving_egress"] = ctrl
    return out



def probe_afis_side(backend_root: str) -> dict:
    """The other half of the decision: does AFI's own endata fetcher still return data?

    akshare's movie-boxoffice family returns 0 rows, which alone cannot tell an unavailable dataset
    from a dead upstream path. This calls the in-tree client the way the scripts do.
    """
    import sys

    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    out = {}
    try:
        from app.data_fetch.scripts.common import _endata_yien as E  # type: ignore

        client = E.EndataYienClient()
    except Exception as exc:  # noqa: BLE001
        return {"import_or_construct": f"{type(exc).__name__}: {str(exc)[:90]}"}
    for name in ("now_date", "latest_completed_day"):
        try:
            out[name] = getattr(client, name)()
        except Exception as exc:  # noqa: BLE001
            out[name] = f"{type(exc).__name__}: {str(exc)[:80]}"
    try:
        dd = client.date_data
        dd = dd() if callable(dd) else dd
        out["date_data"] = {"type": type(dd).__name__, "keys": sorted(dd)[:6], "n": len(dd)}
    except Exception as exc:  # noqa: BLE001
        out["date_data"] = f"{type(exc).__name__}: {str(exc)[:80]}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--dates", default="20240219,20250101,20260105,20261104")
    ap.add_argument("--backend-root", default="/home/yun/Documents/ai-for-investor/src/backend")
    args = ap.parse_args()

    doc = {
        "probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hosts": probe_hosts(args.repeat),
        "endata": probe_endata(),
        "akshare_boxoffice_family": probe_akshare(args.dates.split(",")),
        "afis_own_endata_client": probe_afis_side(args.backend_root),
        "meaning": (
            "A host listed with ConnectionError on every try cannot be verified from this machine, so "
            "any 0-row result for a script that depends on it is a reachability statement, not a "
            "dataset statement. Controls that return rows prove egress works overall."
        ),
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
