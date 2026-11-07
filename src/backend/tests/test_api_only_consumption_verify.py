"""Fixture-driven tests for scripts/ops/verify_api_only_consumption.py (AC18).

Everything runs against tmp_path trees: no network, no systemctl, no DB, no
live ps.  Each guard is pinned with the counterfactual that shows it bites.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "ops" / "verify_api_only_consumption.py"
)
spec = importlib.util.spec_from_file_location("verify_api_only_consumption", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
verify = importlib.util.module_from_spec(spec)
# Register before exec: @dataclass resolution in the module looks it up in sys.modules.
sys.modules.setdefault("verify_api_only_consumption", verify)
spec.loader.exec_module(verify)

SENTINEL_PW = "S3NTINEL-pw-MUST-NOT-LEAK"
LEG_SDK = "no_source_sdk"
LEG_DSN = "no_warehouse_dsn_in_artifact"
LEG_PROC = "no_residual_collection_process"
LEG_EGRESS = "egress_limited_to_opendata_api"
LEG_REVOKED = "data_consumption_tests_after_revocation"

CLEAN_PYPROJECT = """\
[project]
name = "backend"
dependencies = ["fastapi>=0.110"]

[project.optional-dependencies]
data = ["pyarrow>=14.0.0"]
"""

SDK_PYPROJECT = """\
[project]
name = "backend"
dependencies = []

