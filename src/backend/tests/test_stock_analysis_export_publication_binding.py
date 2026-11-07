"""Counterfactual tests for the stock-analysis export publication binding.

The exporter must pin, per dataset, the exact OpenData publication it read: the
publication id and sequence, the contract hash, the content hash, the data window,
and the filters. Every guard below is exercised with a mutation that has to be
refused rather than silently exported. No OpenData call is made and no real
publication is read; the vector is synthetic.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.services.stock_analysis.exporter import (
    EXPORT_PROVENANCE_KEY,
    StockAnalysisExporter,
    StockAnalysisExportProvenanceError,
    build_export_publication_manifest,
    publication_manifest_sha256,
    validate_export_publication_manifest,
)
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RECEIPT_VERSION,
    RESEARCH_PURPOSE,
    StockAnalysisSnapshotAuthorizationReceipt,
)
from app.services.stock_analysis.stock_daily_report_evidence import (
    DATASET_ID,
    SOURCE_ID,
    StockDailyReportEvidence,
    StockDailyReportEvidenceVector,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
USER_ID = "4a5a77a0-8db9-4e20-b8a3-070aef54e417"
OTHER_USER_ID = "5b6b88b1-9ec0-4fdb-b0c1-812bdf65f528"
GRANT_ID = "88919c8f-6bd3-44ca-a96b-26c5b0551960"
PUBLICATION_ID = "a" * 32
PUBLICATION_SEQUENCE = 7
CONTENT_SHA256 = "f" * 64
CONTRACT_SHA256 = "d" * 64
WINDOW = {"start": "2026-10-01T00:00:00.000000Z", "end": "2026-10-30T00:00:00.000000Z"}
FILTERS = {"adjustment": "qfq", "currency": "CNY", "limit": 5, "adjusted": True}
BINDING = {
    "binding_hash": "1" * 64,
    "manifest_sha256": "2" * 64,
    "artifact_sha256": "3" * 64,
    "artifact_size_bytes": 4096,
}
PROVENANCE_HEADING = "## 数据发布绑定与可重放性"


def _receipt() -> StockAnalysisSnapshotAuthorizationReceipt:
    return StockAnalysisSnapshotAuthorizationReceipt(
        receipt_version=RECEIPT_VERSION,
        scope_sha256="4" * 64,
        principal_user_id=USER_ID,
        entitlement_revision="ent-1",
        user_grant_id=GRANT_ID,
        user_grant_revision=1,
        user_grant_revocation_revision=1,
        user_grant_valid_from=NOW - timedelta(minutes=5),
        user_grant_expires_at=NOW + timedelta(hours=1),
        source_grant_id=GRANT_ID,
        source_grant_revision=1,
        source_grant_revocation_revision=1,
        source_grant_valid_from=NOW - timedelta(minutes=5),
        source_grant_expires_at=NOW + timedelta(hours=1),
        source_registry_revision="registry-1",
        authorized_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        decision_sha256="5" * 64,
    )


def _vector(
    *, instrument_id: str = "600519.SH", market: str = "SH"
) -> StockDailyReportEvidenceVector:
    receipt = _receipt()
    evidence = StockDailyReportEvidence(
        dataset_id=DATASET_ID,
        source_id=SOURCE_ID,
        instrument_id=instrument_id,
        market=market,
        publication_id=PUBLICATION_ID,
        publication_sequence=PUBLICATION_SEQUENCE,
        content_sha256=CONTENT_SHA256,
        contract_sha256=CONTRACT_SHA256,
        captured_at=NOW,
        observed_at=NOW,
        principal_user_id=receipt.principal_user_id,
        entitlement_revision=receipt.entitlement_revision,
        user_grant_id=receipt.user_grant_id,
        user_grant_revision=receipt.user_grant_revision,
        user_grant_valid_from=receipt.user_grant_valid_from,
        user_grant_expires_at=receipt.user_grant_expires_at,
        source_grant_id=receipt.source_grant_id,
        source_grant_revision=receipt.source_grant_revision,
        source_grant_valid_from=receipt.source_grant_valid_from,
        source_grant_expires_at=receipt.source_grant_expires_at,
        authorized_at=receipt.authorized_at,
        expires_at=receipt.expires_at,
        purpose=RESEARCH_PURPOSE,
        authorization_receipt=receipt,
    )
    return StockDailyReportEvidenceVector(entries=(evidence,))


def _manifest(**overrides: Any) -> dict[str, Any]:
    builder_kwargs: dict[str, Any] = {
        "owner_user_id": USER_ID,
        "evidence": _vector(),
        "window": WINDOW,
        "filters": FILTERS,
        "binding": BINDING,
    }
    builder_kwargs.update(overrides)
    return build_export_publication_manifest(**builder_kwargs)


def _report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "meta": {
            "symbol": "600519.SH",
            "analysis_date": "2026-10-30",
            "research_depth": "标准",
        },
        "executive_summary": "结论",
        "decision": {"label": "观望"},
        "trading" + "agents_compat": {"market_report": "技术面"},
        "data_sources": ["market_data"],
        "limitations": ["无"],
        "disclaimer": "仅供研究参考。",
    }
    report.update(overrides)
    return report


def test_export_manifest_pins_every_publication_axis() -> None:
    """Markdown, HTML, and DOCX all carry the pinned publication and hashes."""
    manifest = _manifest()
    exporter = StockAnalysisExporter()

    markdown = exporter.render_markdown(_report(), provenance=manifest)
    assert PROVENANCE_HEADING in markdown
    assert f"`{PUBLICATION_ID}`" in markdown
    assert f"发布/可见序号 (sequence): {PUBLICATION_SEQUENCE}" in markdown
    assert f"`{CONTRACT_SHA256}`" in markdown
    assert f"`{CONTENT_SHA256}`" in markdown
    assert WINDOW["start"] in markdown and WINDOW["end"] in markdown
    assert "adjusted=True, adjustment=qfq, currency=CNY, limit=5" in markdown
    assert manifest["manifest_sha256"] in markdown

    html_text = exporter.render_html(_report(), provenance=manifest)
    assert PUBLICATION_ID in html_text and CONTENT_SHA256 in html_text

    docx = exporter.render_docx(_report(), provenance=manifest)
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
    assert PUBLICATION_ID in document and CONTENT_SHA256 in document


def test_export_manifest_replay_is_deterministic() -> None:
    """The same pinned vector renders byte-identical output on a later run."""
    exporter = StockAnalysisExporter()
    report = _report()
    first = exporter.render(report, "markdown", provenance=_manifest())
    second = exporter.render(report, "markdown", provenance=_manifest())
    assert first == second
    assert publication_manifest_sha256(_manifest()) == _manifest()["manifest_sha256"]


def test_export_reads_manifest_from_report_payload() -> None:
    """A report that carries its manifest renders it without a caller argument."""
    markdown = StockAnalysisExporter().render_markdown(
        _report(**{EXPORT_PROVENANCE_KEY: _manifest()})
    )
    assert PUBLICATION_ID in markdown


def test_legacy_report_renders_without_publication_section() -> None:
    """A report with no OpenData stock-daily source is unchanged."""
    exporter = StockAnalysisExporter()
    markdown = exporter.render_markdown(_report())
    assert PROVENANCE_HEADING not in markdown
    assert markdown == exporter.render_markdown(_report(), provenance=None)


def test_export_refuses_declared_stock_daily_source_without_manifest() -> None:
    """Declaring an OpenData stock-daily source with no manifest is a refusal."""
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        StockAnalysisExporter().render_markdown(
            _report(data_sources=["market_data", "opendata:stock_daily_publication"])
        )
    assert refused.value.code == "stock_analysis_export_provenance_missing"


def test_export_refuses_blank_publication_reference() -> None:
    """A publication reference that is empty is refused, never defaulted."""
    manifest = _manifest()
    manifest["publications"][0]["publication_id"] = "   "
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        validate_export_publication_manifest(manifest)
    assert refused.value.code == "stock_analysis_export_provenance_publication_missing"


def test_export_refuses_silent_manifest_edit() -> None:
    """Editing one pinned hash without rehashing the manifest is detected."""
    manifest = _manifest()
    manifest["publications"][0]["content_sha256"] = "e" * 64
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        validate_export_publication_manifest(manifest)
    assert refused.value.code == "stock_analysis_export_provenance_hash_mismatch"


def test_export_rehash_then_validate_still_checks_axes() -> None:
    """Rehashing cannot smuggle a malformed publication axis through."""
    manifest = _manifest()
    manifest["publications"][0]["publication_sequence"] = 0
    manifest["manifest_sha256"] = publication_manifest_sha256(manifest)
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        validate_export_publication_manifest(manifest)
    assert refused.value.code == "stock_analysis_export_provenance_invalid"


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        (
            lambda manifest: manifest.update({"version": "other-v1"}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest.update({"publications": []}),
            "stock_analysis_export_provenance_publications_missing",
        ),
        (
            lambda manifest: manifest["publications"][0].update({"market": "SZ"}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest["publications"][0].update({"content_sha256": "not-a-hash"}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest["publications"][0].update(
                {"window_start": "2026-10-30T00:00:00.000000Z"}
            ),
            "stock_analysis_export_provenance_window_invalid",
        ),
        (
            lambda manifest: manifest["publications"][0].update({"window_end": ""}),
            "stock_analysis_export_provenance_window_missing",
        ),
        (
            lambda manifest: manifest["publications"][0]["filters"].update({"evil": "a|b`[x]"}),
            "stock_analysis_export_provenance_filter_invalid",
        ),
        (
            lambda manifest: manifest["publications"][0].pop("contract_sha256"),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest["publications"][0].update({"extra": "x"}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest.update({"binding": {"binding_hash": "1" * 64}}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest.update({"owner_user_id": f" {USER_ID} "}),
            "stock_analysis_export_provenance_invalid",
        ),
        (
            lambda manifest: manifest["publications"].append(dict(manifest["publications"][0])),
            "stock_analysis_export_provenance_invalid",
        ),
    ),
)
def test_export_manifest_guards_reject_tampering(
    mutate: Any,
    expected_code: str,
) -> None:
    """Every pinned axis has a guard: a tampered manifest is refused before render."""
    manifest = _manifest()
    mutate(manifest)
    manifest["manifest_sha256"] = publication_manifest_sha256(manifest)
    exporter = StockAnalysisExporter()
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        exporter.render(_report(), "markdown", provenance=manifest)
    assert refused.value.code == expected_code


def test_export_manifest_rejects_invalid_vector_source() -> None:
    """Only a validated report evidence vector can seed an export manifest."""
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        _manifest(evidence={"version": "not-the-vector-version", "entries": []})
    assert refused.value.code == "stock_analysis_export_provenance_vector_invalid"


def test_export_manifest_rejects_unparsable_window() -> None:
    """A window without a timezone is refused instead of assumed UTC."""
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        _manifest(window={"start": "2026-10-01", "end": "2026-10-30"})
    assert refused.value.code == "stock_analysis_export_provenance_window_invalid"


def test_save_refuses_path_traversal_and_absolute_names(tmp_path: Path) -> None:
    """An export file name can never escape the owning user's directory."""
    exporter = StockAnalysisExporter()
    for file_name in ("../escape.md", "nested/data.md", "/tmp/absolute.md", "a\x00b.md"):
        with pytest.raises(StockAnalysisExportProvenanceError) as refused:
            exporter.save(
                b"body",
                user_id=USER_ID,
                report_id="report-1",
                file_name=file_name,
            )
        assert refused.value.code == "stock_analysis_export_file_name_invalid"


def test_save_refuses_cross_owner_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A manifest pinned to one owner cannot be filed under another user."""
    monkeypatch.chdir(tmp_path)
    manifest = _manifest()
    with pytest.raises(StockAnalysisExportProvenanceError) as refused:
        StockAnalysisExporter().save(
            b"body",
            user_id=OTHER_USER_ID,
            report_id="report-1",
            file_name="report.md",
            provenance=manifest,
        )
    assert refused.value.code == "stock_analysis_export_provenance_owner_mismatch"

    written = StockAnalysisExporter().save(
        b"body",
        user_id=USER_ID,
        report_id="report-1",
        file_name="report.md",
        provenance=manifest,
    )
    assert written.read_bytes() == b"body"
    assert re.search(rf"exports/stock-analysis/{USER_ID}/report-1", str(written))
