# 迭代 198：验收文档

> 本文是后续验收规范，不是实现验收报告。全部运行用例初始状态为 `NOT_RUN`。
> 本次仅做文档一致性检查；没有请求 THS API、修改数据库或执行产品代码测试。

## 1. 状态与门禁

| 状态 | 含义 |
| --- | --- |
| PASS | 在本次冻结代码/配置/数据上执行，断言与证据都满足 |
| FAIL | 已执行且违反合同 |
| BLOCKED | 缺 THS 权限、环境、有效数据或前置；写清具体缺项 |
| NOT_RUN | 没有执行；不能被合并统计为通过 |

| 门 | 范围 | 通过要求 |
| --- | --- | --- |
| G0 | 基线冻结 | THS API Key、接口契约、复权 golden 对照、能力矩阵、许可条款 |
| G1 | 确定性正确性 | 信封归一化、错误码映射、复权/窗口/身份、限流/熔断契约 |
| G2 | 真实应用与本地持久化 | 隔离数据库 + THS adapter + 197 闭环，二次复用、重启恢复 |
| G3 | 真实来源 | 真实 THS API 取数闭环，A 股主源、财务/除复权/日历/检索 |
| G4 | 容量、迁移与灰度 | 限流恢复、回滚、全市场导出、灰度观察 |

完整结项：所有 P0 对应 G1—G4 通过，`FAIL=0/BLOCKED=0/NOT_RUN=0`。

## 2. 验收环境与证据包

- 写入/故障注入/迁移用隔离数据库/对象目录。
- G1 阻断外网，THS 响应以明确 fixture 提供；G2 用真实候选 API + 至少两个 worker；G3 用获准的真实 THS endpoint，不打印 API Key。
- 证据保存到 `docs/iterations/迭代198-同花顺金融数据API接入/evidence/<run-id>/`，含 manifest、capability-matrix、query-and-provider-trace、storage-receipts、result.json 等（格式沿用 197）。

## 3. 核心功能用例

### 3.1 信封、错误码与鉴权

| ID / 门 | 场景 | 必须断言 |
| --- | --- | --- |
| AC-01 / G1 | fixture：`code=0` 信封，含 `data.item` | 观察正确归一化；`request_id` 进来源证据 |
| AC-02 / G1 | fixture：`code=2001`/`2003` | 不可重试错误，立即失败，脱敏 |
| AC-03 / G1 | fixture：`code=3001`/`3002`/`3004` | 映射 EMPTY_CONFIRMED/DATA_NOT_READY/UNSUPPORTED_IDENTITY |
| AC-04 / G1 | fixture：`code=4001` 与 HTTP 429，**分「携带/不携带 `Retry-After`」两个分支** | 都按限流；携带时遵守 `Retry-After`，不携带时按指数退避（官方未承诺该头，客户端不得依赖其存在）；退避+熔断 |
| AC-05 / G1 | fixture：`code=5001`/`5002`/`5003` | 暂时性错误，可限次重试 |
| AC-06 / G1 | fixture：`code=1001`—`1004` | 请求变换层前置校验，不发送上游（含 100 token 批量上限与 10 年窗口的本地拦截） |
| AC-07 / G1 | 未配置 API Key | `THS_AUTH_UNAVAILABLE`，失败关闭 |
| AC-08 / G1 | 任意异常路径 | API Key 明文不出现在日志/异常/响应 |
| AC-23 / G1 | fixture：超时注入、请求取消、超限响应体 | 单请求 20s 超时生效；取消传播；响应体超限拒绝且不 OOM（NFR-01） |

### 3.2 复权、窗口与身份

| ID / 门 | 场景 | 必须断言 |
| --- | --- | --- |
| AC-09 / G0,G3 | `600519.SH` 对 `forward` 与 AkShare `qfq` 做 golden 对照（**真实数据，非 fixture**——官方已明确 forward=前复权，待核实的仅剩复权基准锚定） | 复权基准一致才等价；不一致则独立 axis，不混拼 |
| AC-10 / G1 | 历史窗口 > 10 年 | 自动切块，每块 ≤ 10 年；`code=1003` 不误判为缺失 |
| AC-11 / G1 | 财务 `period`/`fiscal_period` 多期 | 元数据保留；`null` 透传不补零 |
| AC-12 / G1 | 除复权事件 `ex_date_ms` | 时间语义正确，降序保留，事件类型隐式区分 |
| AC-13 / G1 | 标的检索 `q`/`asset_type`/`exchange` | 中文名解析正确，`thscode` 完整 |
| AC-14 / G1 | 分钟频请求 | `UNSUPPORTED`，不伪造 |

### 3.3 主源与闭环

| ID / 门 | 场景 | 必须断言 |
| --- | --- | --- |
| AC-15 / G2,G3 | A 股日线走 THS 主源 | source 标识 THS；本地满足时 THS 调用=0 |
| AC-16 / G2,G3 | THS 失败回退 AkShare（等价时） | 路由遵守 policy；来源保留；主备皆败时页面给出可解释原因码，不静默空白 |
| AC-17 / G2 | THS 首次取数 → 落库 → 重查 100 次 + 重启 | 后续网络调用=0，行可读回 |
| AC-18 / G2,G3 | 财务/除复权/日历/检索真实取数 | 结构化字段可解析，`reference_series` 落库 |
| AC-24 / G2,G3 | 前端来源标签与失败状态 | 来源标识 THS 有中英文标签；限流/权限失败、主备皆败终态有中英文标签（NFR-06） |
| AC-25 / G2,G3 | 审计链路检索 | 按 `request_id` 可检索到完整调用链（路由 ID、错误码、限流/权限事件）；日志不含 API Key 明文（FR-19） |

