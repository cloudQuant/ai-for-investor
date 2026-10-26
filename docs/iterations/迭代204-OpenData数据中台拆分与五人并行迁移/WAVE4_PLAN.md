# 第四批 股票日线离线运行切片

日期：2026-10-26。状态：5条独立分支已创建并分派开发。目标是在隔离环境中重复执行“统一提交→持久worker→原始证据→fenced发布→REST/coverage”，并验证一条默认disabled的任务定义导入。真实来源、全历史和生产切换仍单独验收。

## 冻结接口和集成顺序

提交入口只依赖 `RunDispatcher` / `RunService.submit`；worker只依赖 `RunService.run_once`、ledger和审核函数注册。`TaskDefinition`、`RunRequest`、canonical身份及publication合同沿用第三批版本，子代理不得自行更改。代码离线开发用显式合成job/fixture，不依赖真实源认证；股票真实源仍由204-B02-02独立验收。

| 执行流 | 关联控制任务 | 分支 | 独占文件与交付 |
| --- | --- | --- | --- |
| 版本化主数据和coverage | 204-A03-02、A06局部 | `codex/od204-wave4-reference` | 新增 `data/instrument_reference.py`、`pipeline/coverage_service.py`及tests；日历、生命周期、别名、来源/版本/范围证据；半开查询窗口、未知起点及缺口准确映射 |
| 股票reviewed job | 204-B02-01、B06局部 | `codex/od204-wave4-stock-job` | 新增 `pipeline/stock_daily_job.py`及tests；复用严格wire/parser/normalizer、raw artifact与合同writer；只注入fixture响应，默认disabled，来源verified仍False |
| 单任务定义导入原型 | 204-D05-02局部 | `codex/od204-wave4-job-import` | 新增 `job_definition_store.py`、`migration_apply.py`及tests；control metadata定义、冻结计划/hash/审核/目标指纹校验、幂等导入；不启动Run、不迁事实/执行/checkpoint |
| 持久worker | 204-D02-04、D03-01局部 | `codex/od204-wave4-worker` | 新增 `pipeline/reviewed_worker.py`及tests；子进程只接plain JSON，父端负责claim/heartbeat/取消/fencing/同事务发布；单次或有界执行 |
| 入口与角色 | 204-D03-03局部 | `codex/od204-wave4-entrypoints` | 新增 `reviewed_cli.py`、`pipeline/runtime_roles.py`、tests及未安装的systemd模板；CLI/APS共用提交SPI，API/scheduler/worker/legacy角色互斥规划，不自动启用 |

root独占总路由、启动配置、Alembic序列、依赖锁、共享schema和quality reference/census，负责独立审查、cherry-pick、跨模块测试及文档。各分支从第三批集成代码开始，执行器进程组修复由root统一合入；不把其他代理未交付模块作为开发前置。

先分别验证各模块，再集成定义store迁移和worker/入口、股票job、coverage，最后串联actual REST。control metadata和warehouse保持独立迁移；不宣称跨库原子提交。原API/legacy启动默认行为在准备好显式角色配置前保持现状，不默认双开新旧scheduler。

## 验收门槛

- 所有数据输入为明确合成fixture；worker、raw文件、SQLite进程/数据库行为是真实执行。记录两者边界，不能升级成真实源或自然周期通过。
- 多入口相同occurrence只入队一个Run；dry-run无持久副作用，提交回执不代表执行成功。worker重启、竞争、取消、超时、租约丢失及旧token均不能绕过事实写fence。
- 新任务定义导入默认disabled；重复幂等，计划/参数/hash漂移、未审核映射、未知/错误目标与冲突必须拒绝。保留1,103任务总分母，10条helper单列。
- coverage绑定dataset/source/instrument/publication及版本化证据，不从现有最早行推断上市日；未知边界和未归档snapshot保持UNKNOWN/SOURCE_LIMITED，不生成缺失bar。
- 新增文件执行Ruff全规则/format、严格mypy、Bandit；data/pipeline目标语句与分支覆盖至少90%，其他新增生产模块至少85%。整仓make gate失败状态单列，不用定向测试代替。

真实Provider网络限流、全局并发、原始对象崩溃回收/保留策略、生产权限及备份恢复仍需后续工作。此次不修改原项目203脚本、运行中任务、生产DDL、systemd或API开关。
