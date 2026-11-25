# 迭代207：OpenCodeReview 全仓复审与改进计划

> 编制日期：2026-11-25（Asia/Shanghai）
> 审阅基线：`dev` @ `4bdfab992fc4d0a0e169d2bba30d88bbe57509a8`
> 状态：**COMPLETED（24 / 24，本地验收完成；证据保留本地，不纳入提交）**
> 证据口径：**E1 = 本机命令直接复现并保留输出**；**E2 = 源码与调用链静态确认**；**E3 = 需在 MySQL/PostgreSQL、SQLite 多进程、生产或受控集成环境动态复验**。
> 证据目录：[evidence/](evidence/)（本地保留，不默认纳入提交）。

---

## 1. 执行摘要

本轮使用固定版本 `@alibaba-group/open-code-review@1.14.2` 的 `scan --preview`、`delegate preview` 与 `delegate rule` 做本地确定性扫描和规则提取；**问题归并、调用链分析、风险判断与修复方案均由当前会话模型完成**，未调用 OpenCodeReview 的外部 LLM review/scan，也未切换到其他模型。

扫描基线：

- 全仓源码：2,394 个文件，其中 2,200 个可审阅，194 个排除，插入 618,444 行。
- 相对迭代 206 基线 `5b9a3a280..4bdfab992`：385 个变更文件，277 个可审阅，108 个排除，`+33,697 / -24,551`。
- 重点复核域：JWT/RBAC/对象隔离、AI 策略持有期研究、行情持久化、纸交易账务、前端异步竞态、后台任务生命周期、CI 门禁真实性。

经与迭代 206 的 44 项已闭环修复逐项去重，本轮确认 **24 项新问题、回归或修复不完整项**：

| 级别 | 数量 | 定义与代表风险 |
|---|---:|---|
| **P0** | **4** | 下一次生产发布前必须关闭：停用账户 JWT 仍有效、策略/回测 RBAC 未接线、持有期样本泄漏、外部 receipt 缺少样本充分性证明 |
| **P1** | **16** | 高优先级：全局配置越权、模拟分析串目录、研究终态不一致、行情取消恢复与重试幂等、SQLite 多进程账务、前端认证与请求竞态、两项 CI 红灯 |
| **P2** | **3** | 中优先级：股票分析页请求栅栏、后台任务生命周期不统一、gitleaks 噪声与扫描口径 |
| **P3** | **1** | 低优先级：迭代索引与迭代 206 状态不一致 |

> **正向基线**：迭代 206 已修复的模拟盘配置/日志写隔离、普通 401 单飞刷新、回测/过拟合 WebSocket 清理、行情搜索序号、纸交易 managed-paper 原子路径、大多数对象归属校验，本轮均未重复立项。新发现针对这些修复未覆盖的兄弟路径或回归。

---

## 2. 当前质量门禁与回归基线

### 2.1 本机确定性检查（E1）

