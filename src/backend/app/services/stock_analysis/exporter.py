"""Render stock analysis reports to multiple export formats.

An export may carry the exact OpenData publication(s) its numbers came from. When
a report declares that provenance the exporter refuses to render an unbound
artifact: the pinned publication id, publication sequence, contract hash, content
hash, data window, and filters are validated and written into every format, so a
later reader can verify the identical vector instead of guessing at a snapshot.
A report with no declared OpenData provenance renders exactly as before.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from markdown_it import MarkdownIt

from app.services.research.canonical import content_hash
from app.services.stock_analysis.report_builder import COMPAT_REPORT_KEY
from app.services.stock_analysis.stock_daily_report_evidence import (
    StockDailyReportEvidenceError,
    StockDailyReportEvidenceVector,
)

UTC = timezone.utc
EXPORT_PROVENANCE_KEY: Final = "opendata_publication_manifest"
EXPORT_PUBLICATION_MANIFEST_VERSION: Final = "stock-analysis-export-publication-v1"
_STOCK_DAILY_PROVENANCE_PREFIX: Final = "opendata:stock_daily"

_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(
    r"(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\Z",
    re.ASCII,
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_FILTER_TEXT = re.compile(r"[A-Za-z0-9._:/+,-]{1,128}\Z", re.ASCII)

_MANIFEST_KEYS = frozenset(
    {"version", "owner_user_id", "publications", "binding", "manifest_sha256"}
)
_PUBLICATION_KEYS = frozenset(
    {
        "dataset_id",
        "source_id",
        "instrument_id",
        "market",
        "publication_id",
        "publication_sequence",
        "content_sha256",
        "contract_sha256",
        "window_start",
        "window_end",
        "filters",
    }
)
_BINDING_KEYS = frozenset(
    {"binding_hash", "manifest_sha256", "artifact_sha256", "artifact_size_bytes"}
)
_WINDOW_KEYS = frozenset({"start", "end"})


class StockAnalysisExportProvenanceError(ValueError):
    """Stable fail-closed error for an export's publication provenance."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def publication_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the canonical content hash of one export publication manifest."""
    return content_hash({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def build_export_publication_manifest(
    *,
    owner_user_id: str,
    evidence: StockDailyReportEvidenceVector | Mapping[str, Any],
    window: Mapping[str, Any],
    filters: Mapping[str, Any] | None = None,
    binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze one report's OpenData evidence vector into an exportable manifest.

    The vector is the only accepted source of publication facts: it is already
    validated and revalidated by the report evidence gate, so an export cannot
    name a publication the report never read.  The window and filters are pinned
    per dataset because they, not the publication id alone, decide which vector
    rows a reader must reproduce.
    """
    vector = (
        evidence
        if isinstance(evidence, StockDailyReportEvidenceVector)
        else _vector_from_json(evidence)
    )
    window_start, window_end = _validate_window(window)
    normalized_filters = _validate_filters(filters if filters is not None else {})
    publications: list[dict[str, Any]] = []
    for entry in vector.entries:
        publications.append(
            {
                "dataset_id": entry.dataset_id,
                "source_id": entry.source_id,
                "instrument_id": entry.instrument_id,
                "market": entry.market,
                "publication_id": entry.publication_id,
                "publication_sequence": entry.publication_sequence,
                "content_sha256": entry.content_sha256,
                "contract_sha256": entry.contract_sha256,
                "window_start": window_start,
                "window_end": window_end,
                "filters": normalized_filters,
            }
        )
    manifest: dict[str, Any] = {
        "version": EXPORT_PUBLICATION_MANIFEST_VERSION,
        "owner_user_id": _validate_text(owner_user_id, maximum=36),
        "publications": publications,
        "binding": None if binding is None else dict(binding),
    }
    manifest["manifest_sha256"] = publication_manifest_sha256(manifest)
    return validate_export_publication_manifest(manifest)


def _vector_from_json(payload: object) -> StockDailyReportEvidenceVector:
    """Parse the report evidence vector, surfacing one stable export error code."""
    try:
        return StockDailyReportEvidenceVector.from_json(payload)
    except StockDailyReportEvidenceError as exc:
        raise StockAnalysisExportProvenanceError(
            "stock_analysis_export_provenance_vector_invalid"
        ) from exc


def validate_export_publication_manifest(value: object) -> dict[str, Any]:
    """Return the normalized manifest, refusing any incomplete publication pin.

    Every pinned axis is required: a missing publication id, an unsealed
    sequence, a non-hash contract or content reference, or a window that cannot
    be parsed is a refusal rather than a guess.  The manifest hash is recomputed,
    so a silent edit of any pinned field is detected here.
    """
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_KEYS:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    if value["version"] != EXPORT_PUBLICATION_MANIFEST_VERSION:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    owner_user_id = _validate_text(value["owner_user_id"], maximum=36)
    raw_publications = value["publications"]
    if isinstance(raw_publications, (str, bytes)) or not isinstance(raw_publications, Sequence):
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    if not raw_publications:
        raise StockAnalysisExportProvenanceError(
            "stock_analysis_export_provenance_publications_missing"
        )
    publications = [_validate_publication(item) for item in raw_publications]
    identities = {(item["dataset_id"], item["publication_id"]) for item in publications}
    if len(identities) != len(publications):
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    normalized: dict[str, Any] = {
        "version": EXPORT_PUBLICATION_MANIFEST_VERSION,
        "owner_user_id": owner_user_id,
        "publications": publications,
        "binding": _validate_binding(value["binding"]),
    }
    if content_hash(normalized) != _validate_sha256(value["manifest_sha256"]):
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_hash_mismatch")
    normalized["manifest_sha256"] = value["manifest_sha256"]
    return normalized


def _validate_publication(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PUBLICATION_KEYS:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    publication_id = value["publication_id"]
    if not isinstance(publication_id, str) or not publication_id.strip():
        raise StockAnalysisExportProvenanceError(
            "stock_analysis_export_provenance_publication_missing"
        )
    if _PUBLICATION_ID.fullmatch(publication_id) is None:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    instrument_id = value["instrument_id"]
    if not isinstance(instrument_id, str) or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    if value["market"] != instrument_id[-2:]:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    sequence = value["publication_sequence"]
    if type(sequence) is not int or sequence < 1:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    window_start, window_end = _validate_window(
        {"start": value["window_start"], "end": value["window_end"]}
    )
    return {
        "dataset_id": _validate_identifier(value["dataset_id"]),
        "source_id": _validate_identifier(value["source_id"]),
        "instrument_id": instrument_id,
        "market": _validate_identifier(value["market"]),
        "publication_id": publication_id,
        "publication_sequence": sequence,
        "content_sha256": _validate_sha256(value["content_sha256"]),
        "contract_sha256": _validate_sha256(value["contract_sha256"]),
        "window_start": window_start,
        "window_end": window_end,
        "filters": _validate_filters(value["filters"]),
    }


def _validate_binding(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != _BINDING_KEYS:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    size = value["artifact_size_bytes"]
    if type(size) is not int or size < 1:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    return {
        "binding_hash": _validate_sha256(value["binding_hash"]),
        "manifest_sha256": _validate_sha256(value["manifest_sha256"]),
        "artifact_sha256": _validate_sha256(value["artifact_sha256"]),
        "artifact_size_bytes": size,
    }


def _validate_window(value: object) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != _WINDOW_KEYS:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_window_invalid")
    start = _parse_instant(value["start"])
    end = _parse_instant(value["end"])
    if start >= end:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_window_invalid")
    return start, end


def _parse_instant(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_window_missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise StockAnalysisExportProvenanceError(
            "stock_analysis_export_provenance_window_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_window_invalid")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_filters(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = _validate_identifier(raw_key)
        if key in normalized:
            raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
        normalized[key] = _validate_filter_value(raw_value)
    return dict(sorted(normalized.items()))


def _validate_filter_value(value: object) -> object:
    if value is None or value is True or value is False:
        return value
    if type(value) is int and not isinstance(value, bool):
        return value
    if isinstance(value, str) and _FILTER_TEXT.fullmatch(value) is not None:
        return value
    raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_filter_invalid")


def _validate_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    return value


def _validate_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or normalized != value:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    return normalized


def _validate_sha256(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_invalid")
    return value


class StockAnalysisExporter:
    """Export reports as Markdown, HTML, DOCX, and PDF."""

    STAGE_TITLES = {
        "market_report": "技术与市场分析",
        "news_report": "新闻与情绪",
        "fundamentals_report": "基本面分析",
        "sentiment_report": "社媒情绪",
        "investment_plan": "多空研究与投资计划",
        "trader_investment_plan": "交易员计划",
        "final_trade_decision": "风险评估与终审",
        "bull_researcher": "多头研究观点",
        "bear_researcher": "空头研究观点",
        "research_team_decision": "研究团队裁决",
        "risky_analyst": "激进风险分析",
        "safe_analyst": "稳健风险分析",
        "neutral_analyst": "中性风险分析",
        "risk_management_decision": "风险经理裁决",
    }

    CONTENT_TYPES = {
        "markdown": "text/markdown; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }

    EXTENSIONS = {
        "markdown": "md",
        "html": "html",
        "docx": "docx",
        "pdf": "pdf",
    }

    def render(
        self,
        report: dict[str, Any],
        export_format: str,
        *,
        provenance: object | None = None,
    ) -> bytes:
        if export_format == "markdown":
            return self.render_markdown(report, provenance=provenance).encode("utf-8")
        if export_format == "html":
            return self.render_html(report, provenance=provenance).encode("utf-8")
        if export_format == "docx":
            return self.render_docx(report, provenance=provenance)
        if export_format == "pdf":
            return self.render_pdf(report, provenance=provenance)
        raise ValueError(f"Unsupported export format: {export_format}")

    def render_markdown(self, report: dict[str, Any], *, provenance: object | None = None) -> str:
        meta = report.get("meta") or {}
        decision = report.get("decision") or {}
        manifest = self._publication_manifest(report, provenance=provenance)
        symbol = self._display_symbol(str(meta.get("symbol") or ""))
        compat = report.get(COMPAT_REPORT_KEY) or {}
        stage_order = list(self.STAGE_TITLES)
        lines = [
            f"# {symbol} 股票分析报告",
            "",
            f"分析日期: {meta.get('analysis_date', '')}",
            "分析师: market, fundamentals, news",
            f"研究深度: {meta.get('research_depth', '')}",
            "",
            "## 执行摘要",
            "",
            self._nest_markdown_headings(report.get("executive_summary") or "", level=3),
            "",
            "## 结构化决策摘要",
            "",
            f"最终建议: {decision.get('label', '观望')}",
            f"目标价位: {decision.get('target_price', 'N/A')}",
            f"置信度: {decision.get('confidence_score', 0.5)}",
            f"风险等级: {decision.get('risk_level', '中等')}",
            f"风险评分: {decision.get('risk_score', 0.5)}",
            "",
            self._nest_markdown_headings(decision.get("reasoning") or "", level=3),
            "",
        ]
        rendered = set()
        for key in stage_order:
            value = compat.get(key)
            if not value:
                continue
            rendered.add(key)
            lines.extend(
                [
                    f"## {self.STAGE_TITLES[key]}",
                    "",
                    self._nest_markdown_headings(value, level=3),
                    "",
                ]
            )
        for key, value in compat.items():
            if key in rendered or not value:
                continue
            lines.extend(
                [
                    f"## {key.replace('_', ' ').title()}",
                    "",
                    self._nest_markdown_headings(value, level=3),
                    "",
                ]
            )
        lines.extend(self._render_publication_markdown(manifest))
        lines.extend(
            [
                "## 数据质量、限制与免责声明",
                "",
                *(f"- {item}" for item in report.get("limitations") or []),
                "",
                str(report.get("disclaimer") or "本报告仅供研究参考，不构成投资建议。"),
                "",
            ]
        )
        return "\n".join(lines)

    def render_html(self, report: dict[str, Any], *, provenance: object | None = None) -> str:
        body = self._markdown_renderer().render(self.render_markdown(report, provenance=provenance))
        return (
            """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>股票分析报告</title>
  <style>
    @page { size: A4; margin: 18mm 15mm; }
    body { font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", sans-serif; font-size: 11pt; line-height: 1.75; margin: 0; color: #1f2937; word-break: break-word; }
    h1, h2, h3, h4, h5, h6 { color: #111827; page-break-after: avoid; }
    h1 { font-size: 24pt; border-bottom: 2px solid #2563eb; padding-bottom: 0.35rem; }
    h2 { font-size: 17pt; margin-top: 1.8rem; border-left: 4px solid #2563eb; padding-left: 0.6rem; }
    h3 { font-size: 14pt; margin-top: 1.4rem; }
    p { margin: 0.55rem 0; }
    ul, ol { padding-left: 1.6rem; }
    li { margin: 0.25rem 0; }
    table { width: 100%; border-collapse: collapse; margin: 1rem 0; page-break-inside: avoid; }
    th, td { border: 1px solid #d1d5db; padding: 0.45rem 0.6rem; text-align: left; vertical-align: top; }
    th { background: #eff6ff; font-weight: 600; }
    pre { background: #f3f4f6; border-radius: 6px; padding: 0.9rem; overflow-wrap: anywhere; white-space: pre-wrap; }
    code { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; }
    blockquote { border-left: 4px solid #93c5fd; color: #4b5563; margin: 1rem 0; padding-left: 1rem; }
    a { color: #2563eb; }
  </style>
</head>
<body>
"""
            + body
            + "\n</body>\n</html>\n"
        )

    def render_docx(self, report: dict[str, Any], *, provenance: object | None = None) -> bytes:
        document_xml = self._docx_document_xml(self.render_markdown(report, provenance=provenance))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
            )
            zf.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
            )
            zf.writestr("word/document.xml", document_xml)
        return output.getvalue()

    def render_pdf(self, report: dict[str, Any], *, provenance: object | None = None) -> bytes:
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise RuntimeError("PDF export requires the weasyprint dependency") from exc
        return HTML(string=self.render_html(report, provenance=provenance)).write_pdf()

    def build_file_name(self, report: dict[str, Any], export_format: str) -> str:
        meta = report.get("meta") or {}
        symbol = self._safe_file_part(
            self._display_symbol(str(meta.get("symbol") or "stock")),
            fallback="stock",
        )
        analysis_date = self._safe_file_part(
            str(meta.get("analysis_date") or "analysis"),
            fallback="analysis",
        )
        return f"{symbol}_分析报告_{analysis_date}.{self.EXTENSIONS[export_format]}"

    def save(
        self,
        content: bytes,
        *,
        user_id: str,
        report_id: str,
        file_name: str,
        provenance: object | None = None,
    ) -> Path:
        """Write one export below the owning user's directory only.

        An export that carries publication provenance must belong to the user the
        manifest pins; a cross-owner copy is refused before any byte is written.
        """
        normalized_owner = self._safe_export_owner(user_id)
        normalized_file_name = self._safe_export_file_name(file_name)
        if provenance is not None:
            manifest = validate_export_publication_manifest(provenance)
            if manifest["owner_user_id"] != normalized_owner:
                raise StockAnalysisExportProvenanceError(
                    "stock_analysis_export_provenance_owner_mismatch"
                )
        output_dir = Path("data") / "exports" / "stock-analysis" / normalized_owner / report_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / normalized_file_name
        output_path.write_bytes(content)
        return output_path

    @staticmethod
    def _safe_export_owner(value: object) -> str:
        """Reject a blank or padded owner so an export cannot be filed anonymously."""
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 36
            or "/" in value
            or "\\" in value
        ):
            raise StockAnalysisExportProvenanceError("stock_analysis_export_owner_invalid")
        return value

    @staticmethod
    def _safe_export_file_name(value: object) -> str:
        """Reject any file name that could escape the export directory."""
        if not isinstance(value, str) or not value:
            raise StockAnalysisExportProvenanceError("stock_analysis_export_file_name_invalid")
        if (
            value != Path(value).name
            or "\\" in value
            or "\x00" in value
            or value in {".", ".."}
            or len(value) > 255
        ):
            raise StockAnalysisExportProvenanceError("stock_analysis_export_file_name_invalid")
        return value

    def _publication_manifest(
        self,
        report: dict[str, Any],
        *,
        provenance: object | None,
    ) -> dict[str, Any] | None:
        """Resolve the report's pinned publication manifest or refuse the export.

        A legacy report declares no OpenData stock-daily source, so it renders
        exactly as before with no manifest section. Once a report does declare
        one, an absent or incomplete manifest is a refusal: an export must never
        present publication-backed numbers without naming the publications.
        """
        candidate = provenance if provenance is not None else report.get(EXPORT_PROVENANCE_KEY)
        if candidate is None:
            if self._declares_stock_daily_provenance(report):
                raise StockAnalysisExportProvenanceError("stock_analysis_export_provenance_missing")
            return None
        return validate_export_publication_manifest(candidate)

    @staticmethod
    def _declares_stock_daily_provenance(report: dict[str, Any]) -> bool:
        sources = report.get("data_sources")
        if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
            return False
        return any(
            isinstance(item, str) and item.startswith(_STOCK_DAILY_PROVENANCE_PREFIX)
            for item in sources
        )

    @staticmethod
    def _render_publication_markdown(manifest: dict[str, Any] | None) -> list[str]:
        if manifest is None:
            return []
        lines = [
            "## 数据发布绑定与可重放性",
            "",
            f"发布绑定清单哈希: `{manifest['manifest_sha256']}`",
            "",
        ]
        binding = manifest["binding"]
        if binding is not None:
            lines.extend(
                [
                    f"研究数据绑定: `{binding['binding_hash']}`",
                    f"绑定 Manifest 哈希: `{binding['manifest_sha256']}`",
                    (
                        f"绑定工件: `{binding['artifact_sha256']}` "
                        f"({binding['artifact_size_bytes']} bytes)"
                    ),
                    "",
                ]
            )
        for publication in manifest["publications"]:
            filters = ", ".join(
                f"{key}={'null' if value is None else value}"
                for key, value in publication["filters"].items()
            )
            lines.extend(
                [
                    (
                        f"### {publication['instrument_id']} · {publication['dataset_id']}"
                        f" · #{publication['publication_sequence']}"
                    ),
                    "",
                    f"- 发布标识 (publication_id): `{publication['publication_id']}`",
                    f"- 发布/可见序号 (sequence): {publication['publication_sequence']}",
                    f"- 契约哈希 (contract_sha256): `{publication['contract_sha256']}`",
                    f"- 内容哈希 (content_sha256): `{publication['content_sha256']}`",
                    (f"- 数据窗口: {publication['window_start']} .. {publication['window_end']}"),
                    (f"- 过滤条件: {filters}" if filters else "- 过滤条件: （无）"),
                    f"- 来源/市场: {publication['source_id']} / {publication['market']}",
                    "",
                ]
            )
        return lines

    def _docx_document_xml(self, markdown_text: str) -> str:
        paragraphs = []
        for line in markdown_text.splitlines():
            text = html.escape(line.strip())
            if not text:
                continue
            paragraphs.append(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
        return (
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
"""
            + "\n".join(paragraphs)
            + """
  </w:body>
</w:document>"""
        )

    @staticmethod
    def _safe_file_part(value: str, *, fallback: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
        return sanitized[:80] or fallback

    @staticmethod
    def _display_symbol(value: str) -> str:
        normalized = str(value or "").strip().upper()
        match = re.fullmatch(r"(\d{6})\.(?:SZ|SH)", normalized)
        if match:
            return match.group(1)
        return normalized or "stock"

    @staticmethod
    def _nest_markdown_headings(value: Any, *, level: int) -> str:
        """Nest an AI Markdown fragment under a report section without losing its structure."""
        text = str(value or "").replace("\r\n", "\n").strip()
        if not text:
            return ""
        heading_pattern = re.compile(r"^(#{1,6})(\s+)", re.MULTILINE)
        source_levels = [len(match.group(1)) for match in heading_pattern.finditer(text)]
        if not source_levels:
            return text
        source_base = min(source_levels)

        def replace_heading(match: re.Match[str]) -> str:
            source_level = len(match.group(1))
            nested_level = min(6, level + source_level - source_base)
            return f"{'#' * nested_level}{match.group(2)}"

        return heading_pattern.sub(replace_heading, text)

    @staticmethod
    def _markdown_renderer() -> MarkdownIt:
        """Return the safe CommonMark renderer used for HTML and PDF exports."""
        return MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
