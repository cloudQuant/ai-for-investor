"""Search the host read-only for the ExecStart targets that are missing from git.

AC01 says these runtime assets must be enumerable; whether they are *recoverable* decides between
"restore and commit" and "retire the units". This looks for the files themselves and for compiled
counterparts, which at least prove the module existed and where it lived.
"""
import json
import subprocess

targets = json.load(open("/tmp/it204/unit_audit.json"))["units"]
names = sorted({p.rsplit("/", 1)[-1] for u in targets for p in u["missing_on_disk"]})
print("distinct missing ExecStart targets:", len(names))

ROOTS = "/home/yun/Documents /home/yun/afi204-evidence /home/yun/.config/systemd /var/tmp /tmp"
for n in names:
    stem = n[:-3] if n.endswith(".py") else n
    ext = "pyc" if n.endswith(".py") else "*"
    pattern = "-name '%s' -o -name '%s.cpython-*.pyc' -o -name '%s.*'" % (n, stem, stem)
    cmd = ("find %s -xdev \\( %s \\) -printf '%%s\\t%%p\\n' 2>/dev/null | grep -v '^0\\t' | head -5"
           % (ROOTS, pattern))
    r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=180)
    hits = [line for line in r.stdout.strip().split("\n") if line]
    print("---", n)
    if not hits:
        print("    nothing on host (also checked compiled counterparts)")
    for h in hits:
        print("    ", h)
