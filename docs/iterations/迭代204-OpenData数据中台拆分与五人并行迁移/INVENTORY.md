# 现状盘点与迁移台账

盘点日期2026-10-26。本轮读取两仓源码及已有记录，没有重新查询生产数据库，也没有执行脚本采集。源码统计、文档中的运行快照、拟建能力分开记述。

## 1 ai-for-investor源码脚本普查

[script_migration_inventory.csv](script_migration_inventory.csv) 是本次生成的逐文件清单：递归扫描 `src/backend/app/data_fetch/scripts/**/*.py`，排除 `__init__.py`，使用AST和路径分析，不import或执行源码。每行含源路径、SHA-256、资产/频率候选、静态角色、AKShare使用线索、迁移路线、目标数据集、状态、owner和说明。

| 统计口径 | 结果 |
| --- | --- |
| 非init Python文件 | 1,066 |
| 可识别入口 | 1,056：fetch_data 886、run 168、main 2 |
| 无上述入口，需辅助文件审查 | 10 |
| 目录名频率候选 | daily 685、hourly 86、weekly 268、monthly 21、unspecified 6 |
| 责任候选 | B 607、C 449、辅助审查10 |
| 共享AKShare writer引用 | 1,051个文件；其中26个另有直接AkShare import |
| 仅文本线索/无静态AKShare线索 | 7 / 8 |

1,066不是数据集数、数据库任务数或可迁移成功数。AST入口只是候选；动态调用、重复脚本、多个任务共用脚本、单脚本写多表、source已失效等需结合运行配置审查。所有目标数据集和Provider等价关系保持待映射，不因名称相似自动填入。

本清单尚不包含 `src/backend/scripts/`、根 `scripts/ops/`、独立provider、动态服务fallback、systemd/crontab、opendata既有脚本。D01/E01/B01/C01须将它们纳入正式全入口清单；因此本CSV不能被用作“所有任务已盘清”的证据。

## 2 当前代码与运行记录

| 事实 | 依据与迁移影响 |
| --- | --- |
| ai有脚本/接口/表/任务/执行/claim/控制模型 | `src/backend/app/models/akshare_mgmt.py`，`src/backend/app/api/akshare/`；控制面迁移需包含执行历史和授权 |
| ai调度仍由启动过程管理 | `src/backend/app/startup/orchestration.py`、`services/akshare/scheduler.py`、`scheduler_service.py`；迁出后删除采集启动hook，保留业务任务编排 |
| ai已有opendata日线适配 | `services/market_data/opendata_provider.py`、`opendata_contracts.py`：股票1d、单页1,000、总50,000、v1当前页读取；仍接本地store/publication |
| ai仍有源直连消费者 | `services/market_instrument_dynamic_data.py`、`stock_analysis/data_collector.py`、`asset_research/providers/akshare.py`；还需盘点scanner、signal、realtime和全部网络路径 |
| ai有完整数据管理UI | `src/frontend/src/views/data/`下任务/脚本/执行/表/接口/治理/同步页面，`src/api/akshare.ts`；迁管理、留业务行情与预检 |
| opendata有统一查询和client | `opendata/api/data_query.py`、`opendata_client/opendata_client/client.py`；复用v1但不把当前视图当可重放快照 |
| opendata有Provider与ODS/DWD | `opendata/data/providers/`、`data/domains.yaml`、`pipeline/`；扩展现有领域和发布管道，不新建第三套框架 |
| opendata原生model持久化是局部能力 | `opendata/services/provider_model_store.py`的模型映射只有FredSeries、BlsSeries、EquityHistorical；这是该路径覆盖，非整个仓库覆盖统计 |
| opendata调度/手工run有持久化缺口 | `services/scheduler_service.py`、`api/pipeline.py`内存run跟踪；DB任务定义不代表跨进程可恢复执行 |
| opendata仍有legacy AKShare调用 | `services/scheduler.py`、`services/data_acquisition.py`、既有data-fetch脚本；与ai迁入任务一起收敛 |
| opendata分钟与导出能力有限 | `data/minute_archive.py`、`api/minute_data.py`；单机Parquet、有界JSON；普通CSV和native NDJSON导出不能替代通用异步快照下载 |