| 检查 | 结果 | 证据 |
|---|---|---|
| Ruff | **PASS**：`All checks passed!` | [check-ruff.exit](evidence/check-ruff.exit) |
| 复杂度预算 | **PASS**：`max_cc=91, count_cc_ge_50=31` | [check-complexity.txt](evidence/check-complexity.txt) |
| 大文件棘轮 | **PASS**：垂直切片后回到原 baseline，未上调 | [WP06](evidence/WP06/green-summary.log) |
| mypy 棘轮 | **PASS**：Python 3.11.8 + mypy 1.20.2；app/collection 本机均 0 错误；collection 的 CI baseline 保持 2，待 CI 产出 provenance 后再收紧 | [WP06](evidence/WP06/green-summary.log) |
| Alembic heads | **PASS**：88 revisions，单 head | [check-alembic.txt](evidence/check-alembic.txt) |
| 依赖同步 | **PASS** | [check-deps-sync.exit](evidence/check-deps-sync.exit) |
| 敏感跟踪文件 | **PASS** | [check-sensitive-files.exit](evidence/check-sensitive-files.exit) |
| 文档链接 | **PASS** | [check-doc-links.exit](evidence/check-doc-links.exit) |
| ORM schema drift | **PASS** | [check-orm-drift.exit](evidence/check-orm-drift.exit) |
| 前端图标 A11y | **PASS** | [check-icon-a11y.exit](evidence/check-icon-a11y.exit) |
| 生产锁唯一性 | **PASS** | [check-prod-lock.exit](evidence/check-prod-lock.exit) |
| 前端 typecheck / lint / tests / build | **PASS**：2,228 tests，185 files；production build 成功 | [WP05](evidence/WP05/tests.log) / [WP06](evidence/WP06/green-summary.log) |
| 后端定向与垂直切片回归 | **PASS**：WP01 56、WP02 268、WP03 312、WP04 152、垂直切片 336 | [WP01](evidence/WP01/) / [WP02](evidence/WP02/) / [WP03](evidence/WP03/) / [WP04](evidence/WP04/) / [WP06](evidence/WP06/green-summary.log) |

大文件红灯不是误报，必须通过抽取/拆分使文件回到当前基线以内；**禁止上调基线绕过**。mypy 红灯是工具链漂移触发 fail-closed，必须先在仓库锁定的 `mypy==1.20.2` 环境重跑，不能通过重生成基线掩盖。

### 2.2 gitleaks 结果口径

`gitleaks detect --no-git` 产生 67 个候选；按 Git 跟踪状态分类为 22 个 ignored、45 个 tracked，规则以 `generic-api-key` 为主。抽查确认候选主要来自 `.env`、测试 fixture、JWT 示例、claim key 和第三方数据文件；**当前没有证据表明存在真实已跟踪凭据泄漏**。计划保留“校准扫描口径与 allowlist”项，不把 67 个候选写成 67 个真实泄漏。

详见 [gitleaks-backend-summary.txt](evidence/gitleaks-backend-summary.txt) 与脱敏后的 [gitleaks-backend-redacted.json](evidence/gitleaks-backend-redacted.json)。

最终扫描拆分为两个口径：全历史继续使用 `.gitleaks.toml` 与精确 fingerprint 审计基线；当前工作树和 PR commit 使用不豁免文档/示例的 `.gitleaks-tracked.toml`。`scripts/ci/scan_tracked_secrets.py` 只复制 `git ls-files` 跟踪的当前文件，最终得到 133 个候选（115 generic-api-key、14 curl-auth-header、4 jwt）；候选不等于已确认泄漏。诊断脚本中的一个 Binance key 候选已改为环境变量读取；137 条历史候选按精确 fingerprint 完成分类后，全历史门禁恢复 0 findings。

### 2.3 全量后端与基线归因

本机基础环境执行 `pytest -q -n 4 --dist loadfile --tb=short`，收集 11,210 项，结果为 **31 failed / 10,972 passed / 185 skipped / 15 xfailed / 13 errors**。该命令未按 CI 排除 `performance`，因此 9 个 performance setup error 属于命令口径差异；3 个 collection error 来自仓外 `bt_api_py` / `bt_api_risk` 缺符号；另有 1 个本轮测试导入错误，已在垂直切片后修正。

对 31 个失败节点逐项归因后，修复了 11 个本轮引入的回归（旧测试合成 JWT、同步 WebSocket mock、过宽子串断言及缺失/停用账户的新 401 语义），并修复新 topic 限流测试的日志传播隔离。最终同一 31 节点集合在当前分支为 **18 failed / 13 passed**，在基线 `4bdfab992` 为 **18 failed / 12 passed**；排除基线不存在的新增测试后，两边 18 个失败节点集合完全相同，`new_failures=[]`、`resolved_failures=[]`。全量运行中 `test_data_topic_hub_lru_eviction_and_tracked_task_cleanup` 的 caplog 顺序敏感失败在当前与基线隔离复跑均通过，未冒充为全量 PASS。

