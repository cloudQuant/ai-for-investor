# 迭代 200–202：最终验收汇总

状态：**PASS / ACCEPTED_LOCAL**。迭代 200、201、202 的本轮开发与本地验收已完成；D04/D05 仍为 **DEFERRED_TO_OPENDATA**。后端采用完整批次与最终受影响文件复验的组合证据，生产最终源码镜像完成独立启停。过程中的失败与中断保留在[执行台账](EXECUTION_STATUS.md)，不被后续通过结果覆盖。

起始 HEAD 为 `50b6a54baa6a7d9424bc3b3664c399c297908852`，分支 `feature/a5-opendata-provider`。验收结束时实现尚未提交、未推送；后续 Git 交付范围与证据存储见 [GIT_DELIVERY.md](GIT_DELIVERY.md)；受测代码以各收据的文件 SHA-256 和源码清单为准。

## 1. 已完成的最终门禁

| 检查 | 当前结果 | 独立证据 |
| --- | --- | --- |
| Node 20.20.2 / 24.19.0 | 每套 1,726 项全部通过；Vue typecheck、Vite 配置 tsc、零 warning ESLint、正式构建和原 bundle 预算均通过 | [v15 矩阵复核](evidence/2026-10-12/frontend-final-v15-matrix-parent-review.json) |
| 最终生产前端产物 | 两套 Node 生成的 176 个文件逐字节一致；浏览器使用同一产物，检查前后无漂移 | [产物与浏览器复核](evidence/2026-10-12/frontend-final-v15-browser-parent-review.json) |
| 会话与工作区浏览器 | 7 项通过，覆盖临时身份故障、旧会话响应、当前会话 401，以及 A/B 工作区响应顺序 | [浏览器完整收据](evidence/2026-10-12/frontend-final-v15-browser-parent-receipt.json) |
| Tailwind 4 样式 | Chromium / Firefox / WebKit 共 9 项通过，18 张截图；单 worker、零重试、零 flaky | [浏览器完整收据](evidence/2026-10-12/frontend-final-v15-browser-parent-receipt.json) |
| 后端类型 | 最终 dev 锁下 Mypy 1.20.2：667 文件、0 errors；ratchet 0/0 | [最终锁复核](evidence/2026-10-12/docx-final-dev-parent-review.json) |
| 后端 lint / 格式 / 尺寸 | Ruff 0.16.2 check/format 和全局尺寸棘轮通过；后续测试 fixture 的检查分别附收据 | [静态门禁](evidence/2026-10-12/backend-final-static-v4-parent-receipt.json) |
| 后端职责补齐差异 | 8 个文件的完整相关回归 451 passed、0 skipped、0 failed；覆盖 portfolio、workspace、paper runtime、valuation、AkShare/OpenBB | [差异复验](evidence/2026-10-12/backend-final-delta-parent-review.json) |
| 开发依赖完整性 | 172 个 registry pin 与隔离安装一致；另有 1 个固定 Git 提交。只增加 python-docx 1.2.0，原有 pin 不变，连续生成两次一致 | [锁差异](evidence/2026-10-12/docx-dev-lock-diff-parent.json)、[复核](evidence/2026-10-12/docx-final-dev-parent-review.json) |
| 开发依赖审计 | 172 个 registry 条目、0 已知公告；Git Backtrader 不在 registry 审计证明范围内 | [审计原始结果](evidence/2026-10-12/docx-final-dev-parent-audit.json) |
| CTP 工作区离线合同 | 真实 Git checkout 的完整文件 55 passed；原 Git-ignore、报告路径及离线入口断言保留 | [完整命令与结果](evidence/2026-10-12/docx-final-dev-parent-receipt.json) |
| WebSocket fixture 适配 | 整文件 5 passed / 1 既有 skipped；局部 fixture 为未版本化内存库显式启用建表，真实启动、注册、登录和 WS 断言保留 | [独立整文件复验](evidence/2026-10-12/websocket-fixture-final-parent-receipt.json) |
| 历史封存验收工具测试 | 整文件 34 passed；真实历史 B2 迁移图用于相关单测，生产 runner 继续拒绝当前后继、多 head 及缺祖先，不更新封存版本 | [整文件复验](evidence/2026-10-12/iteration197-sealed-fixture-parent-receipt.json) |
| 服务边界 fixture 适配 | 整文件 11 passed；以明确收集事件模拟取消，验证 pending 取消、停止追加投递和取消结果不被采用 | [整文件复验](evidence/2026-10-12/service-edge-fixture-parent-receipt.json) |
| 工作区 JSON 配置 | 整文件 4 passed；本次 objective/direction 覆盖旧运行字段，嵌套配置保留且输入不被修改 | [整文件复验](evidence/2026-10-12/workspace-json-fixture-parent-receipt.json) |
| 后端完整批次与失败关闭 | 原批次 7,853 passed / 25 failed / 131 skipped（含 1 个 collection skip），24 performance deselected；25 个原失败全部对应整文件复验通过。最终源码 12 个变化均有收据映射 | [组合复核及逐例映射](evidence/2026-10-12/backend-final-composite-parent-review.json)、[源码差异](evidence/2026-10-12/full-v3-final-source-delta-parent.json) |
| 编辑边界 | 用户原有 6 个根目录文件哈希不变；49 个新增生产模块均小于 1,000 行，11 个入口均满足计划上限 | [尺寸和保护文件](evidence/2026-10-12/final-source-sizes-and-protected-files-parent.json) |

