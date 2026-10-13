# 迭代 200–202 开发与验收执行台账

> 开始日期：2026-10-12（Asia/Shanghai）。状态：**PASS / ACCEPTED_LOCAL**。本台账记录用户进一步授权的开发与验收，区别于本目录最初的只读审查和计划交付。完成状态须由主审对当前代码和新鲜证据确认。

## 范围与版本

- 起始 HEAD：`50b6a54baa6a7d9424bc3b3664c399c297908852`，分支 `feature/a5-opendata-provider`。
- 迭代 200：刷新 canonical lock、Mypy 1.20.2、质量棘轮、前端受支持 Node、完整本地回归及依赖审计证据；历史 T69 结果不代替当前验收。
- 迭代 201：完成九个工作包的具名职责拆分、兼容和失败边界测试、量化尺寸及全局门禁。
- 迭代 202：D01–D03、D06–D14 开发与验收；**D04/D05、WP03 继续 DEFERRED_TO_OPENDATA**，后续接入 OpenData 时统一处理。
- 用户追加决定：本轮升级 Tailwind 4，并补样式及真实浏览器回归；兼容性下限为 Safari 16.4、Chrome 111、Firefox 128。该项用于处理当前前端依赖审计中没有 Tailwind 3 修复版本的依赖链，不将版本升级本身当作样式验收。
- 不执行生产发布、真实行情采集、模型付费调用或交易操作；数据库与部署验证使用一次性本地环境。
- 根目录中已有 README 中英文版、DISCLAIMER 和三个许可证草稿属于用户现有改动，保持不变。本轮没有提交或推送。

## 工作包归属与进度（当前）

| 迭代 / 工作包 | 实现范围 | 执行状态 | 主审验收 |
| --- | --- | --- | --- |
| 200 / 当前门禁 | 最终依赖、类型/尺寸/安全、前后端回归 | canonical Mypy 667 文件零错误、0/0 ratchet；两套 Node 各 1,726 passed；后端 25 个原失败全部整文件复验关闭 | PASS / ACCEPTED_LOCAL |
| 201 / WP-01–WP-09 | 九个具名职责拆分和兼容/失败边界 | 全部指定回归、49 个新模块及 11 个入口尺寸通过；公开 facade 和 498 个前端返回键保持 | PASS / ACCEPTED_LOCAL |
| 202 / WP01 | token 用途及优化任务授权失败关闭 | 主审鉴权 27 passed，加完整批次覆盖 | PASS |
| 202 / WP02 | 网格、有界取消、终态 CAS、最优摘要 | 关联 169、生命周期 14、专项及完整批次覆盖；真实 ZIP/进程/线程路径 | PASS |
| 202 / WP03 | THS dry-run、历史补缺 | DEFERRED_TO_OPENDATA | 不进入本轮门槛 |
| 202 / WP04 | 研究任务容量与租约派发 | MySQL/PostgreSQL 跨连接租约、容量及取消通过，完整批次覆盖 | PASS |
| 202 / WP05 | 会话代次、身份重试、工作区资源竞态 | 最终 v15 两套 Node 及同产物浏览器通过 | PASS |
| 202 / WP06–WP08 | 开发启动、迁移/只读启动、TLS | 两库迁移、备份恢复、开发首次启动、TLS 及最终生产镜像 v5 双 worker 启停通过 | PASS |
| 202 / WP09 | 当前版本集成证据汇总 | 后端原批次及 25 项复验逐例映射完成，最终 12 个源码变化及生产镜像有收据 | PASS / ACCEPTED_LOCAL |

主审核对的当前入口是[最终验收汇总](FINAL_ACCEPTANCE.md)、[201 工作包映射](evidence/2026-10-12/iteration201-final-workpackages-parent-review.json)和[后端组合复核](evidence/2026-10-12/backend-final-composite-parent-review.json)。原失败与中断保留，不能把组合复验描述成原全量运行零失败。

## 验收环境与已知边界

