# Wave 32 evidence — secret-scan gate attributability

## What was measured

`Security - Secret Scan (177 §D)` was the only red member of dev CI run
`42472229710` (head `7c8f6f2f12f9ac325a6a1608f340b4ea8c8a7b92`, pushed
2026-11-08T10:37:43Z). Job `128705525478` exited 2 in 14 s; the log holds no
gitleaks finding:

```
curl: (56) Connection died, tried 5 times before giving up
tar: Error is not recoverable: exiting now
##[error]Process completed with exit code 2.
```

The step immediately before it had already printed
`Gitleaks history baseline check passed (accepted=281, unresolved=0, blocking_ready=true)`,
so the red was the scanner binary failing to arrive, not a leak. Rerunning that
one job (attempt 2, job `128754894980`) made the whole run green without any
repository change — which is the definition of a non-attributable gate.

Across the 20 dev `CI - Quality Checks` runs before that head, the secret-scan
member succeeded on its recorded attempt 19/19 times; the 20th is this head,
whose first attempt failed and whose rerun passed.

## Instrument

`gitleaks_install_step_sim.py` extracts the `Install gitleaks` step body verbatim
from the workflow under test and from a pinned `--before-ref`'s `ci.yml`, serves a
real `gitleaks` archive from a loopback HTTP server, and executes each body in the
runner's own shell (`bash -eo pipefail`). Only the download URL, the scratch paths,
and the two lines that assume `/usr/local/bin` is on PATH are rewritten.

```bash
python3 docs/iterations/迭代204-OpenData数据中台拆分与五人并行迁移/evidence/2026-11-08-wave32/gitleaks_install_step_sim.py \
  --workflow .github/workflows/ci.yml \
  --before-ref 7c8f6f2f12f9ac325a6a1608f340b4ea8c8a7b92 \
  --repo . --root /tmp/gitleaks-sim
```

`gitleaks_install_step_simulation.json` is that command's output
(2026-11-08T14:25:21Z). `requests_per_case` is the server's own count, so the
retry behaviour is observable rather than asserted.

## Reading

| case | before fix | after fix |
| --- | --- | --- |
| clean | exit 0, binary reports `gitleaks version 8.30.1` | identical |
| first response truncated mid-body | exit 2, `tar: Error is not recoverable` (the CI signature) | exit 0 after 2 requests, `curl: (18) end of response with 578 bytes missing` stays in the log |
| release host answers 500 every time | exit 2, `gzip: stdin: not in gzip format` | exit 22, `curl: (22) The requested URL returned error: 500` after 6 requests, `tar` never invoked |

The fixed step therefore (a) survives a transient release-host failure, and
(b) when it cannot be rescued, says so in the first line of its own output
instead of leaving a corrupt-archive error to be mistaken for a scan result.

## Not claimed

- This does not prove gitleaks found nothing in history; that is the baseline
  checker's own line, quoted above, and the `no leaks found` audit in
  `SUBAGENT_TASKS.md` row 229.
- The local server emulates the failure shape seen in the CI log; the real
  release host was never reachable from this machine (`SUBAGENT_TASKS.md` row
  269 records the egress limits).
- The added version-agreement check in `check_gitleaks_history_baseline.py`
  makes the baseline's `gitleaks_version` field load-bearing for the first
  time. It passes on `7c8f6f2f12f` because the workflow and the audit both
  say `8.30.1`; it does not prove the fingerprints are correct for 8.30.1.
