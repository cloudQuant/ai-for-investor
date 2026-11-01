# 第三批 执行隔离 原始证据与迁移预演

日期：2026-10-26。状态：7条执行任务已审查并合入本地集成分支，代码与隔离测试通过；未push、合入dev或部署。OpenData代码截至 `f250940f`，AFI本批未修改业务源码。前一批收据见 [WAVE2_STATUS.md](WAVE2_STATUS.md)，下一批5条开发流见 [WAVE4_PLAN.md](WAVE4_PLAN.md)。

## 分派与合并

| 执行条目 | 子代理及分支 | 本批交付 | 尚未覆盖 |
| --- | --- | --- | --- |
| D03-01局部 | wave3_executor / `codex/od204-wave3-executor` | 审核函数、固定Python helper、非阻塞有界JSON IPC、deadline/cancel/checkpoint、输出丢弃计数和进程组回收；64项执行器测试 | 仅POSIX，非Python沙箱；全局并发、OS配额与持久worker接线 |
| A04-01局部 | wave3_evidence / `codex/od204-wave3-evidence` | 原始body流式SHA、私有目录/文件、独立manifest、原子no-clobber、模型边界重验、FIFO/symlink保护；22项测试 | SIGKILL/崩溃残留暂存与孤立对象的安全回收、实际挂载持久性和保留策略执行 |
| D01-01局部 | wave3_host / `codex/od204-wave3-host` | 固定只读systemctl/crontab、有界proc/checkpoint/配置hash盘点；43项测试 | systemd存在UNKNOWN、proc/checkpoint为PARTIAL，writer身份未建立 |
| D03-03局部 | wave3_dispatch / `codex/od204-wave3-dispatch` | scheduled/manual/backfill同一RunService入队、dry-run、APScheduler真实slot桥接；31项测试 | 生产scheduler启动、管理员API、CLI/systemd接线 |
| D05-02局部 | wave3_migration / `codex/od204-wave3-migration-plan` | runtime/catalog/审核mapping/目标白名单及指纹的离线dry-run；56项测试 | apply、实际目标授权与备份恢复；本次0个ready任务 |
| A02-04 | wave3_contract_gate / `codex/od204-wave3-api-contract-gate` | actual main v1/v2冻结、兼容检查与make gate接线；24项行为测试，控制任务代码/离线DEV_DONE | 远端CI未执行；完整gate失败状态单列 |
| B02-01修正 | wave2_stock / `codex/od204-wave3-stock-wire` | HTTP原始JSON code/market校验后构建股票行，避免vendor回填symbol造成伪身份校验；股票迁移/P0组合96项测试 | 真实返回未成功，verified=False；HTTP先完整buffer再执行2MiB检查，入口流式硬上限尚缺 |

root集中维护主集成分支、共享契约/路由、quality reference/census和文档。每个分支小批提交、独立审查后cherry-pick；五人团队可按A–E工作流领取这些小任务，不共享同一checkout。

## 集成审查与修复

执行器审查发现初始通信实现可能在部分帧/大参数发送时阻塞，已改为父端非阻塞读写和持续deadline/cancel/checkpoint；固定helper避免callable导入阶段输出泄露。第二次组合又暴露真实竞态：新session已建立，但父端未消费ready帧时触发超时，只清理直接子进程，可能留下fork后代。现于Popen成功时记录隔离事实，ready不能降级；新增ready前fork回归，独立短deadline复现及完整64项测试通过。

APScheduler的 `EVENT_JOB_SUBMITTED` 先于executor执行/misfire判定。队列接收、tick完成和数据发布分别记录，不能用提交事件宣称自然周期成功；保留原occurrence，不改写成latest。Cron采用APScheduler3五字段，weekday仅接受 `*` 或命名星期；数字weekday需要先确认旧方言并人工转换，避免把POSIX周一至五解释成其他日期。

raw证据在写入边界重新验证manifest/source，拒绝FIFO、符号链接、过大摘要整数和冲突对象，普通失败清理临时文件。同一body的不同请求/来源/时刻保留独立manifest。主机清单修复了输出/配置别名、FIFO、PATH伪装和根目录扫描上限；迁移计划拒绝bool版本号，分别绑定task/script参数hash及审核映射。