### 3.4 全市场导出与运维

| ID / 门 | 场景 | 必须断言 |
| --- | --- | --- |
| AC-19 / G4 | `market-dumps` 预签名链接下载 | 5 分钟有效期内完成；不持久化链接 |
| AC-20 / G4 | 全市场 Parquet importer | 进规范层，遵守发布事务与授权 |
| AC-21 / G4 | 关闭 `MARKET_DATA_THS_ENABLED`（及撤销任一激活链下层记录，见 DESIGN D7） | 回退 AkShare，THS 数据保留可读 |
| AC-22 / G4 | 限流/权限失败恢复 | 熔断恢复，本地数据仍可读 |
| AC-26 / G4 | 多标的批量补齐容量场景（如 ≥300 只 A 股日线缺口） | 快照类按 100 token 切批；历史类逐标的请求；在限流预算（退避+熔断）内完成且无 429 风暴；中断可恢复（NFR-02/FR-09） |

## 4. 真实资产验收账本

| 覆盖项 | 标的 | 真实源/kind | 首次取数落库 | 重启复用 | 初始状态 |
| --- | --- | --- | --- | --- | --- |
| THS-STOCK-DAILY | G0 冻结 | THS 1d bars | 待执行 | 待执行 | NOT_RUN |
| THS-FINANCIALS | G0 冻结 | 利润表/资产负债表/现金流 | 待执行 | 待执行 | NOT_RUN |
| THS-ADJUSTMENT | G0 冻结 | 复权事件流 | 待执行 | 待执行 | NOT_RUN |
| THS-CALENDAR | G0 冻结 | 交易日历 | 待执行 | 待执行 | NOT_RUN |
| THS-TICKER | G0 冻结 | 检索/列表 | 待执行 | 待执行 | NOT_RUN |
| THS-INDEX | G0 冻结 | 指数成分股 | 待执行 | 待执行 | NOT_RUN |
| THS-DUMP | G0 冻结 | 全市场 Parquet | 待执行 | 待执行 | NOT_RUN |

## 5. 需求—设计—验收追踪

| 需求 | 设计位置 | 具名验收 |
| --- | --- | --- |
| FR-01 | D1/D2 | AC-01, AC-15 |
| FR-02 | D3.2 | AC-07, AC-08 |
| FR-03 | D1/D3 | AC-01 |
| FR-04 | D3.3 | AC-02, AC-03, AC-05, AC-06 |
| FR-05 | D3.3 | AC-04 |
| FR-06 | D4 | AC-15, AC-16 |
| FR-07 | D2.3 | AC-09 |
| FR-08 | D2 | AC-14 |
| FR-09 | D2.4 | AC-10, AC-26 |
| FR-10 | D5 | AC-11, AC-18 |
| FR-11 | D5 | AC-12, AC-18 |
| FR-12 | D5 | AC-18 |
| FR-13 | D2/D5 | AC-13, AC-18 |
| FR-14 | D5 | AC-18 |
| FR-15 | D5 | -（P1） |
| FR-16 | D6 | AC-19, AC-20 |
| FR-17 | D4/DATA_SCOPE | AC-18 |
| FR-18 | D1/D5 | AC-17 |
| FR-19 | D3 | AC-08, AC-25 |
| FR-20 | D7 | AC-21, AC-22, AC-24 |
| NFR-01 | D3.1 | AC-23 |
| NFR-02 | D3.3 | AC-04, AC-26 |
| NFR-03 | D5 | AC-17 |
| NFR-04 | D3.2 | AC-08 |
| NFR-05 | D1 | -（复用 197，本迭代目标零 schema 变更；G4 验证） |
| NFR-06 | D7 | AC-24 |

## 6. 后续执行命令合同

这些是后续开发/验收命令模板，本次未执行。复用 197 的测试入口，THS 相关测试集中在 `tests/market_data_platform/test_ths_*`。

```bash
cd /Users/yunjinqi/Downloads/backtrader_web/src/backend
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/market_data_platform/test_ths_provider.py tests/market_data_platform/test_ths_contracts.py
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m ruff check app/services/market_data tests/market_data_platform/test_ths_provider.py
```

验收驱动脚本（沿用 197 约定）须提供 `--mode offline|integration|live`、`--case`、`--asset-type`、`--output`、`--dry-run`；live 检查 THS API Key 环境配置，缺配置退出 `BLOCKED`。返回码：0=PASS，1=FAIL，2=BLOCKED，3=未完整执行。

## 7. 文档检查（本次交付）

检查七份文档均存在、Markdown 内部引用可解析、FR/NFR/MIG 在追踪矩阵无遗漏、AC-01—AC-26 定义唯一、DATA_SCOPE 覆盖 THS 各数据域、所有运行状态保留 NOT_RUN，以及 Git 改动只包含本迭代文档。该检查没有推导产品 PASS 的权力。

**门—任务对齐**：G0 由 T0 完成（含 AC-09 golden 对照）；G1 由 T1/T2 的 fixture 测试覆盖（AC-01—AC-08、AC-10—AC-14、AC-23）；G2/G3 由 T3/T4 实现并在 T6 执行（AC-15—AC-18、AC-24、AC-25）；G4 由 T6 执行（AC-19—AC-22、AC-26）。
