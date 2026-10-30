"""Data collection for native stock analysis."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.schemas.stock_analysis import StockAnalysisSinaFzbSnapshotSelection
from app.services.market_instrument import MarketInstrumentService
from app.services.news_intelligence import get_news_intelligence_service
from app.services.stock_analysis.opendata_financial_archive import (
    OpenDataFinancialArchiveError,
    OpenDataFinancialArchiveReader,
)
from app.services.stock_analysis.opendata_sina_fzb_snapshot import (
    OpenDataSinaFzbSnapshotError,
    OpenDataSinaFzbSnapshotReader,
)

_SINA_FZB_SAFE_REASON_CODES = frozenset(
    {
        "OPENDATA_BASE_URL_INVALID",
        "OPENDATA_CREDENTIAL_INVALID",
        "allowed_hosts_invalid",
        "base_url_host_not_allowed",
        "base_url_insecure_transport",
        "base_url_invalid",
        "capture_entry_limit_exceeded",
        "capture_id_invalid",
        "configuration_invalid",
        "content_type_invalid",
        "credential_missing",
        "credential_reflected_in_response",
        "deadline_exceeded",
        "duplicate_business_key",
        "feature_disabled",
        "http_401_unauthorized",
        "http_403_forbidden",
        "http_404_not_found",
        "http_410_snapshot_expired",
        "http_413_too_large",
        "http_422_invalid_request",
        "http_429_rate_limited",
        "http_503",
        "http_error",
        "http_server_error",
        "instrument_id_invalid",
        "instrument_scope_mismatch",
        "publication_id_invalid",
        "reader_error",
        "record_business_key_invalid",
        "record_business_key_mismatch",
        "record_entries_invalid",
        "record_entry_invalid",
        "record_hash_invalid",
        "record_metadata_invalid",
        "record_observation_time_mismatch",
        "record_order_invalid",
        "record_ordinals_invalid",
        "record_payload_invalid",
        "record_payload_scope_mismatch",
        "record_payload_shape_invalid",
        "record_publication_invalid",
        "record_publication_mismatch",
        "record_scope_mismatch",
        "record_shape_invalid",
        "record_temporal_scope_invalid",
        "record_too_large",
        "records_page_count_invalid",
        "records_page_invalid",
        "records_page_meta_invalid",
        "records_page_meta_mismatch",
        "records_snapshot_mismatch",
        "response_json_invalid",
        "response_read_failed",
        "response_too_large",
        "selector_missing",
        "snapshot_contract_mismatch",
        "snapshot_cursor_repeated",
        "snapshot_empty",
        "snapshot_expiry_invalid",
        "snapshot_hash_invalid",
        "snapshot_incomplete",
        "snapshot_metadata_invalid",
        "snapshot_page_limit_exceeded",
        "snapshot_row_limit_exceeded",
        "snapshot_scope_mismatch",
        "snapshot_selection_mismatch",
        "snapshot_window_invalid",
        "timestamp_invalid",
        "total_response_too_large",
        "transport_error",
    }
)
_SINA_FZB_REASON_DESCRIPTIONS = {
    "OPENDATA_BASE_URL_INVALID": "OpenData 服务地址配置无效。",
    "OPENDATA_CREDENTIAL_INVALID": "OpenData consumer key 配置无效。",
    "allowed_hosts_invalid": "OpenData 服务主机允许列表配置无效。",
    "base_url_host_not_allowed": "OpenData 服务主机不在允许列表中。",
    "base_url_insecure_transport": "远程 OpenData 服务必须使用 HTTPS。",
    "base_url_invalid": "OpenData 服务地址配置无效。",
    "credential_missing": "OpenData consumer key 未配置。",
    "feature_disabled": "AFI 的 Sina FZB OpenData 读取功能未启用。",
    "http_401_unauthorized": "OpenData 拒绝了 consumer key（401），请检查密钥状态。",
    "http_403_forbidden": "OpenData 数据集或操作权限不足（403）。",
    "http_404_not_found": "指定的 OpenData publication 或资源不可用（404）。",
    "http_410_snapshot_expired": "OpenData snapshot 已过期（410）。",
    "http_429_rate_limited": "OpenData 请求达到限流上限（429）。",
    "http_503": "OpenData 服务暂时不可用（503）。",
    "http_server_error": "OpenData 服务返回了服务器错误。",
    "instrument_scope_mismatch": "选择的证券与当前分析对象不匹配。",
    "snapshot_empty": "指定的 OpenData snapshot 没有可读取记录。",
    "transport_error": "AFI 无法连接到 OpenData 服务。",
}
_SINA_FZB_GENERIC_FAILURE_DESCRIPTION = "OpenData 未能提供符合冻结合同的完整快照。"


class StockAnalysisDataCollector:
    """Collect current-project data used by the stock analysis pipeline."""

    _BULLISH_NEWS_TERMS = (
        "增长",
        "增持",
        "回购",
        "分红",
        "预增",
        "上调",
        "获批",
        "中标",
        "突破",
        "改善",
        "利好",
    )
    _BEARISH_NEWS_TERMS = (
        "下滑",
        "下降",
        "亏损",
        "减持",
        "处罚",
        "立案",
        "风险",
        "违约",
        "暴跌",
        "利空",
        "监管",
    )

    def __init__(
        self,
        db: AsyncSession,
        *,
        settings: Any | None = None,
        financial_archive_reader: OpenDataFinancialArchiveReader | None = None,
        sina_fzb_snapshot_reader: OpenDataSinaFzbSnapshotReader | None = None,
    ) -> None:
        self.db = db
        self.market_service = MarketInstrumentService()
        self._settings = settings
        self._financial_archive_reader = financial_archive_reader
        self._sina_fzb_snapshot_reader = sina_fzb_snapshot_reader

    async def collect(
        self,
        *,
        user_id: str,
        symbol: str,
        market_type: str,
        analysis_date: date,
        opendata_sina_fzb_snapshot: StockAnalysisSinaFzbSnapshotSelection | None = None,
    ) -> dict[str, Any]:
        market_payload = await self._collect_market(symbol=symbol, analysis_date=analysis_date)
        quote = self._build_quote(market_payload)
        info, peers = await self._collect_company_context(
            symbol=symbol,
            market_type=market_type,
            market_payload=market_payload,
        )
        history = market_payload.get("history") or {"rows": []}
        financials = await self._collect_financials(
            symbol=symbol,
            market_type=market_type,
            analysis_date=analysis_date,
            market_payload=market_payload,
            opendata_sina_fzb_snapshot=opendata_sina_fzb_snapshot,
        )
        technicals = {"factors": market_payload.get("indicators") or {}}
        news = await self._collect_news(user_id, symbol, market_type)

        missing_fields = [
            name
            for name, value in {
                "quote": quote,
                "info": info,
                "history": history.get("rows") if isinstance(history, dict) else None,
                "financials": self._has_financial_data(financials),
                "technicals": technicals,
            }.items()
            if value is False or not value
        ]
        degraded_reasons: list[str] = []
        if not self._has_financial_data(financials):
            degraded_reasons.append("财务数据为空")
            if isinstance(financials.get("raw_archive"), dict):
                degraded_reasons.append(
                    self._financial_archive_degradation_reason(financials["raw_archive"])
                )
            snapshot_evidence = financials.get("opendata_sina_fzb_snapshot")
            if isinstance(snapshot_evidence, dict):
                degraded_reasons.append(
                    "新浪 FZB 来源原生记录仅作证据引用，未进入标准化财务分析；"
                    f"状态：{snapshot_evidence.get('status', 'unavailable')}"
                )
                if (
                    opendata_sina_fzb_snapshot is not None
                    and snapshot_evidence.get("status") == "unavailable"
                ):
                    degraded_reasons.append(
                        self._sina_fzb_failure_degraded_reason(
                            snapshot_evidence.get("reason_code")
                        )
                    )
        if not news.get("items"):
            degraded_reasons.append("新闻数据为空")
        data_quality = {
            "status": "degraded" if missing_fields else "ok",
            "missing_fields": missing_fields,
            "degraded_reasons": degraded_reasons,
        }

        return {
            "symbol": symbol,
            "market_type": market_type,
            "analysis_date": analysis_date.isoformat(),
            "quote": quote,
            "info": info,
            "history": history,
            "financials": financials,
            "peers": peers,
            "technicals": technicals,
            "news": news,
            "data_quality": data_quality,
        }

    async def _collect_news(self, user_id: str, symbol: str, market_type: str) -> dict[str, Any]:
        local_news = {"items": [], "total": 0, "status": "degraded"}
        try:
            local_news = await asyncio.wait_for(
                get_news_intelligence_service(self.db).list_articles(user_id, ticker=symbol),
                timeout=10,
            )
            if not local_news.get("items"):
                normalized_symbol = self._cn_stock_code(symbol)
                if normalized_symbol != symbol.upper():
                    local_news = await asyncio.wait_for(
                        get_news_intelligence_service(self.db).list_articles(
                            user_id, ticker=normalized_symbol
                        ),
                        timeout=10,
                    )
        except Exception:
            pass

        if local_news.get("items") or not self._is_cn_stock(symbol, market_type):
            return local_news

        try:
            raw_news = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_cn_stock_news, self._cn_stock_code(symbol)),
                timeout=20,
            )
            items = self._normalize_cn_news(raw_news, symbol)
        except Exception:
            items = []
        if not items:
            return local_news
        return {
            "items": items,
            "total": len(items),
            "status": "ok",
            "provider": "akshare",
        }

    async def _collect_market(self, *, symbol: str, analysis_date: date) -> dict[str, Any]:
        end_date = analysis_date
        start_date = end_date - timedelta(days=365)
        try:
            return await asyncio.wait_for(
                self.market_service.lookup(
                    asset_type="stock",
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    period="daily",
                    # Legacy lookup is deliberately local-only. Provider I/O
                    # must use the v2 local-first path with durable receipts.
                    refresh_online=False,
                ),
                timeout=30,
            )
        except Exception:
            return {
                "symbol": symbol,
                "name": symbol,
                "provider": None,
                "snapshot": {},
                "history": {"rows": []},
                "indicators": {},
            }

    @staticmethod
    def _build_quote(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = payload.get("snapshot") or {}
        symbol = snapshot.get("symbol") or payload.get("symbol")
        return {
            "symbol": symbol,
            "name": snapshot.get("name") or payload.get("name") or symbol,
            "price": snapshot.get("price"),
            "previous_close": snapshot.get("previous_close"),
            "change": snapshot.get("change"),
            "change_pct": snapshot.get("change_pct"),
            "currency": "CNY",
            "provider": payload.get("provider"),
            "updated_at": snapshot.get("update_time"),
        }

    @staticmethod
    def _build_info(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = payload.get("snapshot") or {}
        symbol = snapshot.get("symbol") or payload.get("symbol")
        return {
            "symbol": symbol,
            "name": snapshot.get("name") or payload.get("name") or symbol,
            "asset_type": "stock",
            "exchange": StockAnalysisDataCollector._infer_exchange(str(symbol or "")),
            "country": "CN",
            "listing_currency": "CNY",
            "provider": payload.get("provider"),
        }

    async def _collect_company_context(
        self,
        *,
        symbol: str,
        market_type: str,
        market_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Enrich an explicit A-share analysis request with issuer and peer context."""
        info = self._build_info(market_payload)
        peers = {"items": [], "total": 0}
        if not self._is_cn_stock(symbol, market_type):
            return info, peers

        try:
            profile_frame = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_cn_company_profile, self._cn_xq_symbol(symbol)),
                timeout=20,
            )
        except Exception:
            return info, peers

        profile = self._frame_key_values(profile_frame)
        info = self._merge_cn_company_profile(info, profile)
        industry = self._profile_industry(profile)
        if not industry:
            return info, peers

        try:
            members_frame = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_cn_industry_members, industry),
                timeout=20,
            )
        except Exception:
            return info, peers
        items = self._normalize_cn_industry_peers(
            members_frame,
            symbol=symbol,
            industry=industry,
        )
        if not items:
            return info, peers
        return info, {"items": items, "total": len(items), "provider": "akshare"}

    async def _collect_financials(
        self,
        *,
        symbol: str,
        market_type: str,
        analysis_date: date,
        market_payload: dict[str, Any],
        opendata_sina_fzb_snapshot: StockAnalysisSinaFzbSnapshotSelection | None = None,
    ) -> dict[str, Any]:
        financials = self._build_financials(market_payload)
        active_settings = self._settings or get_settings()
        sina_snapshot_enabled = bool(
            getattr(active_settings, "STOCK_ANALYSIS_OPENDATA_SINA_FZB_SNAPSHOT_ENABLED", False)
        )
        if opendata_sina_fzb_snapshot is not None or (sina_snapshot_enabled and market_type == "A股"):
            return await self._collect_sina_fzb_snapshot_financials(
                financials=financials,
                symbol=symbol,
                market_type=market_type,
                selection=opendata_sina_fzb_snapshot,
                feature_enabled=sina_snapshot_enabled,
            )
        if not self._is_cn_stock(symbol, market_type):
            return financials

        active_settings = self._settings or get_settings()
        if bool(
            getattr(
                active_settings,
                "STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ENABLED",
                False,
            )
        ):
            instrument_id = self._opendata_instrument_id(symbol)
            try:
                if instrument_id is None:
                    raise OpenDataFinancialArchiveError("instrument_id_invalid")
                reader = self._financial_archive_reader
                if reader is None:
                    reader = OpenDataFinancialArchiveReader.from_environment(
                        allowed_hosts=getattr(
                            active_settings,
                            "STOCK_ANALYSIS_OPENDATA_FINANCIAL_ARCHIVE_ALLOWED_HOSTS",
                            "",
                        )
                    )
                archive_evidence = await reader.fetch_analysis_evidence(
                    instrument_id=instrument_id,
                    analysis_date=analysis_date,
                )
            except OpenDataFinancialArchiveError as exc:
                archive_evidence = self._empty_financial_archive_evidence(
                    symbol=symbol,
                    analysis_date=analysis_date,
                    reason_code=exc.code,
                )
            except Exception:
                # Never switch providers after the explicit OpenData selection.
                # Keep a stable, credential-free failure visible to the caller.
                archive_evidence = self._empty_financial_archive_evidence(
                    symbol=symbol,
                    analysis_date=analysis_date,
                    reason_code="reader_error",
                )
            financials.update(
                {
                    "annual": [],
                    "quarterly": [],
                    "provider": "opendata",
                    "raw_archive": archive_evidence,
                }
            )
            return financials

        try:
            abstract, indicators = await asyncio.wait_for(
                asyncio.to_thread(
                    self._fetch_cn_financial_frames,
                    self._cn_stock_code(symbol),
                    analysis_date.year - 2,
                ),
                timeout=30,
            )
            annual, quarterly = self._normalize_cn_financials(
                abstract,
                indicators,
                analysis_date=analysis_date,
            )
        except Exception:
            return financials

        if annual or quarterly:
            financials.update(
                {
                    "annual": annual,
                    "quarterly": quarterly,
                    "provider": "akshare",
                }
            )
        return financials

    async def _collect_sina_fzb_snapshot_financials(
        self,
        *,
        financials: dict[str, Any],
        symbol: str,
        market_type: str,
        selection: StockAnalysisSinaFzbSnapshotSelection | None,
        feature_enabled: bool,
    ) -> dict[str, Any]:
        """Read one caller-pinned source snapshot and retain only safe provenance."""
        # Source-native records are intentionally not normalized into annual or
        # quarterly metrics. Clearing those fields also prevents another
        # provider's financial values from appearing as if they came from this
        # explicit selection.
        financials.update(
            {
                "annual": [],
                "quarterly": [],
                "provider": "opendata",
            }
        )
        summary: dict[str, Any] = {
            "status": "unavailable",
            "source": "sina-fzb",
            "dataset_id": "sina_fzb_report_observations",
            "instrument_id": selection.instrument_id if selection is not None else None,
            "publication_id": selection.publication_id if selection is not None else None,
            "capture_id": selection.capture_id if selection is not None else None,
            "record_count": 0,
            "page_count": 0,
            "reason_code": None,
            "temporal_semantics": "none",
            "eligible_for_decision_or_backtest": False,
        }

        active_settings = self._settings or get_settings()

        if not feature_enabled:
            summary["reason_code"] = "feature_disabled"
            financials["opendata_sina_fzb_snapshot"] = summary
            return financials

        if selection is None:
            summary["reason_code"] = "selector_missing"
            financials["opendata_sina_fzb_snapshot"] = summary
            return financials

        expected_instrument_id = self._opendata_instrument_id(symbol)
        if (
            market_type != "A股"
            or expected_instrument_id is None
            or expected_instrument_id != selection.instrument_id
        ):
            summary["reason_code"] = "instrument_scope_mismatch"
            financials["opendata_sina_fzb_snapshot"] = summary
            return financials

        try:
            reader = self._sina_fzb_snapshot_reader
            if reader is None:
                reader = OpenDataSinaFzbSnapshotReader.from_environment(
                    allowed_hosts=getattr(
                        active_settings, "STOCK_ANALYSIS_OPENDATA_SINA_FZB_ALLOWED_HOSTS", ""
                    )
                )
            result = await reader.fetch_capture(
                instrument_id=selection.instrument_id,
                publication_id=selection.publication_id,
                capture_id=selection.capture_id,
            )
        except OpenDataSinaFzbSnapshotError as exc:
            summary["reason_code"] = self._safe_sina_fzb_reason_code(exc.code)
        except Exception:
            # Do not expose URLs, credentials, or response bodies in task/report
            # data and never switch providers after an explicit selection.
            summary["reason_code"] = "reader_error"
        else:
            snapshot = result.snapshot
            summary.update(
                {
                    "status": "ok" if result.records else "empty",
                    "snapshot_id": snapshot.get("snapshot_id"),
                    "publication_sequence": snapshot.get("sequence"),
                    "record_count": len(result.records),
                    "page_count": result.page_count,
                    "selection_sha256": snapshot.get("selection_sha256"),
                    "content_sha256": snapshot.get("content_sha256"),
                    "contract_sha256": snapshot.get("contract_sha256"),
                    "as_of": snapshot.get("as_of"),
                    "expires_at": snapshot.get("expires_at"),
                    "completeness": result.completeness,
                    "historical_as_of_status": result.historical_as_of_status,
                }
            )
            if not result.records:
                summary["reason_code"] = "snapshot_empty"

        financials["opendata_sina_fzb_snapshot"] = summary
        return financials

    @staticmethod
    def _safe_sina_fzb_reason_code(reason_code: object) -> str:
        """Return a known stable error code without exposing arbitrary exception data."""
        if isinstance(reason_code, str) and reason_code in _SINA_FZB_SAFE_REASON_CODES:
            return reason_code
        return "reader_error"

    @classmethod
    def _sina_fzb_failure_degraded_reason(cls, reason_code: object) -> str:
        """Build a credential-free explanation for an explicit failed snapshot read."""
        safe_code = cls._safe_sina_fzb_reason_code(reason_code)
        description = _SINA_FZB_REASON_DESCRIPTIONS.get(
            safe_code, _SINA_FZB_GENERIC_FAILURE_DESCRIPTION
        )
        return f"新浪 FZB OpenData 快照读取失败（{safe_code}）：{description}"

    @classmethod
    def _opendata_instrument_id(cls, symbol: str) -> str | None:
        """Return a conservatively resolved suffix-form A-share identifier."""
        normalized = symbol.strip().upper()
        explicit_exchange: str | None = None
        if "." in normalized:
            if normalized.count(".") != 1:
                return None
            code, explicit_exchange = normalized.split(".", 1)
            if explicit_exchange not in {"SH", "SZ", "BJ"}:
                return None
        elif normalized.startswith(("SH", "SZ", "BJ")):
            explicit_exchange, code = normalized[:2], normalized[2:]
        else:
            code = normalized

        if re.fullmatch(r"[0-9]{6}", code, re.ASCII) is None:
            return None

        if code.startswith("6"):
            exchange = "SH"
        elif code.startswith(("0", "3")):
            exchange = "SZ"
        elif code.startswith("920") or code.startswith(("43", "83", "87", "88")):
            exchange = "BJ"
        else:
            # This excludes B-share and ambiguous 9/2-prefixed symbols. The
            # older generic exchange guesser remains for legacy display paths.
            return None

        if explicit_exchange is not None and explicit_exchange != exchange:
            return None
        return f"{code}.{exchange}"

    @classmethod
    def _empty_financial_archive_evidence(
        cls,
        *,
        symbol: str,
        analysis_date: date,
        reason_code: str,
    ) -> dict[str, Any]:
        start_period = date(max(1, analysis_date.year - 2), 1, 1)
        instrument_id = cls._opendata_instrument_id(symbol)
        return {
            "source": "opendata",
            "source_id": "ths_fuyao",
            "instrument_id": instrument_id,
            "status": "unavailable",
            "requested_window": {
                "start_report_period": start_period.isoformat(),
                "end_report_period": analysis_date.isoformat(),
            },
            "queries": [
                {
                    "statement_type": statement_type,
                    "periodicity": periodicity,
                    "status": "failed",
                    "record_count": 0,
                    "reason_code": reason_code,
                }
                for statement_type in ("income", "balance", "cashflow")
                for periodicity in ("annual", "quarterly")
            ],
            "records": [],
            "single_page_limit": 199,
            "pagination_supported": False,
            "future_disclosure_record_count": 0,
            "historical_as_of_status": "unavailable",
            "analysis_date_filtering": "report_period_only",
            "completeness": "unknown",
            "point_in_time_reconstruction": "unavailable",
            "period_amount_semantics": "unknown",
            "provenance_status": "incomplete",
            "observation_time_semantics": "deduplicated_observation_timestamp_not_capture_time",
            "normalization_status": "unreviewed",
            "eligible_for_decision_or_backtest": False,
        }

    @staticmethod
    def _financial_archive_degradation_reason(archive: dict[str, Any]) -> str:
        status = archive.get("status")
        raw_only_context = (
            "指标、单位和季度语义未审核，provenance不完整，"
            "观察时间不是采集时间，PIT不可用"
        )
        future_count = archive.get("future_disclosure_record_count")
        future_disclosure_note = (
            f"；{future_count}条记录披露日晚于分析日，不能用于历史时点分析"
            if isinstance(future_count, int) and future_count > 0
            else ""
        )
        if status == "observed":
            return (
                f"OpenData财报仅保留为来源原生证据；{raw_only_context}"
                f"{future_disclosure_note}"
            )
        if status == "empty":
            return (
                "OpenData财报归档请求成功但未返回记录，覆盖完整性仍未知；"
                f"{raw_only_context}{future_disclosure_note}"
            )
        reason_codes = sorted(
            {
                str(query.get("reason_code"))
                for query in archive.get("queries", [])
                if isinstance(query, dict) and query.get("reason_code")
            }
        )
        if reason_codes:
            return (
                f"OpenData财报归档不可完整读取；{raw_only_context}；"
                f"原因代码：{', '.join(reason_codes)}{future_disclosure_note}"
            )
        return (
            f"OpenData财报归档不可用；来源和覆盖完整性未验证；"
            f"{raw_only_context}{future_disclosure_note}"
        )

    @staticmethod
    def _build_financials(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = payload.get("snapshot") or {}
        valuation = {
            key: snapshot.get(key)
            for key in ("market_cap", "float_market_cap", "pe", "pb", "turnover")
            if snapshot.get(key) is not None
        }
        return {
            "symbol": payload.get("symbol"),
            "annual": [],
            "quarterly": [],
            "valuation": valuation,
            "provider": payload.get("provider"),
        }

    @staticmethod
    def _is_cn_stock(symbol: str, market_type: str) -> bool:
        return market_type == "A股" and bool(
            re.fullmatch(r"\d{6}", StockAnalysisDataCollector._cn_stock_code(symbol))
        )

    @staticmethod
    def _cn_stock_code(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if "." in normalized:
            normalized = normalized.split(".", 1)[0]
        if normalized.startswith(("SH", "SZ", "BJ")):
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _fetch_cn_financial_frames(symbol: str, start_year: int) -> tuple[Any, Any]:
        import akshare as ak

        return (
            ak.stock_financial_abstract(symbol=symbol),
            ak.stock_financial_analysis_indicator(symbol=symbol, start_year=str(start_year)),
        )

    @staticmethod
    def _fetch_cn_stock_news(symbol: str) -> Any:
        import akshare as ak

        return ak.stock_news_em(symbol=symbol)

    @staticmethod
    def _fetch_cn_company_profile(symbol: str) -> Any:
        import akshare as ak

        return ak.stock_individual_basic_info_xq(symbol=symbol)

    @staticmethod
    def _fetch_cn_industry_members(industry: str) -> Any:
        import akshare as ak

        return ak.stock_board_industry_cons_em(symbol=industry)

    @classmethod
    def _normalize_cn_financials(
        cls,
        abstract: Any,
        indicators: Any,
        *,
        analysis_date: date,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        abstract_rows = cls._frame_rows(abstract)
        if not abstract_rows:
            return [], []

        date_columns = sorted(
            {
                report_date
                for row in abstract_rows
                for column in row
                if (report_date := cls._report_date(column)) is not None
                and report_date <= analysis_date.isoformat()
            }
        )
        metric_candidates = {
            "revenue": ("营业总收入", "营业收入"),
            "net_income": ("归母净利润", "净利润"),
            "eps": ("基本每股收益", "摊薄每股收益"),
            "roe": ("净资产收益率(ROE)", "净资产收益率"),
        }
        metric_rows: dict[str, dict[str, Any]] = {}
        for field, candidates in metric_candidates.items():
            for candidate in candidates:
                matched = next(
                    (
                        row
                        for row in abstract_rows
                        if str(row.get("指标") or "").strip() == candidate
                    ),
                    None,
                )
                if matched is not None:
                    metric_rows[field] = matched
                    break

        growth_by_date: dict[str, dict[str, float]] = {}
        for row in cls._frame_rows(indicators):
            report_date = cls._report_date(row.get("日期"))
            if report_date is None or report_date > analysis_date.isoformat():
                continue
            growth = {
                field: value
                for field, column in {
                    "revenue_growth": "主营业务收入增长率(%)",
                    "profit_growth": "净利润增长率(%)",
                }.items()
                if (value := cls._number(row.get(column))) is not None
            }
            if growth:
                growth_by_date[report_date] = growth

        records: list[dict[str, Any]] = []
        for report_date in date_columns:
            compact_date = report_date.replace("-", "")
            record: dict[str, Any] = {"report_date": report_date}
            for field, row in metric_rows.items():
                if (value := cls._number(row.get(compact_date))) is not None:
                    record[field] = value
            record.update(growth_by_date.get(report_date, {}))
            if len(record) > 1:
                records.append(record)

        annual = [record for record in records if record["report_date"].endswith("-12-31")][-2:]
        quarterly = [record for record in records if not record["report_date"].endswith("-12-31")][
            -4:
        ]
        return annual, quarterly

    @classmethod
    def _normalize_cn_news(cls, raw_news: Any, symbol: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in cls._frame_rows(raw_news)[:20]:
            headline = str(row.get("新闻标题") or "").strip()
            if not headline:
                continue
            content = str(row.get("新闻内容") or "").strip()
            sentiment = cls._classify_cn_news_sentiment(f"{headline} {content}")
            items.append(
                {
                    "headline": headline,
                    "summary": content,
                    "content": content,
                    "published_at": str(row.get("发布时间") or "").strip() or None,
                    "source": str(row.get("文章来源") or "AkShare").strip() or "AkShare",
                    "url": str(row.get("新闻链接") or "").strip(),
                    "tickers": [symbol],
                    "sentiment": sentiment,
                    "impact": "MEDIUM" if sentiment != "UNKNOWN" else "UNKNOWN",
                    "threat": "MEDIUM" if sentiment == "BEARISH" else "UNKNOWN",
                    "status": "ok",
                    "source_flag": "akshare",
                }
            )
        return items

    @classmethod
    def _classify_cn_news_sentiment(cls, text: str) -> str:
        """Classify only supported directional evidence; unknown is not neutral evidence."""
        normalized = text.strip()
        bullish = sum(term in normalized for term in cls._BULLISH_NEWS_TERMS)
        bearish = sum(term in normalized for term in cls._BEARISH_NEWS_TERMS)
        if bullish > bearish and bullish:
            return "BULLISH"
        if bearish > bullish and bearish:
            return "BEARISH"
        return "UNKNOWN"

    @staticmethod
    def _frame_key_values(frame: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for row in StockAnalysisDataCollector._frame_rows(frame):
            key = str(row.get("item") or "").strip()
            if key:
                values[key] = row.get("value")
        return values

    @classmethod
    def _merge_cn_company_profile(
        cls, info: dict[str, Any], profile: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(info)
        name = cls._text(profile.get("org_short_name_cn")) or cls._text(profile.get("org_name_cn"))
        description = cls._text(profile.get("main_operation_business")) or cls._text(
            profile.get("org_cn_introduction")
        )
        industry = cls._profile_industry(profile)
        if name:
            merged["name"] = name
        if description:
            merged["description"] = description
        if industry:
            merged["industry"] = industry
            merged["sector"] = cls._cn_sector(industry)
        if name or description or industry:
            merged["company_profile_provider"] = "akshare.xueqiu"
        return merged

    @classmethod
    def _normalize_cn_industry_peers(
        cls, frame: Any, *, symbol: str, industry: str
    ) -> list[dict[str, Any]]:
        requested_code = cls._cn_stock_code(symbol)
        items: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for row in cls._frame_rows(frame):
            code = cls._cn_stock_code(str(row.get("代码") or row.get("symbol") or ""))
            name = cls._text(row.get("名称") or row.get("name"))
            if (
                not re.fullmatch(r"\d{6}", code)
                or code == requested_code
                or code in seen_codes
                or not name
            ):
                continue
            seen_codes.add(code)
            items.append(
                {
                    "symbol": cls._cn_stock_symbol(code),
                    "name": name,
                    "industry": industry,
                }
            )
            if len(items) == 3:
                break
        return items

    @staticmethod
    def _frame_rows(frame: Any) -> list[dict[str, Any]]:
        try:
            rows = frame.to_dict(orient="records")
        except (AttributeError, TypeError, ValueError):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _profile_industry(cls, profile: dict[str, Any]) -> str | None:
        value = profile.get("affiliate_industry")
        if isinstance(value, dict):
            return cls._text(value.get("ind_name") or value.get("name"))
        text = cls._text(value)
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            return cls._text(parsed.get("ind_name") or parsed.get("name"))
        return text

    @staticmethod
    def _cn_sector(industry: str) -> str:
        return "金融业" if "银行" in industry else industry

    @classmethod
    def _cn_xq_symbol(cls, symbol: str) -> str:
        code = cls._cn_stock_code(symbol)
        exchange = cls._infer_exchange(code)
        return f"{exchange}{code}" if exchange else code

    @classmethod
    def _cn_stock_symbol(cls, code: str) -> str:
        exchange = cls._infer_exchange(code)
        return f"{code}.{exchange}" if exchange else code

    @staticmethod
    def _report_date(value: Any) -> str | None:
        digits = re.sub(r"\D", "", str(value or ""))
        if len(digits) != 8:
            return None
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None

    @staticmethod
    def _has_financial_data(financials: dict[str, Any]) -> bool:
        return bool(financials.get("annual") or financials.get("quarterly"))

    @staticmethod
    def _infer_exchange(symbol: str) -> str | None:
        code = symbol.strip().upper()
        if "." in code:
            code = code.split(".", 1)[0]
        if code.startswith(("6", "9")):
            return "SH"
        if code.startswith(("0", "2", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return None