[project.optional-dependencies]
data = [
    "akshare>=1.18.96,<1.19; python_version >= '3.11'",
    "akshare>=1.18.88,<1.18.89; python_version < '3.11'",
    "pyarrow>=14.0.0,<26.0.0",
]
"""


def build_repo(tmp_path: Path, *, pyproject: str = CLEAN_PYPROJECT) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "backend" / "app").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "frontend" / "dist" / "assets").mkdir(parents=True, exist_ok=True)
    (repo / "docker").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "backend" / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (repo / "docker" / "docker-compose.yml").write_text(
        "services:\n  api:\n    image: python:3.11\n", encoding="utf-8"
    )
    (repo / "src" / "backend" / ".env").write_text(
        "APP_HOST=127.0.0.1\nOPENAPI=http://localhost:8000/v1\n", encoding="utf-8"
    )
    (repo / "src" / "frontend" / "dist" / "assets" / "index-BBGKIPDO.js").write_text(
        "const dbs=['ai_for_investor','akshare_data'];export default dbs;\n", encoding="utf-8"
    )
    (repo / "src" / "backend" / "app" / "config.py").write_text(
        'WAREHOUSE = "akshare_data_database"\n', encoding="utf-8"
    )
    (repo / "src" / "backend" / "app" / "sync.py").write_text(
        'AKSHARE_DATA_DATABASE_URL = env("AKSHARE_DATA_DATABASE_URL")\n', encoding="utf-8"
    )
    (repo / "src" / "backend" / "app" / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def make_config(tmp_path: Path, **overrides):  # -> verify.Config (dynamic module: not static)
    repo = overrides.pop("repo_root", None) or build_repo(tmp_path)
    defaults = {
        "repo_root": repo,
        "use_systemctl": False,
        "ps_output_text": "1 systemdsystemd --switched-root --system\n",
        "venv_python": repo / "src" / "backend" / ".venv" / "bin" / "python",
        "import_prober": lambda _venv, _sdk: {"state": "ABSENT"},
        "opendata_root": tmp_path / "opendata",
    }
    defaults.update(overrides)
    return verify.Config(**defaults)


def leg(receipt: dict, name: str) -> dict:
    return next(item for item in receipt["legs"] if item["name"] == name)


def all_text(receipt: dict, stdout: str) -> str:
    return json.dumps(receipt, ensure_ascii=False) + stdout


class TestDsnMasking:
    """(a) A DSN in a fake dist is flagged and the sentinel password never leaks."""

    def test_flagged_and_secret_never_emitted(self, tmp_path):
        repo = build_repo(tmp_path)
        (repo / "src" / "frontend" / "dist" / "assets" / "leak.js").write_text(
            f'var cfg = "mysql+pymysql://svc:{SENTINEL_PW}@10.0.0.7:3306/akshare_data";\n',
            encoding="utf-8",
        )
        config = make_config(tmp_path, repo_root=repo)
        receipt, code = verify.run_verification(config)
        dsn_leg = leg(receipt, LEG_DSN)
        assert dsn_leg["status"] == verify.FAIL and code != 0
        finding = dsn_leg["detail"]["findings"][0]
        assert finding["file"] == "assets/leak.js"
        assert "db_scheme_url" in finding["pattern_names"]
        assert "credential_at_host" in finding["pattern_names"]
        assert finding["matched_line_count"] >= 1
        summary = verify.format_summary(receipt, code)
        combined = all_text(receipt, summary)
        assert SENTINEL_PW not in combined
        assert "svc:" not in combined
        assert "10.0.0.7:3306" not in combined.replace(finding["file"], "")

    def test_minified_css_does_not_false_positive(self, tmp_path):
        # Counterfactual pinned from the real host: naive user:pass@host regexes
        # matched 50 minified CSS files (`gap:12px}...@keyframes`, `}@media`).
        # The credential pattern must require credential-charset secrets and a
        # dotted/IP/localhost host, so this content scans clean...
        repo = build_repo(tmp_path)
        (repo / "src" / "frontend" / "dist" / "assets" / "page-BNdObE28.css").write_text(
            "gap:12px}.dialog-actions[data-v-26d97afe]{flex-wrap:wrap}@keyframes"
            "spin{40%{opacity:1;transform:scale(.7)}}@media(min-width:1px){.a{b:2px}}",
            encoding="utf-8",
        )
        receipt, _code = verify.run_verification(make_config(tmp_path, repo_root=repo))
        assert leg(receipt, LEG_DSN)["status"] == verify.PASS
        # ...while a URL-encoded password in the same shape is still caught.
        (repo / "src" / "frontend" / "dist" / "assets" / "real-leak.js").write_text(
            'c="postgresql+psycopg://admin:p%40ss@db.corp:5432/prod"', encoding="utf-8"
        )
        receipt2, code2 = verify.run_verification(make_config(tmp_path, repo_root=repo))
        dsn_leg = leg(receipt2, LEG_DSN)
        assert dsn_leg["status"] == verify.FAIL and code2 == 1
        names = dsn_leg["detail"]["findings"][0]["pattern_names"]
        assert "credential_at_host" in names and "db_scheme_url" in names
        assert "p%40ss" not in json.dumps(receipt2, ensure_ascii=False)


class TestSourceSdkCriterion:
    """(b)(c) The SDK leg keys on declaration/import, NEVER on bare strings."""

    def test_bare_akshare_identifiers_alone_do_not_fail_the_leg(self, tmp_path):
        # The false-positive guard: dist is FULL of the literal word akshare
        # (UI db names + a chunk filename), but nothing is declared/importable.
        repo = build_repo(tmp_path)
        dist = repo / "src" / "frontend" / "dist" / "assets"
        (dist / "akshare-BBGKIPDO.js").write_text(
            "import {akshare_data} from './db'; // ai_for_investor, akshare_data\n",
            encoding="utf-8",
        )
        config = make_config(tmp_path, repo_root=repo)
        receipt, _code = verify.run_verification(config)
        sdk_leg = leg(receipt, LEG_SDK)
        assert sdk_leg["status"] == verify.PASS  # string hits must not fail the leg
        assert sdk_leg["detail"]["artifact_bare_string_file_hits"] >= 2
        assert sdk_leg["detail"]["bare_string_hits_are_not_the_criterion"] is True

    def test_declared_sdk_fails_leg_despite_clean_dist(self, tmp_path):
        repo = build_repo(tmp_path, pyproject=SDK_PYPROJECT)
        config = make_config(tmp_path, repo_root=repo)
        receipt, code = verify.run_verification(config)
        sdk_leg = leg(receipt, LEG_SDK)
        assert sdk_leg["status"] == verify.FAIL
        assert code == 1  # unwaived FAIL dominates NOT_RUN
        assert any("akshare>=" in dep for dep in sdk_leg["detail"]["declared_dependency_strings"])
        assert "BY DESIGN" in sdk_leg["note"]

    def test_importable_sdk_fails_leg_even_when_not_declared(self, tmp_path):
        config = make_config(
            tmp_path,
            import_prober=lambda _v, _s: {
                "state": "IMPORTABLE",
                "origin": "/fake/akshare/__init__.py",
            },
        )
        receipt, _code = verify.run_verification(config)
        assert leg(receipt, LEG_SDK)["status"] == verify.FAIL

    def test_absent_everywhere_passes_leg(self, tmp_path):
        # (c) clean pyproject + ABSENT probe => the leg passes.
        config = make_config(tmp_path)
        receipt, _code = verify.run_verification(config)
        assert leg(receipt, LEG_SDK)["status"] == verify.PASS


class TestDenominator:
    """(d) collection vs non-collection split on a synthetic tree."""

    def _mark(self, repo: Path, rel: str, body: str = "akshare_data_database") -> None:
        path = repo / "src" / "backend" / "app" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'X = "{body}"\n', encoding="utf-8")

    def test_split_counts(self, tmp_path):
        repo = build_repo(tmp_path)
        self._mark(repo, "data_fetch/configs/db_config.py")
        self._mark(repo, "api/akshare/tables.py")
        self._mark(repo, "services/akshare/data.py")
        self._mark(repo, "services/sync_service.py")
        self._mark(repo, "db/__init__.py", "AKSHARE_DATA_DATABASE_URL")
        denom = verify.scan_warehouse_denominator(repo / "src" / "backend" / "app")
        assert denom["total_files"] == 7  # incl. pre-made config.py + sync.py
        assert denom["collection_domain_count"] == 3
        assert denom["non_collection_domain_count"] == 4
        assert "data_fetch/configs/db_config.py" in denom["collection_domain"]
        assert "config.py" in denom["non_collection_domain"]
        assert "services/sync_service.py" in denom["non_collection_domain"]
        assert "unrelated.py" not in json.dumps(denom)

    def test_receipt_carries_denominator(self, tmp_path):
        receipt, _code = verify.run_verification(make_config(tmp_path))
        denom = receipt["denominator_warehouse_dsn_files"]
        assert denom["total_files"] == 2  # app/config.py + app/sync.py


class TestNotRunSemantics:
    """(e) unavailable legs => NOT_RUN, nonzero exit, distinct from FAIL."""

    def test_unavailable_legs_are_not_run_and_exit_3(self, tmp_path):
        receipt, code = verify.run_verification(make_config(tmp_path))
        assert leg(receipt, LEG_EGRESS)["status"] == verify.NOT_RUN
        assert leg(receipt, LEG_REVOKED)["status"] == verify.NOT_RUN
        assert code == 3
        assert receipt["failures"] == []
        assert sorted(receipt["skips_not_run"]) == sorted([LEG_EGRESS, LEG_REVOKED])

    def test_not_run_is_distinguished_from_fail(self, tmp_path):
        repo = build_repo(tmp_path, pyproject=SDK_PYPROJECT)
        receipt, code = verify.run_verification(make_config(tmp_path, repo_root=repo))
        statuses = {item["name"]: item["status"] for item in receipt["legs"]}
        assert statuses[LEG_SDK] == verify.FAIL
        assert statuses[LEG_EGRESS] == verify.NOT_RUN
        assert code == 1  # FAIL is reported, NOT_RUN is not folded into it
        assert receipt["failures"] == [LEG_SDK]
        assert LEG_EGRESS in receipt["skips_not_run"]

    def test_egress_reports_host_set_without_claiming_pass(self, tmp_path):
        repo = build_repo(tmp_path)
        (repo / "src" / "backend" / ".env").write_text(
            "LLM=https://api.siliconflow.cn/v1\n"
            f"DB=mysql+pymysql://svc:{SENTINEL_PW}@192.168.1.9:3306/x\n"
            "API=http://localhost:8000\n",
            encoding="utf-8",
        )
        config = make_config(tmp_path, repo_root=repo)
        receipt, code = verify.run_verification(config)
        info = leg(receipt, LEG_EGRESS)["detail"]["config_hosts"]
        assert info["hosts"]["api.siliconflow.cn"] == "external"
        assert info["hosts"]["192.168.1.9"] == "internal_private"
        assert info["hosts"]["localhost"] == "internal_loopback"
        assert info["credential_shaped_value_count"] == 1
        assert leg(receipt, LEG_EGRESS)["status"] == verify.NOT_RUN
        assert code == 3
        assert SENTINEL_PW not in all_text(receipt, verify.format_summary(receipt, code))


class TestWaivers:
    """(f) --allow-fail-leg records the waiver and never pretends success."""

    def test_waiver_recorded_in_receipt_and_status_stays_fail(self, tmp_path):
        repo = build_repo(tmp_path, pyproject=SDK_PYPROJECT)
        config = make_config(
            tmp_path,
            repo_root=repo,
            allow_fail_legs={LEG_SDK},
            waiver_note="pre-cutover: data extra still pins akshare",
        )
        receipt, code = verify.run_verification(config)
        sdk_leg = leg(receipt, LEG_SDK)
        assert sdk_leg["status"] == verify.FAIL  # never rewritten to PASS
        assert sdk_leg["waived"] is True
        assert receipt["failures"] == []
        assert receipt["waived_failures"] == [
            {
                "leg": LEG_SDK,
                "note": "pre-cutover: data extra still pins akshare",
                "granted_via": "--allow-fail-leg",
                "printed_in_receipt": True,
            }
        ]
        assert code == 3  # waiver clears the FAIL, NOT_RUN legs still block exit 0
        summary = verify.format_summary(receipt, code)
        assert "WAIVER RECORDED" in summary and "(WAIVED)" in summary

    def test_waiver_plus_evidence_reaches_exit_0(self, tmp_path):
        repo = build_repo(tmp_path, pyproject=SDK_PYPROJECT)
        eg = tmp_path / "egress.txt"
        rv = tmp_path / "revocation.txt"
        eg.write_text("observed egress: only opendata api\n", encoding="utf-8")
        rv.write_text("consumption suite green after revoke\n", encoding="utf-8")
        config = make_config(
            tmp_path,
            repo_root=repo,
            allow_fail_legs={LEG_SDK},
            egress_evidence=eg,
            revocation_evidence=rv,
        )
        receipt, code = verify.run_verification(config)
        assert code == 0
        assert leg(receipt, LEG_SDK)["status"] == verify.FAIL  # still honest
        assert receipt["skips_not_run"] == []

    def test_not_run_cannot_be_waived(self, tmp_path):
        config = make_config(tmp_path, allow_fail_legs={LEG_EGRESS})
        receipt, code = verify.run_verification(config)
        assert leg(receipt, LEG_EGRESS)["status"] == verify.NOT_RUN
        assert receipt["waived_failures"] == []
        assert any(w["leg"] == LEG_EGRESS for w in receipt["ignored_waiver_requests"])
        assert code == 3

    def test_unknown_leg_waiver_is_recorded_not_silent(self, tmp_path):
        config = make_config(tmp_path, allow_fail_legs={"no_such_leg"})
        receipt, _code = verify.run_verification(config)
        assert receipt["ignored_waiver_requests"] == [
            {"leg": "no_such_leg", "reason": "unknown leg name"}
        ]


class TestProcessLeg:
    def test_worker_row_fails_clean_snapshot_passes(self, tmp_path):
        dirty = make_config(
            tmp_path,
            ps_output_text=(
                "  42 python -m app.data_fetch.script_worker --claim\n"
                " 1746649 /usr/bin/python3 -m uvicorn app.main:app\n"
            ),
        )
        receipt, code = verify.run_verification(dirty)
        proc_leg = leg(receipt, LEG_PROC)
        assert proc_leg["status"] == verify.FAIL
        assert proc_leg["detail"]["matching_processes"][0]["pid"] == "42"
        assert code == 1
        clean = make_config(tmp_path, ps_output_text="1746649 uvicorn app.main:app\n")
        receipt2, code2 = verify.run_verification(clean)
        assert leg(receipt2, LEG_PROC)["status"] == verify.PASS
        assert code2 == 3  # only NOT_RUN legs remain


class TestReceiptShapeAndCli:
    def test_receipt_has_section6_fields(self, tmp_path):
        receipt, _code = verify.run_verification(make_config(tmp_path))
        for key in (
            "case_id",
            "work_package",
            "dataset_task_script_ids",
            "repos",
            "dependency_image_config_versions",
            "environment",
            "scope",
            "commands_run",
            "start_utc",
            "end_utc",
            "legs",
            "failures",
            "skips_not_run",
            "reviewer",
        ):
            assert key in receipt
        assert receipt["case_id"] == "AC18"
        assert receipt["reviewer"]["verdict"] == "PENDING_REVIEWER"
        assert receipt["environment"]["credential_values_emitted"] is False

    def test_cli_json_output_and_exit_code(self, tmp_path, capsys):
        repo = build_repo(tmp_path)
        ps_file = tmp_path / "ps.txt"
        ps_file.write_text("1 systemd\n", encoding="utf-8")
        out = tmp_path / "nested" / "receipt.json"
        code = verify.main(
            [
                "--repo-root",
                str(repo),
                "--no-systemctl",
                "--ps-file",
                str(ps_file),
                "--skip-import-probe",
                "--opendata-root",
                str(tmp_path / "opendata"),
                "--json-output",
                str(out),
            ]
        )
        captured = capsys.readouterr()
        assert code == 3
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["exit_code"] == code
        assert {item["name"] for item in payload["legs"]} == {
            LEG_SDK,
            "no_collection_startup_hook",
            LEG_DSN,
            LEG_PROC,
            LEG_EGRESS,
            LEG_REVOKED,
        }
        assert "REMINDER: NOT_RUN legs keep AC18 open" in captured.out

    def test_cli_waiver_printed_and_sentinel_free(self, tmp_path, capsys):
        repo = build_repo(tmp_path, pyproject=SDK_PYPROJECT)
        (repo / "src" / "frontend" / "dist" / "assets" / "leak.js").write_text(
            f'"postgresql+psycopg://admin:{SENTINEL_PW}@db.corp:5432/prod"\n', encoding="utf-8"
        )
        ps_file = tmp_path / "ps.txt"
        ps_file.write_text("1 systemd\n", encoding="utf-8")
        out = tmp_path / "receipt.json"
        code = verify.main(
            [
                "--repo-root",
                str(repo),
                "--no-systemctl",
                "--ps-file",
                str(ps_file),
                "--skip-import-probe",
                "--allow-fail-leg",
                LEG_SDK,
                "--waiver-note",
                "documented pre-cutover waiver",
                "--json-output",
                str(out),
            ]
        )
        captured = capsys.readouterr()
        assert code == 1  # DSN leg still fails, cannot be hidden by the sdk waiver
        payload_text = out.read_text(encoding="utf-8")
        assert SENTINEL_PW not in payload_text + captured.out
        assert "WAIVER RECORDED" in captured.out
        assert "db_scheme_url" in payload_text  # pattern name IS reported

    def test_startup_hook_launch_line_fails_leg(self, tmp_path):
        repo = build_repo(tmp_path)
        (repo / "docker" / "entrypoint-dev.sh").write_text(
            "#!/bin/sh\npython scripts/run_akshare_scheduled_tasks.py --loop\n", encoding="utf-8"
        )
        receipt, code = verify.run_verification(make_config(tmp_path, repo_root=repo))
        hook_leg = leg(receipt, "no_collection_startup_hook")
        assert hook_leg["status"] == verify.FAIL
        assert hook_leg["detail"]["matches"][0]["matched_token"] == "run_akshare_scheduled_tasks"
        assert code == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