## 回归结果

- 最终40个选定测试文件：**1,491 passed、24 deselected、2 warnings，139.78秒**。受检25个生产目标的语句与分支综合覆盖率 **91.23%**；data模块组 **91.69%**、pipeline模块组 **94.11%**。这是选定范围，不是整仓覆盖率。两项warning为测试SQLite连接ResourceWarning。
- 4项跨模块行为测试使用真实子进程与临时SQLite串起“提交→raw body/manifest→同事务fenced publication→固定snapshot”；超时、取消及损坏证据均不发布。源数据明确为合成fixture。
- 68个新增/触碰Python文件的Ruff/format与Python3.10语法检查通过；34个core及3个SDK目标的定向mypy通过，使用 `--follow-imports=silent`，不宣称全传递依赖检查。37个生产目标Bandit通过。实际运行时为Python3.13.5，3.10运行矩阵未执行。
- `brand-check`、`zero-dep-check`、`public-api-quality`、`published-openapi-check`分别通过。零上游扫描覆盖963个runtime文件、冻结引用0；2,475个公共callable文档/注解100%。实际tracked-file引用表对账0问题，保留既有排除桶和12条精确AST例外，没有扩大整目录豁免。
- v1冻结140条路径、166个operation、32个schema；v2冻结6条路径、18个schema。检查器接入现有CI调用的make gate；没有执行远端CI或push。

最终通过前保留了两次失败收据：一次旧catalog断言仍假设原生wire必须调用vendor函数，更新为实际边界；一次进程组ready竞态，修正后重跑。前批独立MySQL7项、AFI157项和SDK安装5项属于第二批收据，本批没有冒充重跑。

机器验证记录为OpenData `docs/afi204-wave3-validation.json`，保留精确argv、环境、源码hash、覆盖分母及失败收据hash；私有持久归档索引为 `docs/afi204-wave3-archive.json`。

## 真实盘点与外部限制

12:54 UTC主机采样记录20个项目关联systemd unit、12个active、16个installed和8个timer；3次show失败使整体UNKNOWN。77个项目路径关联进程仍全部未分类，不能称为77个采集器；proc有权限/竞态缺口、checkpoint扫描截断。配置仅hash、不保留secret值，没有启停服务。

重新生成的静态catalog含1,066个脚本，其中877个未静态匹配已注册Fetcher、189个待人工确认；未匹配不等于均需从零实现。迁移预演保留1,103个调度任务及10条无调度helper，runtime/static anti-join为0；没有逐任务审核mapping、目标白名单和实际指纹时，**1,103个BLOCKED、0个ready、0个启用**。旧启用状态不自动转成新enabled；影子补数须在隔离目标，每个生产dataset/sink保持单写者。

两次股票公开源短窗口请求均在收到HTTP状态前断开，没有响应体。标的600519/000001、业务窗口2026-10-22至23、无重试或备用源；本次无法核验真实字段，Provider保持verified=False，许可与历史保留未知，不能据此推断源整体不可用。

完整 `make gate` **退出2并在secret-check停止**：指定Gitleaks8.30.1缺失，官方checksum可读但binary archive限时下载失败；实际扫描提交数0、发现数N/A。后续gate子项因短路未执行，不能计为通过。另有历史manifest引用的5,130个支撑路径、16个活动入口路径仍缺失；Git精确hash审计匹配4,024个候选副本，1,031个候选、73份唯一收据及分类/审批原件无匹配，未恢复文件或修改pin。

第三批日志、覆盖数据、脱敏主机库存及迁移预演按hash归档至原OpenData `var/reports/afi204/2026-10-26-wave3`，目录0700、文件0600、Git忽略。第二批22份收据保留独立wave2目录；同主机持久归档不等于异机备份或恢复演练。

真实源、全部模型族适配、全历史迁移/逐标的对账、实际worker部署、自然周期、备份恢复、AFI剩余消费者/UI和生产单写者切换仍继续验收。本批未修改原203脚本、运行中恢复任务、生产DDL或API开关。
