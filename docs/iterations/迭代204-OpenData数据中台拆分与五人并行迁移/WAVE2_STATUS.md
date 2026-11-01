# 第二批：持久发布、受控执行与 REST 快照

日期：2026-10-26。状态：代码与独立集成验证通过，完整迁移验收未完成。代码位于两个独立集成分支；尚未合入 dev、部署或切换旧调度。源码、运行清单和测试的验收面分别记录，不把已注册、启用或测试成功等同于真实数据完整。

## 并行方式

本批分派 11 条开发任务，另安排独立审查。每条任务使用独立 Git branch 和 worktree，公共路由、迁移序列和最终兼容性由 root 集成。五人团队可以按 A–E 五条工作流领取这些小任务；子代理数量不要求固定为五个。

| 任务 | 交付 | 验收边界 |
| --- | --- | --- |
| 契约 | Dataset/Publication/Snapshot/Page、字段单位与时间语义、版本 registry、规范化 hash | 有界 JSON 和离线模型验证；不背书源端真实性 |
| 发布 | 追加修订、原子 head/watermark、固定快照、带签名分页、窗口/行/字节上限 | 已发布仓库读取；不替代各域 DWD/原始证据/DQ 规则 |
| 运行账本 | warehouse Alembic 0010、租约、同事务写入 fence、事务边界保护 | 仅可信内部 publisher；不是 Python 沙箱 |
| 执行服务 | 显式审核的 job registry、运行身份重放、heartbeat、取消、结果预算 | 未接生产 APScheduler、systemd 或受限子进程 worker |
| 契约发布 | 校验来源、逐字段单位、业务键、日期与独立时刻，再提交 publication | rejected 批次不发布；unknown 不升级为通过 |
| 股票日线 | 严格证券身份、日期、字段、单位；拒绝复权价冒充原价 | 合成报文验证；真实 Eastmoney 录制未通过，verified 保持 false |
| 静态映射 | 旧函数/参数/sink/外部代码引用到本地 vendor 与已注册 Fetcher 的 crosswalk | 静态能力证据，不是 1,066 个脚本迁移成功 |
| 运行清单 | 两库只读快照、全部任务和脚本、表结构摘要、双向 anti-join | 不抓源、不执行脚本；参数只公开 hash/字段名 |
| 访问控制 | 操作 scope + 数据域 + 服务端审核 grant，主体/权限 hash 绑定快照 | operator 审核配置不自动证明外部数据权利已核实 |
| v2 API | 数据集目录/元数据/records/coverage、创建和读取 snapshot、OpenAPI | 只支持明确声明的日级业务日期读取；其他时间语义明确拒绝 |
| 客户端/消费者 | 独立 v2 SDK；AFI OpenData-only selector 与缺凭据明确失败 | v2 SDK 尚未替换全部 AFI 投研/回测路径；显式 legacy 模式仍保留 |

## 实际清单

真实只读数据库采集时间为 2026-10-26 11:38 UTC。两个数据库分别使用 READ ONLY + REPEATABLE READ + CONSISTENT SNAPSHOT；这不是跨库全局冻结，也不是生产切换收据。

- 管理库有 1,103 个任务：启用 1,098、停用 5。
- 脚本注册有 1,066 条：启用 1,051、停用 15。全部源码路径存在；1,056 个静态入口均有运行态映射，无悬空 script_id 或未解析路径。
- 旧仓库有 1,042 张表。information_schema 的 TABLE_ROWS 仅为估算，不能证明覆盖完整。
- 1,066 个脚本与初始逐文件 hash 全部一致；另扫描 184 个运维/调度/配置文件和 85 条脚本引用。
- 修正后的脚本级分类：877 个未静态匹配已注册 Fetcher，189 个需要人工确认。前一类有本地 vendor export 静态证据；不意味着数据语义、源可用或落库已验证。
- 代码中的服务文件不等于主机已经安装的 systemd/cron。主机任务、进程、checkpoint 和全部旁路写入入口仍需核对。

OpenData 的脱敏摘要位于 `docs/afi204-runtime-inventory.json`、`docs/afi204-migration-catalog.json`；完整只读收据已按hash复制到原OpenData `var/reports/afi204/2026-10-26-wave2`，目录0700、文件0600、Git忽略；22项索引见OpenData `docs/afi204-wave2-archive.json`。这是同主机持久目录，异机备份与恢复演练尚未完成。

## 架构决定与限制