证据：[WP07 验收记录](evidence/WP07/ACCEPTANCE.md)、[backend-full.log](evidence/WP07/backend-full.log)、[失败集合差分](evidence/WP07/failure-set-diff.json)、[当前节点复跑](evidence/WP07/failed-rerun-current.log)、[基线节点复跑](evidence/WP07/failed-rerun-baseline.log)、[40 项新增回归](evidence/WP07/iteration207-regression.log)、[69 项受影响文件回归](evidence/WP07/affected-regression.log)。结论保持 **ACCEPTED_LOCAL**，不声称本机全量后端或远端 CI 已全绿。

---

## 3. 工作包与执行波次

| 工作包 | 主题 | 事项 | 建议波次 |
|---|---|---|---|
| **WP01** | 认证、RBAC 与隔离收口 | REV207-01、02、05～07 | Wave 1（P0）→ Wave 2（P1） |
| **WP02** | AI 策略持有期研究完整性 | REV207-03、04、08 | Wave 1（P0）→ Wave 2（P1） |
| **WP03** | 行情持久化、重试与后台任务 | REV207-09～11、20 | Wave 2 → Wave 3 |
| **WP04** | SQLite 纸交易多进程账务 | REV207-12 | Wave 2，需 E3 |
| **WP05** | 前端认证与异步 generation 栅栏 | REV207-13～19 | Wave 2 → Wave 3 |
| **WP06** | CI 门禁红灯与扫描口径 | REV207-21～23 | Wave 1 → Wave 3 |
| **WP07** | 文档状态与索引收口 | REV207-24 | Wave 4 |

执行顺序：

1. **Wave 1 — 止血与恢复绿灯**：REV207-01～04、22、23。每项先补失败反例，再修复；CI 红灯同步恢复。
2. **Wave 2 — 高优先级业务闭环**：REV207-05～18。按文件所有权并行，避免同一路由/服务被两路同时修改。
3. **Wave 3 — 前端与维护性收口**：REV207-19～21。
4. **Wave 4 — 全量验收与文档**：REV207-24、全量门禁、测试、迁移/部署复验与回滚检查。

---

## 4. 强制验收原则

- **先红后绿**：P0/P1 必须存在可在当前代码上失败的反例；修复后同一反例转绿。不能只增加“实现存在”的断言。
- **双向控制**：每个安全/竞态测试同时包含合法用户或当前请求通过的对照臂，以及越权/迟到请求失败的实验臂。
- **精确失败码**：基础设施、取消、清理失败不得被主异常或通用 500 掩盖；错误回执必须能定位到主失败和清理失败。
- **不放松判定**：样本充分性、时间隔离、权限和终态标准由策略/安全契约决定，禁止为让测试通过而删除断言或调宽阈值。
- **无静默兼容**：若研究快照缺少隔离所需元数据，应要求重新封存；不得默认视为隔离通过。
- **CI 基线不漂移**：大文件与复杂度只能向下收紧；mypy 只能在锁定版本、解释器和配置下重生成，并说明差异。
- **证据可复现**：每个完成项记录命令、退出码、测试节点和关键 `文件:行`；E3 未完成时不得把静态修复标为生产验收完成。

---

## 5. 全局通过标准

### 5.1 代码与门禁

```bash
# 本机工具链漂移时，用隔离环境复现仓库锁定的 Python 3.11 + mypy 1.20.2。
MYPY_ENV="${TMPDIR:-/tmp}/afi-mypy-1.20.2"
uv venv --python 3.11 --system-site-packages "$MYPY_ENV"
uv pip install --python "$MYPY_ENV/bin/python" "mypy==1.20.2"
"$MYPY_ENV/bin/python" -m mypy --version

python3 scripts/ci/large_file_ratchet.py
python3 scripts/ci/check_complexity_budget.py
"$MYPY_ENV/bin/python" scripts/ci/mypy_ratchet.py
"$MYPY_ENV/bin/python" scripts/ci/mypy_ratchet.py --scope collection
python3 scripts/ci/check_alembic_heads.py
python3 scripts/ci/check_deps_sync.py
python3 scripts/ci/check_sensitive_tracked_files.py
python3 scripts/ci/check_doc_links.py
python3 scripts/ci/check_orm_schema_drift.py
python3 scripts/ci/check_frontend_icon_a11y.py
python3 scripts/ci/check_prod_lock_singleton.py
```