- Python 命令统一使用 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python`；base Python 为 3.11.8。
- base Mypy 2.3.1、Backtrader 1.4.0 与 canonical lock 不同。已在临时 target 安装锁定依赖，通过 `PYTHONPATH` 使用；最终同步检查 172 个 registry pin 一致，Git Backtrader 为 1.3.0 / `04adc08c2deb02cbf240efbd495e5eee68b375d8`。开发 PostgreSQL 驱动及生产迁移工具已补齐。不修改用户共享 Conda base。
- 临时验收目录：`/tmp/ai-investor-iter200-202-20261012.afLb99`。完成收据将把必要脱敏证据保存至仓库文档目录并记录摘要，不能仅依赖临时目录。
- 系统默认 Node 25.1.0 不作正式验收。主审已用 Node 20.20.2 干净执行最终锁的 `npm ci --ignore-scripts`，并独立通过 Node 20.20.2 / 24.19.0 引擎检查（232 required packages，86 optional skipped）；类型、测试、构建与浏览器继续。
- Docker daemon 版本 29.3.1；一次性 MySQL 8 / PostgreSQL 16 上前序 revision 升级与双只读启动已有主审独立证据。MySQL 8.0.46 真实备份恢复现已主审独立通过，见恢复与构建收据；此前无收据的实现者声明不作为验收依据。
- AGENTS 引用的 `.joyincode/rules/backend.md`、`.joyincode/rules/frontend.md` 不在当前仓库；使用实际存在的 `docs/reference/CODING_STANDARDS.md`，后续文档治理将准确标注路径。
- 并行实现阶段不运行最终全量回归；待文件可导入且工作包收敛后，再在一致版本上出具全局证据。

## 最终收口进度

后端全量运行已结束：7,853 passed / 25 failed / 130 selected skipped；控制台/JUnit 另有 1 个 collection skip，总计 131 skipped，24 performance deselected，选中范围无未运行用例。25 个原失败全部对应整文件复验通过；晚改的 workspace JSON 4 项复验已计入 12 文件最终源码映射。最终生产镜像正式构建 exit 0 / 3,506.158 秒；v5 运行 327.712 秒通过，包含无 DDL 账户、双 worker、独立 HTTP/DB 健康、TERM 优雅退出和前后 schema 一致。镜像内 1,777 个源码文件、123 个生产 registry pin、UID 1000 及固定 Git Backtrader 均核对通过。本轮必要本地门槛已关闭，原失败、131 skip、24 performance deselected 与范围外 NOT_RUN 保留。见[最终运行复核](evidence/2026-10-12/prod-source-final-runtime-parent-review.json)及[镜像源码复核](evidence/2026-10-12/prod-source-final-image-parent-review.json)。

## 历史主审发现与处理（按当时快照保留）

以下“当前”“待完成”“运行中”及中间计数均指记录当时；最新状态以前述收口进度与最终汇总为准。

- 收尾复验：新增开发锁的 **172 registry pin 同步、0 已知公告审计、Mypy 667 文件零错误及 0/0 ratchet** 全部通过，CTP 工作区原文件在真实 checkout **55 passed**。后端完整批次继续检出旧测试契约不匹配，已逐项复核修订，主审整文件结果为 WebSocket **5 passed / 1 既有 skipped**、历史封存验收工具 **34 passed**、服务边界 **11 passed**。见[最终锁复核](evidence/2026-10-12/docx-final-dev-parent-review.json)与[三文件复核](evidence/2026-10-12/late-fixture-parent-review.json)。历史 197 runner、生产迁移验证和优化调度实现未因此放宽；该 runner 仍明确拒绝当前 202 后继图。
- 当前结果统一汇入[最终验收汇总](FINAL_ACCEPTANCE.md)，其中后端完整批次与生产最终镜像保持未关闭，其他历史段落按当时快照保留。

- 最终前端 v15 已完成：Node **20.20.2 / 24.19.0 各 1,726 项通过**，两套 Vue typecheck、构建配置 tsc、零 warning ESLint、正式 build 与原 bundle gate 全部通过；176 个 dist 文件逐字节一致。会话/工作区 **7 项**、Chromium/Firefox/WebKit 样式 **9 项**均在同一最终产物上通过，零重试、零 flaky。见[矩阵复核](evidence/2026-10-12/frontend-final-v15-matrix-parent-review.json)和[浏览器复核](evidence/2026-10-12/frontend-final-v15-browser-parent-review.json)。最低版本浏览器仍为 NOT_RUN。
- 后端补齐职责的八文件差异已完成独立回归：portfolio、workspace、paper runtime、valuation、AkShare/OpenBB **451 passed / 0 skipped / 0 failed**，源码前后不变，见[差异复验](evidence/2026-10-12/backend-final-delta-parent-review.json)。full-v3 的五项旧 fixture 失败保留原记录，使用整文件复验及精确源码清单映射，不能把原批次改写为零失败。
- 完整回归另发现开发依赖缺少 `python-docx`；已只在 dev extra 加入并锁定为 **1.2.0**，原有 171 个 pin 和生产锁不变。新增后的 172 项安装同步已通过，真实 Git checkout 的完整 CTP 工作区离线文件、审计及最终 Mypy 正在复验。tar 快照里两条 `git check-ignore` 返回 128 将由真实仓库原断言验证，不改用例、不伪造 Git 元数据。
- 最终后端完整批次和官方生产 Dockerfile 的最终源码镜像构建仍运行；以上局部 PASS 不代表三个迭代已经整体关闭。

- 最终补齐复核：后端职责补齐后，canonical Mypy **667 文件零错误**、类型棘轮 0/0、全后端 Ruff 0.16.2/format、全局尺寸门槛再次通过，源码前后不变。主审已固定与 full-v3 的八文件差异清单，在另一个无网络、带 init 的容器中运行 portfolio/workspace/paper-runtime/valuation 及修订 runner 测试的完整文件回归。
- WP-07 审查发现继续任务迁出后漏设运行态；恢复原 `aiResearchRunning=true` 并新增 deferred 成功/失败和重复提交边界。v14 Node20 的 1,724 项虽通过，但未覆盖该遗漏；主审明确停止自己核验的 v14 进程组，保留其类型/lint/测试通过与构建中断状态。最终 v15 Node20/24 全矩阵重新运行，生产镜像也从最终后端源码重建；不影响其他项目任务。
- full-v3 已完整执行研究服务 **219 项通过**和研究 manager 新边界 **3 项通过**；完整后端批次继续，最终仍须依据全批退出和剩余失败汇总验收。

- 完成审计更新：v12 最终构建及原 bundle gate 均 **PASS**，dist 与已有浏览器受测产物逐字节相同，见[构建收据](evidence/2026-10-12/frontend-final-build-v12-parent-receipt.json)及[产物映射](evidence/2026-10-12/frontend-v12-browser-dist-linkage.json)。v10 的 428 文件源码清单已归档。最终 Vue typecheck、全量零 warning lint 及 Node 24 完整矩阵待下一次冻结源复验。
- 迭代 201 完成审计发现三个窄范围缺口，重新打开 WP-02/WP-03/WP-07：portfolio 估值与概览聚合、workspace 响应行方向/数量别名归一化、前端研究任务生命周期。按原计划补齐协作者边界，不以行数下降替代职责完成。策略 CUD 已在 dialogs 协作者，不额外要求独立 CRUD 文件。此前静态、回归、构建及运行镜像证据保留为调整前快照，补齐后刷新受影响证据。

- 20:50 更新：最终前端 v10 **157 个文件、1,721 项全部通过 / 143.89 秒**，命令 exit 0；独立 Vite 配置 tsc 通过，输入源码前后不变。v9 的 6 项 10 秒超时保留，未放宽 testTimeout；类型检查同时修正了 `vitest/config` 引用、Node 配置 ES2020 target 和无效的 `setupFiles: first`，后者改为受支持的 `list`，实际顺序执行语义不变。见[完整收据](evidence/2026-10-12/frontend-final-v10-parent-receipt.json)。
- 正式样式 v9 **9 passed / 34.9 秒**；主审已查看 Chromium 浅色桌面登录、WebKit 深色移动工作区截图。等待确切主题 popper 隐藏后，原有 390px 宽度门槛全部通过，未改 CSS 或分块。最低浏览器版本仍 NOT_RUN。
- 生产双 worker 的真实启动、无 DDL 权限、独立 HTTP、TERM 退出、exit 0/OOM=false 和前后 schema 指纹一致已通过[组合复核](evidence/2026-10-12/prod-runtime-parent/parent-review.json)。v4 只读取已停止容器和既有数据库；v1/v2/v3 的错误假设及原失败收据保留。
- AkShare 当前 fixture 全文件 **32 passed / 166.47 秒，exit 0**，无存活 runner 后代；OpenBB 用真实 runner/provider 源文件定位 checkout root 后，四项原失败及无 Git 回退专项 **5 passed / 89 deselected，exit 0**。产品逻辑未变。后端 full-v3 在原冻结快照继续，已核实 pytest 进程存活；五项旧 fixture 失败不会覆盖，最终汇总须列明这两份修订测试。

- 20:30 更新：AkShare 修订测试的独立文件已经生成 **32 passed / 263.36 秒** 的控制台及 JUnit 结果，但外层会话退出 143，未捕获 pytest 退出码。完整 Vitest v8 同样以 143 中断且缺少最终 JSON；两轮均保留为 harness 未完成，未确定信号来源。见[中断复核](evidence/2026-10-12/interrupted-v8-and-akshare-v6-parent-review.json)。当前将运行器与工具会话分离、直接落盘退出收据，产品时限和单 worker 设置不变。
- 移动端原操作序列复现了明确的瞬态：主题 dropdown 正在离场，仍位于桌面锚点，根元素 scrollWidth 为 1257（登录）/1088（工作区）；页面内容和 body 宽度均为 390。第 10 个 RAF 菜单变为 display:none 后恢复 390。修订测试等待该菜单真正隐藏，再保留原宽度断言，不改产品样式。主审查看了登录和工作区的收敛后截图。
- 生产 v3 验证了 PID 1 init → Gunicorn master → 两 worker、无 DDL 权限、两 worker 就绪及独立 HTTP 200。真实停机日志含两 worker 的 Application shutdown complete / Finished server process 和 master shutdown，容器 exit 0、OOM=false；harness 因还要求不存在的 Worker exiting 字样失败。将以独立只读续验核对当前 worker 实现的实际退出标志及前后 schema 指纹，原 v3 失败不改写。
- 后端完整 v3 继续运行；除已修订的 AkShare fixture 外，另有四个 OpenBB 测试在查找 checkout 根目录时 StopIteration，正在核对隔离快照是否遗漏真实根标志文件，尚不归为产品缺陷。

- 20:14 更新：v8 构建与未修改的 bundle gate 通过，主审独立复验原预算也通过：入口/登录 JS 请求 2/4，入口/登录 gzip 471,714/492,689，最大初始 JS gzip 411,500 bytes。manifest 恢复唯一入口和 LoginPage facade，完整依赖图无静态循环。正式 preview 会话/工作区 **7 passed / 53.0 秒**，关闭 D09/D10 当前浏览器门槛，D11 在同一产物再次通过。三浏览器样式 **4 passed / 5 failed / 59.4 秒**，移动 viewport 切换后 scrollWidth 断言需诊断；全量 Vitest 正在单 worker 执行。
- 后端完整 v3 仍运行，目前暴露 AkShare 超时测试的 0.1 秒启动竞态：尚未生成 runner-pid/child-ready 就被真正超时终止。修订仅在该 fixture 等待真实子进程就绪后调用原始 0.1 秒 wait_for，返回后直接验证两个 PID 和整个 PGID 消失；生产超时与清理实现不变，完整文件独立复验待结果。首次新验收容器因重复传入 sleep argv 未启动 pytest，明确记录为 harness 失败后纠正。
- 生产双 worker 已在无 DDL 权限账户下启动且 Docker healthy。v1 fixture 漏配随机管理员密码，v2 则误以为生产控制台含 INFO 就绪日志，两轮 harness 失败均保留；继续用 v2 的既有容器、真实 Uvicorn 及应用文件日志完成独立进程树/HTTP/优雅退出/schema 指纹续验，尚未记运行验收 PASS。

- 19:53 更新：前端 v6 生产构建 **exit 0 / 599 秒**，独立检查 108 个分块的静态图无循环，shell 的完整依赖闭包未包含 Element Plus 总入口。原 bundle gate 仍失败：手工 auth 分块吞掉登录页 facade，manifest 缺少 `src/views/LoginPage.vue`；因此不能记为预算通过。下一步保留动态路由入口、将完整 shell 静态依赖合并后复验，预算脚本和阈值不改。见[v6 原始证据及复核](evidence/2026-10-12/frontend-build-v6/parent-review.json)。

- 19:45 更新：D12 第三轮从空 PostgreSQL 卷启动最终开发镜像，`up --wait` **exit 0 / 205.189 秒**；独立容器 HTTP 和数据库均 healthy，关闭首次启动门槛。internal fixture 网络的宿主端口探针 exit 7 单独记录，不作为端口发布证据。见[主审收据](evidence/2026-10-12/d12-fresh-start-parent-review.json)。前两轮失败保留。最终生产镜像 `exec gunicorn` 缓存构建 exit 0，真实双 worker 启停验收待运行。
- 前端最新完整 typecheck **exit 0 / 171 秒**，7 个受影响文件 251 项定向测试及局部 ESLint 通过；正式 v6 构建、预算和浏览器尚在继续。后端完整离线回归仍运行，不以当前已通过案例替代整套结果。

- 19:33 更新：主审在相同受测快照启用 Docker `--init` 后，AkShare runner **32 passed / 18.65 秒**；进程表无残留 zombie。原容器 PID 1 为 sleep，已退出后代未被回收，导致严格进程组清理等待；产品清理断言保持不变。见[诊断](evidence/2026-10-12/akshare-runner-timeout-diagnosis.md)与[复验收据](evidence/2026-10-12/akshare-runner-init-v4-parent-receipt.json)。后端完整回归改用该容器，并逐阶段写入 JSONL 记录，尚在运行。
- 开发/生产/local Compose 的 backend 增加 `init: true`，并补生产启动 exec 的信号传递；这些配置的实际运行验收继续。第三轮 D12 已从空数据库启动，仍使用原健康检查时限。新加的浏览器运行时诊断及登录/注册 SVG 图标断言已通过主审 scoped ESLint，正式 dist 回归待构建。

- 19:16 更新：正式 dist 的 preview v5 发现真实初始化错误 `Cannot access de before initialization`。主审从 trace 和 manifest 确认 `application-vendor` 与共享 Element Plus 分块静态循环；3 项失败、1 项由主审中断、3 项未运行，exit 130 / 455.14 秒。该问题与此前 dev fixture 混版不同，正在修复分块边界；原预算不放宽。当前构建的 gzip 预算均通过，但登录静态请求数 10 > 4，仍为 FAIL。见[检查点](evidence/2026-10-12/acceptance-checkpoint-1913-parent.json)。
- 最终 dev 镜像缓存构建已捕获 buildx exit 0；前次 wrapper 因 zsh 特殊变量返回 1 的记录仍保留。第二轮全新 PostgreSQL/Compose up 在 563.39 秒后 exit 1，后端随后于 19:04:55 就绪，不能改写首次启动失败。生产镜像 17 个可选路由全部可用且无导入错误，独立记录于[路由探针（本地原件索引）](EVIDENCE_MANIFEST.json)。
- 后端完整离线回归 8,008 selected，在 market_data_platform/test_akshare_runner_provider.py 已出现 2 个失败后触发 180 秒 thread watchdog，exit 1 / 3,010.31 秒，未生成 JUnit；全套为 INCOMPLETE。将先保留失败原日志，再按文件分组、及时写出结果，避免后续超时抹掉已执行断言。没有放宽产品 sandbox 或取消时限。

- 18:43 更新：冻结源码的浏览器 v4 **4 passed / 3 failed，exit 1 / 420.66 秒**；两项工作区响应顺序、旧会话成功重试隔离、startup 401 通过。主审已查看两张工作区最终截图，标题/单位均为 B。503 场景的 trace 确认四次同 token 的 503 响应，随后路由已到登录页，但同页加载不同优化缓存 hash 的 Vue，在 renderSlot 报错并白屏；其余失败继续逐项归因。见[完整收据（本地原件索引）](EVIDENCE_MANIFEST.json)和[浏览器制品](evidence/2026-10-12/session-browser-v4-parent/results.json)。后续配置改用 `vite preview` 验证同一正式构建的 dist，保留原时限、worker 数、零重试和业务断言。
- 已单独记录开发浏览器前置缓存损坏、配置编辑引起重启的两次中断，均为 exit 130 / INCOMPLETE；没有覆盖原失败记录。见[前置恢复收据](evidence/2026-10-12/frontend-preflight-recovery-parent-receipt.json)。前端构建继续使用原预算，并通过 `onlyExplicitManualChunks: true` 限定手工 chunk 的依赖收纳范围，结果待出。

- 18:27 更新：主审独立复验此前失败的 StrategyPage 防抖旧结果用例，**1 passed / 157 skipped**，用例 3.22 秒、总 32.79 秒、exit 0；不据此前单次失败推断产品缺陷。浏览器会话/工作区七项已启动。后端最终完整离线回归收集 **8,032 项 / 24 deselected / 1 skipped / 8,008 selected**，仍在运行，尚无完整结论。
- 去除未使用的全局图标注册后，前端构建 exit 0，但原预算仍失败：入口闭包 719,594 > 655,360 bytes、登录闭包 726,530 > 655,360、最大初始 chunk gzip 616,736 > 552,960；请求数 2/4 和 4/4 通过。继续定位静态依赖边界，不上调阈值。
- 最终生产镜像的[构建与运行命令收据](evidence/2026-10-12/iter202-prod-build-receipt.md)已归档；主审核对临时 Dockerfile 差异仅为精确 Backtrader 提交的本地镜像来源替换。构建 exit 0 已记录，但起止墙钟时间未单独捕获；镜像配置的 `Created` 时间不等同 `buildx --load` 完成时间，不能据其伪造精确起止。开发镜像仍在按最终 Dockerfile 重建，不能用诊断派生镜像替代。

- 18:07 更新：最终 prod 锁对应的 Python 3.12.15 / linux-arm64 镜像已构建；实现者离线验证 app import、`pip check`、Alembic head、UID 1000 与 Backtrader 精确提交全部通过。主审读取完整输出并独立核对镜像 ID/平台/用户；这关闭生产运行依赖缺失，不能替代真实部署启动。见[运行时和收集复核收据](evidence/2026-10-12/production-runtime-and-collection-parent-review.json)。
- 后端离线容器非性能收集 **7995/8019、24 deselected，exit 0**；排除本轮延期 THS 文件。新增 D03/D08 边界和 ZIP 测试已冻结，先执行专项，再执行更新快照的完整回归。
- D12 日志确定显示 DEBUG app 日志位于 reload 观察树内并持续触发变化记录；开发 LOG_DIR 已移到 `/var/log/ai-for-investor`，Dockerfile/Compose 同步配置。lifespan 约 19 秒，不能把全部冷启动延迟归因于此问题；最终 dev 镜像及 fresh up 仍需验收。

- 17:42 更新：优化相关五文件 **169 passed / 642.86 秒**，加上先前 14 项生命周期通过；下载 ZIP 两项首次运行因测试 gate 在产品临时目录已清理后继续写标记而失败，保留失败证据并修订测试回调。没有为此改变产品代码或生产时限。
- 最终运行依赖闭包已修订：基础依赖声明包含原先仅在 dev extra 的 `httpx` 和 `purgedcv`；prod 锁加入实际导入所需传递依赖，dev 锁逐字节不变，故 666 文件 Mypy 的依赖证据仍适用。主审最终 prod registry 审计 **124 个条目、0 告警、exit 0**；Git 源包的 registry 审计边界保持不变。见[优化与生产依赖审计收据](evidence/2026-10-12/optimization-and-prod-audit-parent-receipt.json)。
- 最终前端构建 **PASS / 2,081.97 秒**；原 bundle 预算实测失败：入口闭包 746,409 > 655,360 bytes，登录闭包 750,286 > 655,360，最大初始 chunk gzip 648,842 > 552,960。正在移除未使用的全局图标注册并收窄共享 chunk，预算不放宽。
- MySQL 8.0.46 主审备份恢复演练已通过，覆盖 gzip/hash/0600、重复输出拒绝、未授权恢复拒绝且旧值不变、授权恢复读回备份值和一次性资源清理。首次 readiness 误判及修正后复跑分别保留收据，产品脚本未改。

- 17:20 更新：主审 canonical-v2 的完整 Mypy **666 个源文件零错误，exit 0 / 4,499.03 秒**；棘轮 **0/0，exit 0 / 47.95 秒**。运行依赖分类修订仍在进行，最终确认 dev 包版本集合不变后复用此证据；若类型配置或实际依赖发生变化，再决定受影响复验范围。收据见 [类型与收集检查记录](evidence/2026-10-12/type-and-collection-parent-receipt.json)。
- 17:15 更新：后端收集错误已定位为临时精简验收容器缺少 POSIX `ps`，不是业务模块导入失败。为该容器补装 `procps` 后会恢复离线，再复验；生产镜像不增加测试工具。
- 生产精确锁镜像已构建，但 `from app.main import app` 在 `opendata_provider.py` 失败：缺少 `httpx`。该包此前仅在 dev extra 中，现转入基础运行依赖并重新生成两锁；旧 prod 镜像构建成功不能算应用就绪。开发锁已有该包，依赖版本差分须另行核对。
- 前端最终完整 Vitest 在 StrategyPage 的 158 项中先报告 18 项失败，随后进程以 143 退出，未形成完整失败堆栈或全套结果。主审未对这个 npm 进程发出停止信号，当前无法确定退出信号来源；该轮明确为 **INCOMPLETE**，不直接归因为机器负载。后续 build/bundle 检查继续，失败用例需单独复验。

- 16:50 更新：用户明确选择保留其他项目任务，继续当前验收。后续较重检查尽量串行；不停止其他项目进程，也不通过放宽产品时限改变验收语义。
- 最终前端 clean install、Node 20/24 引擎、官方 registry 审计、typecheck（515.56 秒）、lint（510.81 秒）均通过；完整 Vitest、build 和浏览器仍待完成。前一次 clean install 被退出信号中断：子任务曾在未核实 cwd 的情况下清理 PID，存在误停主验收进程的可能；该次退出保留为协调事故，不归为依赖缺陷。独立干净重跑已通过。
- 最终后端 Ruff 0.16.2 check/format 和全仓尺寸棘轮通过。当前锁下的全量 Mypy 仍运行；15:04 的 666 文件通过只代表当时依赖快照。
- 最终容器 D13：PostgreSQL 迁移 **1 passed / 66.60 秒**；MySQL 租约与迁移 **2 passed / 215.97 秒**。开发锁没有可选 MySQL extra，因此 MySQL 验收明确另装生产锁的 `aiomysql==0.3.2`；未安装 extra 的首次失败也保留。pytest watchdog 为 600 秒，产品时限未改。
- D12 主审从干净项目执行 `up --wait`，**exit 1 / 353.71 秒，backend unhealthy**。稍后健康接口与数据库检查返回成功，但延迟恢复不能覆盖 fresh up 失败；正在检查启动时序。开发 healthcheck 的 180 秒 grace 已存在，本次未再上调。
- D12 时序复核：容器入口约 08:28:11 UTC 启动，数据库 `SELECT 1` 在 08:28:17 成功；应用 08:38:32 才 ready，首个健康 200 在 08:38:44。探针路径和 migration 依赖顺序一致；当前证据是应用冷启动超过预算，不能直接归为驱动或 DB 等待错误。已保存脱敏日志，停止本次拥有的临时服务以减轻负载；其他项目保持运行。
- 后端离线容器完整回归收集到 8,126 项，但有 1 项收集错误；主审为定位错误中断该轮，退出 143，不算全量回归通过。另两项 sandbox 定点诊断均在启动阶段失败，尚无当前环境下的完整通过证据。
- 以上日志和尺寸、受保护文件哈希见 [当前主审检查点](evidence/2026-10-12/current-parent-checkpoint.json)。后续结果以新鲜独立收据为准；下面按时间保留诊断历史。

- 16:00 更新：最终 dev/prod 锁已冻结为 SQLAlchemy 2.0.54、PyMySQL 1.2.3；171 个安装版本同步通过，两次重新生成的锁逐字节一致；最终两锁 registry 审计退出 0。MySQL 和 PostgreSQL D06 跨连接实测均通过。
- 最终鉴权组合主审结果为 **27 passed / 4 warnings / 368.31s**。TLS 主审通过真实 Pebble HTTP-01 签发及签发、reload、配置读取失败回滚；源文件哈希和服务证书指纹已核对，长期收据保存 54 份脱敏制品。生产 DNS/CA 未运行。
- 最终新迁移兼容普通旧库、已由 ORM 建好列的库和部分列已存在的库；不兼容列在执行 DDL 前显式拒绝。实现者 9 项图与 SQLite 兼容检查通过。主审最终依赖下 MySQL/PostgreSQL D13 均在重建前序 revision 的 subprocess 中触发 180 秒 pytest watchdog，未完成断言，不能记 PASS；正在准备容器复验。
- 宿主单独 Backtrader 导入测得 62.65 秒（`-S`）/92.94 秒（正常），依赖容器冷/热文件缓存测得 39.31/23.49 秒；上述观测支持环境性能受限，但不证明完整产品回归通过。未提高产品 sandbox 的 15 秒 bootstrap 或取消时限。
- 第一次全前端 Vitest 为 **1720 passed / 1 failed**，失败是持久化测试沿用“仅有 token 即已认证”的旧断言；已修正为身份确认后才启用认证状态，待最终全量重跑。首次 typecheck/lint 的失败也保留，最终模板兼容修复尚在收口。
- MiniRacer 0.14.1 不再提供原 `py_mini_racer.py_mini_racer` 导入别名，已改为公开 `MiniRacer` 入口，实际 `eval('1 + 1')` 通过。这是锁升级引出的收集兼容修复，不涉及延期的 THS dry-run 或历史补缺逻辑。

- 15:04 更新：主审 canonical 全量 Mypy 通过（666 个源文件），Mypy 棘轮 0/0。前端全量 typecheck 失败于 Axios 请求类型、Element Plus 表格行/事件类型与一处测试字段；lint 失败于升级后的 Vue/Node/browser globals 配置。完整回归仍在执行，不作整体 PASS。
- 主审真实 MySQL D06 失败：SQLAlchemy 2.0.49 与 PyMySQL 1.2.0 的 `pool_pre_ping` 调用触发 `ping()` 缺失 `reconnect`。上游 [SQLAlchemy 2.0.50 修复说明](https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html#change-2.0.50) 与 [问题 13306](https://github.com/sqlalchemy/sqlalchemy/issues/13306) 确认兼容性缺陷；另据 [PyMySQL 官方安全公告](https://github.com/PyMySQL/PyMySQL/security/advisories/GHSA-x4f8-9hx9-hpp9) 需要更新 PyMySQL。正在保持 SQLAlchemy 2.0 系列并更新补丁锁。下面旧锁 SHA 和审计结果是当时快照，不是修订后最终门槛；registry 审计零告警也不代替上游公告核查。
- 同轮独立数据库检查：MySQL D13 通过、PostgreSQL D06 通过；PostgreSQL D13 因前次测试遗留 `scriptfrequency` 枚举而失败，需修复一次性数据库测试的完整清理，并重复运行确认。未把环境清理失败写为产品迁移通过。
- 开发镜像完成锁定安装与 PostgreSQL migration 后，真实应用启动发现 WeasyPrint 缺少 `libgobject-2.0-0`。执行者正在补系统运行库；原镜像使用修订前 Python 锁，仅作诊断证据。
- 初次 canonical 生产 Python registry 审计发现 2 个包、17 条公告，更新 PyJWT/urllib3 后主审重新执行 dev/prod 两锁审计均退出 0、无已知漏洞；Backtrader Git 源被审计器明确跳过。前端初次全量 registry 审计发现 20 个包节点告警（16 high、4 moderate）；最终锁的主审官方 registry 审计退出 0。用户配置的 npm 镜像不提供审计端点（404/NOT_IMPLEMENTED），该失败保留，正式检查显式使用 `https://registry.npmjs.org`。
- 迭代 201 拆分后的接收者类型已要求保持原服务类型；不能通过新增 `Any` 接收者或省略注解制造类型检查通过。
- D03 的极大有限参数范围可触发 Decimal 除法异常，主审已实际复现并要求在物化前以受控 4xx 拒绝。
- D06 的 MySQL REPEATABLE READ 事务可能保留旧租约快照。实现改为 Provider 前使用短独立会话检查；实现者已在真实 MySQL 8.0 复现并验证跨连接取消，主审独立复验及 PostgreSQL 验证待完成。
- Ruff 必须直接运行隔离目录的 `toolchain/bin/ruff` 并核对 `0.16.2`；仅设置 `PYTHONPATH` 后运行 `python -m ruff` 仍可能转调 base 环境二进制，因此此前版本未核实的格式检查不能直接作为最终 CI 版本收据。
- 后端一次 494 项组合回归出现 worker 崩溃，已保留原日志；三个被点名的用例独立重跑 3 passed。研究服务完整文件未取得通过，定点复跑有两项在 sandbox 子进程 15 秒 bootstrap 握手阶段失败；未进入策略执行，也未修改业务超时。主机高负载仅作环境观测，不能代替根因结论或 PASS。
- 最终 Tailwind 4.3.3 依赖已安装；会话/工作区真实浏览器与样式浏览器分别使用 loopback 4177/4187、单 worker、受控 API 响应，结果尚待收口。

