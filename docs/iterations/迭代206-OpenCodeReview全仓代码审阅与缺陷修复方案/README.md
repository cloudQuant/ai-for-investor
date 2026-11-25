# 迭代206：OpenCodeReview 全仓代码审阅与缺陷修复方案

> 编制日期：2026-11-20（Asia/Shanghai）  
> 审阅基线：`dev` @ `5b9a3a280`（含迭代205收口合并 `efb316162` 及 `00c762d80..5b9a3a280` 全部集成提交）  
> 状态：**COMPLETED（44 / 44 已闭环，见 [TODO.md](TODO.md)）**  
> 证据口径：**E1 = 本机命令直接复现并保留输出**；**E2 = 源码与调用链静态确认**；**E3 = 需在 MySQL/PostgreSQL/生产或受控集成环境动态复验**。

---

## 1. 执行摘要

本轮基于 `open-code-review`（`ocr v1.13.11`）的主机代理委托协议，在 `HEAD 5b9a3a280` 上对前后端源码、数据采集与回填管道、交易与投研引擎、CI/CD 门禁、部署脚本及测试基线进行了系统性全仓审阅，重点覆盖**迭代205未审计的 RBAC/IDOR 授权面**以及 **`00c762d80..5b9a3a280` 新合入代码的回归与遗留缺口**。

经去重、合并与源码交叉核验，共确认 **44 项可执行问题与优化项**：

| 严重级别 | 数量 | 核心风险概览 |
|---|---:|---|
| **P0（阻断级）** | **8** | 跟踪证据文件明文泄漏真实 `OKX_API_KEY`；Airflow 回调无鉴权可伪造执行记录；旧实盘网关跨租户 IDOR；`large_file_ratchet` CI 门禁已红灯；`STOCK_ZH_A_HIST` 不复权覆盖前复权与 DDL 冲突；`_call_timeout` 被静默丢弃；`AkshareProvider` 未裁剪未知列；`save_data` 返回值回归破坏幂等调用方并双倍计数 |
| **P1（高优先级）** | **24** | Airflow DAG/风控/自动交易 BFLA 越权、RSS SSRF、模拟盘跨租户覆盖、`start_app.sh` 覆盖 `APP_ENV=production`；模拟撮合非原子化双花与百条持仓截断、组合/回测截断失真、`avg_win/avg_loss` 恒 0、小数手成交被截断、`ComparisonService` 必崩/回撤反选/IDOR、`AITradingService` 并发/全站广播/日志死代码、涨跌幅二次乘 100；回测无法取消与超时僵尸进程、监控僵尸任务、DB 连接池释放缺陷、WebSocket 泄漏、同步阻塞 I/O；`conftest.py` xfail 遮蔽安全回归与生产 bug、`secret-scan` 未阻断 `ci-summary`、MySQL 生产迁移缺 fence 变量；前端重试拦截器吞 401、AI 交易失败误发取消、新闻 URL 注入、分页重置、Refresh Token 未接入、WS 竞态泄漏 |
| **P2（中优先级）** | **7** | 未鉴权信息泄露、生产配置/IB TLS fail-open、fire-and-forget 任务与无界内存泄漏、数据层查询/锁/时区卫生、后端多处 N+1 与分析边界、前端监听/竞态/审计串户、CI `nightly` 审计中断与供应链/脚本漂移 |
| **P3（低优先级）** | **5** | 潜伏 IDOR、孤儿任务与静默 `except pass`/`assert` 清理、测试/门禁卫生与断链清理、前端三大巨型文件拆分、后端高复杂度与巨型文件降债 |

> **正向基线确认**：迭代205 关闭的 P0/P1 项（如 JWT `access`/`refresh` 类型校验、`bcrypt`/SHA-256 凭据处理、大多数业务路由的鉴权与 `user_id` 隔离、前端 `v-html` 经 DOMPurify 净化、Ruff 单测与复杂度门禁）仍保持有效，本方案不重复立项，仅针对实测暴露的新问题、回归及未覆盖缺口立案。

---

## 2. OpenCodeReview 审阅方法与可复现命令

### 2.1 `open-code-review` 执行口径（如实记录）

- 工具版本：`/opt/homebrew/bin/ocr` → `open-code-review v1.13.11 (0f5a284) darwin/arm64`（`@alibaba-group/open-code-review`）。
- 外部 LLM 端点状态：执行 `ocr llm test` 返回 `api_key_cmd for provider "anthropic" produced empty output`，本机未配置 `ocr` 独立 LLM 凭据，因此**未伪造 `ocr scan`/`ocr review` 独立 LLM 报告**。
- 实际采用的 **OpenCodeReview Host-Agent Delegation（主机代理委托）流水线**：
  1. `ocr scan --preview --path src/backend/app,src/frontend/src`：识别全仓 **2,152 个可审查源码文件**（总计 2,347 文件 / +528,825 行）。
  2. `ocr delegate preview --from 00c762d80 --to HEAD`：识别最新合并窗口内 **39 个可审查变更文件 / 71 个总文件**（`+11,460 / -458` 行）。
  3. `ocr delegate rule src/backend/app/api/auth.py src/frontend/src/App.vue src/frontend/src/main.ts scripts/dev/check_all.sh`：提取 OpenCodeReview 内置 Python / TypeScript-JS / Default 规则集（精确优先、安全、并发、边界、资源管理、错误处理、性能、可维护性）。
  4. 按 6 个正交域（安全与 RBAC/IDOR、异步并发与资源、数据采集与回填管道、交易与投研逻辑、前端 Vue/TS、CI/测试/迁移）并行执行源码级审阅，并对核心 P0 发现逐一二次源码复核。