以上命令均须退出码 0；mypy 必须运行在固定 `1.20.2` 环境。

本地 secret-scan 只复制 `git ls-files` 跟踪的当前工作树，不扫描 ignored/untracked 的 `.env` 或 evidence：

```bash
python3 scripts/ci/scan_tracked_secrets.py --report /tmp/afi-tracked-secrets.json
```

报告中的 `findings` 是候选数，不是已确认泄漏数；`audited_line_matches` 仅表示路径/规则/行号与历史审计记录一致，不替代对当前值的复核。CI 的 PR commit 范围扫描与全历史指纹门禁继续分别执行。

### 5.2 测试

```bash
cd src/backend
pytest tests/test_iteration206_security_rbac.py \
  tests/test_iteration207_auth_authorization.py \
  tests/test_ai_research_holdout_worker.py \
  tests/test_iteration207_holdout_integrity.py \
  tests/market_data_platform/test_cffex_settlement_collector.py \
  tests/market_data_platform/test_stock_valuation_collector.py \
  tests/test_opendata_direct_query.py \
  tests/test_paper_trading_service.py \
  tests/test_iteration207_paper_sqlite_multiprocess.py

cd src/frontend
npm run typecheck
npm run lint
npm run test -- --run
```

其中 `test_iteration207_*` 为本轮拟新增测试；新增前必须确认其断言针对当前缺陷会失败。

### 5.3 E3 发布门禁

- SQLite 多进程纸交易反例通过，且 MySQL/PostgreSQL 行锁路径无回归。
- 研究隔离与 receipt 充分性在测试数据库和受控外部 evaluator fixture 上通过。
- 在线行情持久化在事务提交后各 `await` 点取消均可恢复，不得遗留不可见 receipt。
- 未完成 E3 的事项保持 OPEN；不得以单进程单测替代发布证据。

---

## 6. 回滚与兼容策略

- **默认策略**：每个工作包独立提交/PR，目标 `dev`；不做跨工作包的大爆炸提交。
- **安全与 RBAC**：新增依赖默认 fail-closed；回滚只回退接线代码，不删除角色/权限定义和回归测试。
- **研究隔离**：新增 manifest/策略版本字段采用向后可读迁移；旧快照无元数据时拒绝 promotion，不伪造默认值。
- **行情持久化**：保持 append-only 审计语义；幂等修复通过唯一键/去重判断实现，不删除历史 revision。
- **纸交易**：仅改变执行事务边界与锁策略，不改变订单公开 API；保留 managed-paper 与 legacy 两条测试臂。
- **前端**：请求栅栏为进程内状态，不改变 API 契约；回滚不得恢复共享 `isLoading` 被旧请求覆盖的旧实现。
- **文档**：REV207-24 独立提交，不夹带业务代码。

---

## 7. 文档入口

- [AUDIT.md](AUDIT.md)：25 项发现的精确源码位置、违反的不变量、证据等级、最小反例与修复方向。
- [TODO.md](TODO.md)：逐项执行清单、依赖、文件所有权、验收命令与回滚方式。
- [evidence/ocr-scan-preview.json](evidence/ocr-scan-preview.json)：OpenCodeReview 全仓扫描预览。
- [evidence/ocr-delegate-preview.json](evidence/ocr-delegate-preview.json)：迭代 206 基线至本次 HEAD 的变更预览。
- [evidence/ocr-delegate-rules.txt](evidence/ocr-delegate-rules.txt)：本地规则集提取结果。