最终依赖摘要：

- dev：`a2d2c91b7c69ea02b74653f2d5ab11cdb14e482a05ddc71174e53f0a9e1fe42e`。
- prod：`b3e165273f2f7eef37d2cfef25d6466b379abd7d681375b020e57966d2efbb6b`。
- frontend：`6412512146fbf7fc6bd2f1bc04683f71db626f3967cd5dd4cdff1a18eaa4f44e`。

## 2. 职责拆分的主审检查

迭代 201 的九个工作包保持原兼容 facade、错误码和写入顺序；尺寸下降不能单独作为验收。主审核对了迁出主体、调用接缝与失败路径。最终补齐时发现并修正两项迁移遗漏：workspace 别名读取须传入实例方法回调，继续研究任务须在 API 调用前设置运行态。对应新增断言验证实例级替换、等待期间重复提交拒绝以及成功/失败收尾。

- [Portfolio 计算边界复核](evidence/2026-10-12/portfolio-completion-parent-review.json)。
- [Workspace 归一化边界复核](evidence/2026-10-12/workspace-completion-parent-review.json)。
- [策略页面边界复核](evidence/2026-10-12/strategy-task-completion-parent-review.json)：公开返回键前后均为 498，无增加、遗漏或重复。
- [九个工作包的逐文件结果](evidence/2026-10-12/iteration201-final-workpackages-parent-review.json)：WP-01 133、WP-02 138、WP-03 178、WP-04 36、WP-05 173、WP-06 222、WP-08 67、WP-09 71 项通过；计数有重叠，不能相加成唯一用例数。WP-07 在 Node 20/24 各 1,726 项完整回归中通过。
- 后端最终结论采用组合证据：完整批次保留 **FAIL_WITH_COMPLETE_EXECUTION**，25 项原失败由 451、55、34、5、11、4 项通过的完整相关文件结果逐一关闭。原选中范围无未运行用例；130 个选中 skip、1 个收集阶段 skip 和 24 个排除的性能用例保留，未重写为通过。

## 3. 部署和数据库证据

