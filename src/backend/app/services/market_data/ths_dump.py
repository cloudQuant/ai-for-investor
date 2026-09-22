"""THS 全市场 Parquet 受控回填（``market-dumps``）。

预签名 S3 链接通常 5 分钟有效，不可持久化缓存。全市场导出是受控批量回填
路径（P1），不作页面即时查询。下载后经 importer 进入规范层，遵守 197 的
发布事务与授权。

本模块提供确定性的 dump 契约（dump_id → 下载端点 → Parquet 字段 schema）
与受控下载骨架；真实回填与 importer 对接在 T6（G4）执行。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# THS 全市场导出端点（见 RESEARCH 5.11）。
THS_MARKET_DUMPS_ENDPOINT = "/api/dump/market-dumps"


@dataclass(frozen=True, slots=True)
class ThsDumpSpec:
    """一个受控全市场导出的契约描述。"""

    dump_id: str
    download_path: str
    description: str
    parquet_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.dump_id or not self.download_path:
            raise ValueError("dump_id and download_path must be non-blank")
        if not self.parquet_columns:
            raise ValueError("parquet_columns must be non-empty")


# 日 K Parquet 列（见 RESEARCH 5.11）。
_DAILY_K_COLUMNS = (
    "thscode",
    "currency",
    "interval",
    "adjusted",
    "date_ms",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
)

# 复权因子 Parquet 列。
_ADJUSTMENT_FACTORS_COLUMNS = (
    "thscode",
    "ticker",
    "ex_date_ms",
    "dividend_per_share",
    "per_share_bonus",
    "allotment_ratio",
    "allotment_price",
    "currency",
)

THS_DUMP_SPECS: Mapping[str, ThsDumpSpec] = MappingProxyType(
    {
        "a_share_daily_k_1d_none_10y": ThsDumpSpec(
            dump_id="a_share_daily_k_1d_none_10y",
            download_path="/api/dump/market-dumps/daily-k/download-url",
            description="10 年全量日 K",
            parquet_columns=_DAILY_K_COLUMNS,
        ),
        "a_share_daily_k_1d_none_10d": ThsDumpSpec(
            dump_id="a_share_daily_k_1d_none_10d",
            download_path="/api/dump/market-dumps/daily-k-10d/download-url",
            description="最近 10 交易日日 K",
            parquet_columns=_DAILY_K_COLUMNS,
        ),
        "a_share_adjustment_factors_event_none_all": ThsDumpSpec(
            dump_id="a_share_adjustment_factors_event_none_all",
            download_path="/api/dump/market-dumps/adjustment-factors/download-url",
            description="复权因子全量",
            parquet_columns=_ADJUSTMENT_FACTORS_COLUMNS,
        ),
    }
)


class ThsDumpError(RuntimeError):
    """全市场导出失败。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


def ths_dump_spec(dump_id: str) -> ThsDumpSpec:
    """按 dump_id 精确解析契约，绝不使用同形后备。"""
    if not isinstance(dump_id, str) or not dump_id.strip():
        raise ThsDumpError("THS_DUMP_ID_INVALID")
    spec = THS_DUMP_SPECS.get(dump_id.strip())
    if spec is None:
        raise ThsDumpError("THS_DUMP_UNREGISTERED")
    return spec


def parse_download_url(envelope_payload: Mapping[str, object]) -> str:
    """从 market-dumps 响应中解析预签名下载 URL（不持久化）。

    官方 download-url 响应为 ``data.presigned_url``（实测，见 RESEARCH 5.11 勘误），
    附带 ``presigned_url_expires_at`` 与 ``expires_in_seconds``（通常 300 = 5 分钟）。
    解析出 URL 后由调用方即时下载消费，绝不缓存链接。
    """
    data = envelope_payload.get("data")
    if isinstance(data, Mapping):
        url = data.get("presigned_url")
        if isinstance(url, str) and url:
            return url
    raise ThsDumpError("THS_DUMP_URL_MISSING")