## 已保存的独立证据

最新证据见 [v2 中间收据](evidence/2026-10-12/intermediate-v2-receipt.json)、[鉴权与迁移复验收据](evidence/2026-10-12/auth-and-migration-v2-parent-receipt.json) 和 [TLS 主审收据](evidence/2026-10-12/tls-parent/receipt.json)。当前最终 dev lock SHA-256 为 `6b364dec1106a567294881e16dc626ba52c01e5678a5d2913bb7078258e6a2cb`，prod 为 `b3e165273f2f7eef37d2cfef25d6466b379abd7d681375b020e57966d2efbb6b`。下面的初步收据保留历史失败和修订前锁摘要，不能当作最终版本证据。

[初步核验收据](evidence/2026-10-12/initial-verification-receipt.json) 保存当前依赖锁、审计与三项故障诊断日志的 SHA-256。这里只接受对应的局部检查，不代表三个迭代整体通过。

- dev lock SHA-256：`e7a8a5dc5c5e7adf6b58a1237fffb05dd69613277c4c46bdc378f6860970eba5`。
- prod lock SHA-256：`35db099c180072c93e7d09b9fbd99c0f1c336c649f8ba4cb5eae3bdf8454e15a`。
- 主审工作目录为仓库根目录，使用 canonical target 的 `PYTHONPATH`、Anaconda base Python，分别执行 `python -m pip_audit --requirement config/requirements-{dev,prod}.lock --no-deps --disable-pip --desc --format json --output <对应证据文件>`，两次退出码均为 0。`--disable-pip --no-deps` 直接审计已完整锁定的 registry 包列表，不审计用户共享 base 的额外包。
- 主审另执行 `python scripts/ci/check_lockfile_sync.py config/requirements-dev.lock`，退出码 0，171 个锁定包与 target 中安装版本一致。
- 完整镜像、生产锁运行时、源码类型、前后端全量回归、浏览器、真实数据库与 TLS 门槛继续独立验证。

## 完成规则

1. 只关闭当前实现、命名行为测试和主审复核均通过的工作包。
2. 新模块小于 1,000 行，原入口达到迭代 201 的既定上限；不能用放宽基线或压缩格式代替拆分。
3. fixture、浏览器受控响应、真实数据库和容器分别报告证据，不互相替代。
4. 对环境缺失、失败和未执行项保留 `BLOCKED_ENVIRONMENT`、`FAIL`、`NOT_RUN` 或 `INCOMPLETE`，不借历史 PASS 关闭。
5. D04/D05 延期保留，既不要求当前修复，也不写为已修复。