`services/`在上表ai条目中相对于 `src/backend/app/`，opendata条目使用其仓库根路径。精确实现是否上线由后续环境验收证明。

203 最新相关台账（历史本地路径，当前 checkout 未包含该文件）：`docs/iterations/迭代203-全量数据补齐与持续调度治理/EXECUTION_STATUS.md`；当前仓库可核对的相关文档见 [迭代203-底层依赖收口与产品化基线](</home/yun/Documents/ai-for-investor/docs/iterations/迭代203-底层依赖收口与产品化基线/README.md>)：

- 2026-10-26 15:26记录：1,103个task，1,098 active，5个helper inactive；69 curated是子集，不能继续以69作为总迁移分母。所有task含inactive都要去向清晰，未来新增项按变更控制纳入。
- 2026-10-25记录六个user timer/service：full-history-recovery、policy-expiry-watchdog、dce-browser-capture、dce-option-daily、stock-tail-daily、stock-amount-daily；另有四个ETF NAV shard。实际已安装配置、checkpoint和进程须开工时重新只读核对。
- 2026-10-26 15:10记录一次误连backtrader_web事件：外部脚本通过editable install导入错误仓库app，误改任务后回滚。迁移工具在写前必须校验代码来源、环境及数据库身份。
- 启用后的stock验证批次出现失败，enabled不等于verified；旧active标记不能作为新任务启用凭据。

203早期README/CSV的脚本数、task数、active数会过时。本轮静态清单绑定每文件hash，后续运行清单绑定查询时间和环境；不得混用不同日期的数值计算完成率。

## 3 opendata既有工作复用

项目路径：`/home/yun/Documents/opendata`，HEAD `61800c18`。本轮检查时工作树无Git状态输出。其[迭代2计划](/home/yun/Documents/opendata/docs/迭代计划/迭代2-统一Provider架构与全量能力补齐/README.md)与[OpenBB迁移提案](/home/yun/Documents/opendata/docs/proposals/openbb-migration/README.md)明确自研Provider，零OpenBB运行时依赖；本次用户已再次确认这一选择。

正式模型CSV有350条provider×model项、202个模型身份；当前CSV的implementation状态为5 DEV_DONE、13 IN_PROGRESS、332 NOT_RUN，live全部NOT_RUN。另一份离线验收plane记录更多OFFLINE_ACCEPTED，不等于implementation完成或来源验证。旧文档的lint/gate结果也不等于当前HEAD结果，A01/D01重新记录基线。

本迭代不另起一套350模型开发清单。新增交叉表：`legacy_script/task → 数据需求 → opendata domain/provider/model → 迭代2任务ID → 204工作包`，重叠工作复用实现和证据，未重叠需求新增数据契约。先满足ai真实迁移范围，同时保持opendata既定全量能力需求不丢失。

## 4 正式台账要求

M0在opendata仓库建立唯一可维护的迁移manifest，ai本计划只保存起始快照和发布版本引用，避免两份长期手工台账漂移。D维护导出/校验工具，A负责schema，B/C/E补齐域和消费关系。

| 台账 | 必填字段 |
| --- | --- |
| 文件/脚本 | legacy_path、sha256、入口/辅助角色、调用源、版本、业务域、候选处置、owner |
| 任务/入口 | legacy_task_id或service/cron身份、script_hash、参数hash/脱敏参数、cron/timezone/calendar、active状态、next/last occurrence、source预算、run方式 |
| 数据集/落点 | dataset_id/schema、source/model、原/目标表或文件、业务键、字段/单位、时间语义、adjustment、生命周期/universe、许可及保留 |
| 覆盖/质量 | requested_start/end、inception证据、source_retention_start、head/interior/tail、质量规则、PARTIAL/UNKNOWN/SOURCE_LIMITED、证据与复查责任 |
| 消费者 | repo/file/callsite、API/页面/研究场景、身份/权限、频率/时效、snapshot需求、读写/缓存、切换状态 |
| 交接 | new_job_id/version、sink_partition、writer_owner/epoch、checkpoint版本、receipt、启停/回滚时间、自然周期状态 |