| 场景 | 已有证据及其边界 |
| --- | --- |
| MySQL / PostgreSQL 任务租约 | [真实跨连接租约复核](evidence/2026-10-12/supported-lease-v2-parent-receipt.json)，覆盖容量等待、派发前有效性与取消；不等同真实模型 Provider 验收 |
| 两库迁移 | [容器迁移收据](evidence/2026-10-12/supported-migration-container-parent-receipt.json)：PostgreSQL 1 passed；MySQL 租约/迁移 2 passed；MySQL 可选驱动显式安装并记录 |
| MySQL 备份恢复 | [独立恢复演练](evidence/2026-10-12/restore-and-build-parent-receipt.json)：gzip/hash/0600、重复路径拒绝、未授权恢复拒绝及授权恢复后独立读回 |
| 开发容器首次启动 | [D12 收据](evidence/2026-10-12/d12-fresh-start-parent-review.json)：最终驱动/启动修订镜像从空 PostgreSQL 卷 `up --wait` 成功，205.189 秒；原健康检查预算不变。该镜像绑定加 python-docx 前的 dev 锁 `6b364dec…`；新增仅用于离线报告测试，原驱动及其他 pin 均未变，不能描述成最终 a2d2 锁的全新镜像构建 |
| 生产双 worker | [最终镜像 v5 复核](evidence/2026-10-12/prod-source-final-runtime-parent-review.json)：PID 1 init → master 6 → workers 7/8；受限账户无 DDL，独立 HTTP 200/DB healthy；TERM 后两 worker/master 正常退出、exit 0/OOM=false，schema 指纹不变；总耗时 327.712 秒 |
| TLS | [真实 Pebble HTTP-01 收据](evidence/2026-10-12/tls-parent/receipt.json)：空证书引导、签发、reload，以及失败时保留有效配置/证书；生产 DNS/CA 未运行 |

最终生产镜像 `sha256:ad00640ed6c2b51761b5b9e6d7b70030ecd809a868b3b301aa36c6bfd19732f2` 由仓库 Dockerfile 正式构建，exit 0 / 3,506.158 秒，见[构建收据](evidence/2026-10-12/prod-source-final-build-parent-receipt.json)。[镜像内容复核](evidence/2026-10-12/prod-source-final-image-parent-review.json)确认 1,777 个应用源码哈希、123 个 registry pin 和生产锁一致，pip check 通过，UID 1000，Git Backtrader 为精确固定提交。镜像 pyproject 与最终树唯一差异是后加的 dev-only python-docx，生产依赖及应用代码一致。

v5 在 internal 网络、无宿主端口/挂载的一次性 PostgreSQL 环境验证；验收容器明确使用 health retries=5 和 900 秒启动观察预算，应用 Gunicorn 300 秒、graceful 30 秒保持，实际 Docker stop 宽限为 35 秒。不是默认配置启动耗时基准，也不代表生产发布。新增镜像内容探针先有 stdin 缺失和 60 秒 wrapper 超时，原记录保留；最终具名、逐阶段探针通过，未修改产品。

## 4. 明确保留的范围边界

- **DEFERRED_TO_OPENDATA**：D04/D05（THS dry-run 实际写入、历史补缺）及 WP03。遵照用户决定，本轮不单独修复、不标 PASS，后续接入 OpenData 时统一处理。
- **NOT_RUN**：Safari 16.4、Chrome 111、Firefox 128 这些最低版本。已验证的是安装的 Chromium 145、Firefox 146、WebKit 26。
- **NOT_RUN**：真实交易/CTP 连接、行情供应商生产采集、付费模型、生产数据迁移、生产 DNS/CA、远端 CI 与发布。受控 API、离线策略入口和一次性数据库不替代这些证据。
- 可选 O02 会话刷新、O03 大工件性能优化未扩为本轮缺陷关闭门槛；O01 按迭代 201 单独验收，O04 只完成本轮导航与证据状态维护。
- 后端非性能批次排除性能标记及本轮延期 THS 文件；既有 skip 需随最终结果逐项保留，不计为通过。

[最终交付复核](evidence/2026-10-12/final-delivery-parent-review.json)再次核对 2,303 个后端文件、487 个前端/配置文件及三份锁，均无漂移；6 个用户原有根文件保持不变。已按精确容器 ID 停止本任务的 6 个完成验收的 fixture，保留容器、镜像、数据卷和证据，其他项目未操作，见[资源收尾收据](evidence/2026-10-12/completed-fixtures-stop-parent-receipt.json)。

以上边界不授权生产发布；此处保留提交前的验收快照；后续提交/推送依用户单独授权执行，见 Git 交付说明。