### 2.2 本机确定性门禁与静态检查（E1）

| 检查项 | 命令 | 实际结果 |
|---|---|---|
| 复杂度预算 | `python3 scripts/ci/check_complexity_budget.py` | **PASS**（`max_cc=147, count_cc_ge_50=64`） |
| 大文件棘轮 | `python3 scripts/ci/large_file_ratchet.py` | **FAIL (EXIT 1)**：`portfolio/api.py` 1957 > 1948；`db/database.py` 1030 > 1000 |
| Alembic 迁移链 | `python3 scripts/ci/check_alembic_heads.py` | **PASS**（单 head `20261106_akshare_run_coordinator_claims`，88 revisions） |
| 依赖同步 | `python3 scripts/ci/check_deps_sync.py` | **PASS** |
| 敏感跟踪文件 | `python3 scripts/ci/check_sensitive_tracked_files.py` | **PASS**（但未覆盖 `docs/iterations/.../full-suite-20261118.txt` 中的 `OKX_API_KEY`） |
| 生产锁唯一性 | `python3 scripts/ci/check_prod_lock_singleton.py` | **PASS**（`config/requirements-prod.lock`） |
| 前端图标 A11y | `python3 scripts/ci/check_frontend_icon_a11y.py` | **PASS** |
| 文档链接检查 | `python3 scripts/ci/check_doc_links.py` | **FAIL**（32 处失效链接） |
| Python AST 规则扫描 | `src/backend/app/**/*.py` | `bare_except=0`, `mutable_default=0`, `shell=True=0`, `is_literal=0`; `exec=3`, `pickle.load=3`, `silent_except_pass=17`, `prod_assert=86` |

---

## 3. 工作包规划（WP01–WP08）

为便于按风险从高到低、低冲突地逐项修复，将 44 项问题划分为 8 个工作包：

| 工作包 | 主题 | 涵盖 ID | 优先级 | 建议执行波次 |
|---|---|---|---|---|
| **WP01** | 安全紧急止血与授权收口（密钥清理 + RBAC/IDOR/SSRF/配置） | OCR-01, 02, 03, 09, 10, 11, 12, 13, 33, 34, 40 | P0 / P1 / P2 / P3 | Wave 1（最优先） |
| **WP02** | 数据采集、写入契约与回填管道修复 | OCR-05, 06, 07, 08, 21, 36 | P0 / P1 / P2 | Wave 1 |
| **WP03** | CI 阻断红灯、测试隔离与生产迁移修复 | OCR-04, 26, 39, 42 | P0 / P1 / P2 / P3 | Wave 1–2 |
| **WP04** | 交易撮合、账务、回测分析与投研算法修复 | OCR-14, 15, 16, 17, 18, 19, 20, 37, 41 | P1 / P2 / P3 | Wave 2 |
| **WP05** | 后端并发、进程生命周期、DB 连接池与异步阻塞修复 | OCR-22, 23, 24, 25, 35 | P1 / P2 | Wave 2 |
| **WP06** | 前端鉴权、交易容错、安全与 WebSocket/内存泄漏修复 | OCR-27, 28, 29, 30, 31, 32, 38 | P1 / P2 | Wave 3 |
| **WP07** | 前端巨型文件垂直切片重构 | OCR-43 | P3 | Wave 4 |
| **WP08** | 后端巨型文件拆分与复杂度棘轮下调 | OCR-44 | P3 | Wave 4 |

---

## 4. 逐项修复节奏与验收原则

1. **逐项推进**：严格按 [TODO.md](TODO.md) 从 P0 到 P3 逐条（或按同文件聚类小步）提交 PR 到 `dev`，每完成一项立即补充单测/回归测试并在 `TODO.md` 勾选留痕。
2. **禁止掩盖信号**：修复 `large_file_ratchet` 必须通过拆分逻辑而非盲目上调基线；修复 `known_preexisting_failures.txt` 必须逐项根治并将 `conftest.py` 改为 `strict=True`。
3. **全局验收门槛**：
   - 所有 P0（OCR-01~08）与安全/账务 P1 清零；
   - `python3 scripts/ci/large_file_ratchet.py`、`check_complexity_budget.py`、`check_alembic_heads.py`、`ruff`、`mypy`、`vue-tsc`、`eslint` 全部退出码 0；
   - `secret-scan` 接入 `ci-summary` 阻断门禁，且历史/当前仓库无泄露密钥；
   - 新增/修改逻辑均附带可复现测试证据与 `文件:行` 回执。

---

## 5. 文档入口

- [AUDIT.md](AUDIT.md)：44 项缺陷与优化建议的完整审阅证据（含精确 `file:line`、调用链、根因与修复方案）。
- [TODO.md](TODO.md)：面向逐项执行的优先级 TODO 清单（可直接勾选跟踪、含涉及文件与验收标准）。