导出不读取或打印明文凭据；只记录secret引用及版本。台账每次更新保留时间、环境和基线，新增/删除/合并项目有审计原因。每项可同时有多个source/consumer，不能强制一对一掩盖实际关系。

## 5 既有问题进入204的方式

| 事项 | 当前含义与204归属 |
| --- | --- |
| 202 D04/ D05 / WP03 | THS dry-run内部提交、按series存在跳过内部缺口；本轮D05/B05及AC15必须在保留或替代链路验收 |
| 197本地事实权威 | 将事实、发布、覆盖权威搬到opendata；ai仅保留不可变研究工件，E04/A04保留旧引用 |
| 203 B45 | DCE连续别名等遗留数据保持原始证据，C02/C06隔离精确/连续/TAS，不污染目标规范表 |
| 203 B52 | 早期可转债universe与未知身份历史，B03/B05保持边界，不能凭当前源最早日宣称上市全历史完整 |
| SZSE ETF期权源限制、EM FX WAF | C02/C03记录真实范围、可行替代及差异；不重试绕过限制，不伪造历史 |
| EM指数全universe、B38原始词面证据 | B04/B05重新核对最新版台账，并保留未闭需求与语义证据 |
| SHFE四个归档空日 | 203于10-24已有恢复记录，迁移复用原始工件和229行核验，不把旧缺口重新误报未修；两行矛盾OHLC单独保留源复核事项 |
| 新启用legacy任务失效 | B06/C07按失败类型处理，D03设置全局限流/冷却，迁入默认disabled |
| opendata迭代2门禁与缺口 | A01先复测当前基线，按依赖处理；不将文档注册或离线plane绿灯当生产就绪 |

上述源限制是既有记录，实际切换前须用最新状态复核；已经修复的项保留证据迁移，未闭项继续开放。

## 6 高风险假设与负责人

| 风险 | 发现信号 | 处置/负责人 |
| --- | --- | --- |
| 所谓“直接换OpenBB调用”覆盖不足 | 无等价model、字段/历史深度不同 | 用户已选自研；B/C逐源适配，A裁决契约 |
| 全量脚本实际重复度低，工期增加 | 20例样本定制/失效比例高 | A重估；按域重分B/C/E任务，不删分母 |
| 已恢复历史和运行中断点丢失 | 源库修订、缺原始工件、游标格式变化 | D05版本化导出/对账/恢复；B/C审覆盖 |
| 两边同时写或旧worker复活 | 同sink多个入口、过期lease仍提交 | D02/D07单一ownership、权限fence、并发负例 |
| 错源、错标的、错币种仍HTTP200 | 字段同形但identity不同 | E02严格响应校验，AC03零容忍 |
| as_of或复权泄露未来 | 旧源无披露时间/因子仅当前值 | A/B/E隔离unknown、固定revision、PIT拒绝 |
| 源许可/Key/配额不满足 | policy引用无权利审查、真实调用失败 | A/B/C审用途、批准来源、保留BLOCKED |
| 研究权限被共享服务Key绕过 | sealed集可被普通API再次取得 | E04/A05跨系统授权测试，按租户/用途隔离 |
| REST吞吐或可用性不足 | 大规模分钟/多标的超时 | A05/E04快照导出、缓存、索引/负载测试；不退回采集直连 |
| 依赖混装连接错误环境 | 包路径/库身份与manifest不符 | D01在写前失败关闭，隔离安装包/镜像 |

M0待核实但不阻碍规划的输入：实际数据量/增长与磁盘预算、部署主机与数据库版本、source Key/许可、5名成员技能和投入比例、核心数据SLA、生产维护窗口与告警接收人。默认复用当前技术栈和用户确认的自研架构，核实结果进入版本化决策记录。