1. **运行账本与发布事实同库。** 运行定义/control metadata 可以保留管理库；`od_run_ledger`、publication、事实修订和 watermark 使用 warehouse engine。0010/0011 都归 warehouse Alembic；不使用跨库伪原子提交。
2. **增量发布不能改变数据合同。** 同 dataset 的 source/schema/semantic/unit/adjustment/contract hash 漂移会失败。升级使用新数据集身份或另做显式迁移，不能给未迁移的旧行套新版本标签。
3. **快照版本与行血缘分开。** 快照固定一个发布序号；未修改的行可能来自更早 publication。响应保留行的原始 publication 和序号，客户端验证其不超出快照边界。
4. **租约使用数据库时钟。** 生产多主机worker必须显式选择 `clock_policy="database"`；领取、心跳、提交均以同连接数据库UTC判断。默认caller仅用于兼容与确定性测试，worker不能覆盖数据库模式commit clock。
5. **可信回调边界。** source fetch/normalize 不持有 warehouse connection；只有审核的内部 publisher 可以进入 fence。SQLAlchemy guard 捕获常见误提交，不能限制任意 Python 或 raw DBAPI；不接受用户提交的回调或动态脚本。
6. **范围公开。** v2 当前不支持 intraday/event_time 窗口、严格 PIT、通用筛选/投影、异步导出和 data-request/admin 管理端点。未知单位/来源/覆盖不会被猜成已验证；unsupported 请求明确失败。
7. **容量是初始预算。** 单页和同步快照有显式上限，超限失败；没有用本次测试声称 p95、并发容量、RPO/RTO 或生产 SLO 达标。

## 独立审查与门禁

本批已修复：完整状态与缺口矛盾、浅层 frozen 模型突变绕过 hash 校验、合同漂移混入旧行、Unicode cursor 变成 500、MySQL 大小写/尾空格比较、TEXT 容量不足、page 在字节检查前整体加载，以及 rejected DQ 仍进入发布。

独立 MySQL 8.0.46 只监听临时 Unix socket；测试为每个案例新建随机 `od204_test_*` 数据库并清理。实际测试涵盖 literal migration、并发 claim、接管、取消、旧 token、callback 回滚、70 KiB JSON、大小写身份、修订快照，以及任务到 REST/SDK 的组合行为。采集输入仍是合成数据，认证测试主体不等于生产凭据验收。

实际验证结果：

- OpenData选定组合回归 **1,120 passed、25 deselected**，语句与分支综合覆盖率 **90.87%**；受检data与pipeline模块组分别93.73%和93.76%。这不是全仓覆盖率。另有两项SQLite ResourceWarning，记录在收据中。
- 独立MySQL **7 passed**；SDK最小/全部extras隔离wheel安装 **5 passed**；AFI消费者/Provider/source policy/query API组合 **157 passed**。
- 精确引用策略 **73 passed**；brand-check、zero-dep-check和public-api-quality通过。扫描器5保持0个冻结外部SDK引用，公开callable 2,449个的docstring与注解均100%。新增6个旧名称分类例外逐点绑定SHA和AST结构，真实import/动态加载仍失败。
- 目标Ruff/format、mypy和Bandit通过；实际Python为3.13.5，3.10仅语法核验，未冒称运行矩阵。
- 修复了组合回归发现的HTTP `Retry-After` 日期秒级舍入问题，并用固定时钟测试验证后复跑通过。临时MySQL实例已按准确datadir/socket验证身份并通过管理员socket关闭，测试库均清理。

机器收据位于OpenData `docs/afi204-wave2-validation.json`，包含源码/报告hash、测试范围、限制与私有日志hash；操作说明见 `docs/operations-afi204-migration.md`。本批22份私有收据已完成同主机持久归档，未完成异机备份或恢复演练。

整仓门禁尚未通过：两个OpenData checkout均缺少既有immutable-evidence manifest引用的5,130个文件；现有依赖静态诊断、secret全历史扫描等也不能由本轮定向检查代替。正在只读核查历史原件恢复路径，不伪造批准或扩大豁免。

## 下一批依赖

1. 将审核的 stock Provider、原始证据/日历/coverage 接入实际 job，并提供受控 worker/CLI/APScheduler 入口。
2. 按模型族审查 877 个未静态匹配已注册Fetcher的脚本和 189 个待确认脚本，确定复用或新增适配，生成旧 task → job/version/dataset/sink 映射；默认 disabled。
3. 开发存量历史导入 dry-run、分区对账、源更正追赶和备份恢复，不以 MAX 日期判定完整。
4. 扩展其他资产、真实覆盖和来源验证，再迁移 AFI 剩余直连消费者与管理界面。
5. 满足逐域真实源、自然周期、单写者和回滚门槛后切换；保持未覆盖域需求开放。

## 第三批已分派

6个子代理分别在独立worktree/branch开发：受控子进程执行器（D03-01局部）、原始响应证据存储（A04-01）、主机systemd/cron/进程只读清单（D01-01局部）、统一scheduled/manual/backfill提交器（D03-03局部）、迁移映射dry-run（D05-02局部）、v1/v2 OpenAPI兼容门禁（A02-04）。这些在开发中，不计入本批已验收结果；root负责接口协调、独立审查和最终组合测试。
