# 验收与切换方案

本矩阵中的生产、全范围、端到端和cutover验收均为 `NOT_RUN`，除非下方记录了与该验收ID相符的当前证据。源码/离线PR验收只更新精确代码范围，不等于系统已迁移。

## 当前基线与限定验收（2026-10-31 更新，Asia/Shanghai）

**2026-10-31 基线**：AFI `dev` HEAD 为 `b825f921476b6e698881e1be68993c8a4ac610e1`，OpenData `dev` HEAD 为 `373211d246ab3099ac8c551681c0f1703fcbd964`。该基线不包含本次文档改动；后续执行必须记录执行时的新 HEAD 及 dirty diff hash。

**2026-10-30 历史快照**：本轮编辑这些计划文档之前，AFI `dev` 与 `origin/dev` HEAD 为 `73c7b2f7537cacab2ab75daf4381e850a0977b9b`，OpenData 两者 HEAD 为 `cc79654171bd00b00d9909f7973547a10790a945`；当时两仓工作树干净。

| 已合入交付 | 可确认范围 | 仍未通过的验收 |
| --- | --- | --- |
| OpenData #132 签名恢复日志 | 限定隔离回归487项通过、1项既有OpenAPI检查明确deselect；full-follow mypy有3项既有诊断。 | job仍disabled/unregistered、无scheduler和生产签名器；ledger与日志发布没有原子链接。不能关闭AC06/AC13/AC14或真实历史验收。 |
| OpenData #133 CSI500历史对账器 | 限定合成回归68项通过、statement+branch 96.77%、0项排除。 | 未验证真实来源、calendar、source grant/retention、生产DB/调度或实际覆盖；不能关闭AC05/AC10/AC14。 |
| AFI #193 snapshot授权策略 | 纯策略的离线行为已验收。 | 授权持久模型/迁移仍在本地开发中，未合入当前 AFI HEAD、未验收；尚无可信grant registry/数据库签发撤销、route/task接线和读取/保存前复核；不能关闭AC09或AC18。 |

**2026-10-31 更正与新增证据**：AFI #201（`1af1366cccbdeef57d7c84c15820d556124c8cf8`）已合入精确 snapshot grant 的 ORM 模型与 Alembic 迁移 `20261030_stock_analysis_snapshot_grants`，因此上表 #193 行“授权持久模型/迁移仍在本地开发中”只适用于 2026-10-30 时点。当前存储默认为空，不签发权限、不认证签发人、不强制完整审计链；该合入提交也没有可信 adapter、route/task 接线、读取/保存前复核或数据库级 UPDATE/DELETE 保护；AC09/AC18 仍不能关闭。AFI #202（`076caa979498f0e930f5454bf7b48b766e3d29e1`）新增固定 stock-daily publication reader，但未接业务路径/授权/fallback，且上游路由当时硬禁用（#150 后改为默认关闭的容量门禁，默认仍返回 404）。OpenData #144–#149 只交付隔离 source-gate 样本准备、离线缺口对账、当时硬禁用的 v2 日线路由、job 请求预算、MySQL 反射 CHECK 校验和模拟 THS 的 MySQL 竖向验收夹具；提交与文档未记录测试通过数，均不构成真实源、生产部署、自然周期或历史覆盖证据。

**2026-10-31 Wave 15 合入与 CI 状态**：OpenData #150（`a76b48580c2f71ac3dc6a045a05edafba1f896e5`）合入默认关闭的股票日线容量门禁、仅执行回补执行器/CLI 与跨仓/回放 fixture；#151（`56d4cb38869c0fb8114c917be78e720506f659de`）合入 opt-in Fuyao 六 scope 真实字节回放（1 项通过、52 项观察 13/13/7/7/6/6，六个 manifest 实体 hash 校验）；#152（`373211d246ab3099ac8c551681c0f1703fcbd964`）合入离线当前 A 股 universe 候选（SZSE 真实样本 2,905 条、0 冲突；分页/完整性 `UNKNOWN`、无退市生命周期、`universe_census_attested=false`，SSE/BSE/Fuyao 真实响应体 `NOT_RUN`）；AFI #204（`b825f921476b6e698881e1be68993c8a4ac610e1`）合入股票日线精确 grant 扩展、默认关闭的授权 adapter、迁移与跨仓/回放测试（138 项定向）。这些只推进 `CODE/OFFLINE`，不关闭 AC05/AC09/AC10/AC14/AC17/AC18：容量门禁不是数据授权，Fuyao 回放不是实时来源，universe 候选不是权威全 A 分母。**CI 不是绿色**：上述 PR 按用户要求在 CI 清理前合入，已知 OpenData quality gate 与 full-history secret scan、AFI Governance Gate（PR body，合入后已更正）、Backend Security Scan、Doc Links、No Generated Artifacts 与 MySQL 9.4 Contract 失败；修复作为独立后续跟进，不能据此写成已通过。

用户已声明AkShare、Fuyao可用于自动采集、保存及两个内部服务间使用；该声明无需重复询问，但具体AkShare函数的上游产品/endpoint、dataset/市场/历史/频率/留存范围仍须映射并记入运营grant。用户目标范围为全A股，包含计划定义的北交所及退市证券。当前API尚不支持BSE是实现限制，不得作为缩小全集分母的理由。完整范围的判定须有每个纳入交易所的当前证券目录、退市证券与跨板/换码事件、稳定身份及实际分页完整性证据；任何一项未知时全A股完整性保持 `UNKNOWN`。

近期可并行准备、但按依赖串联验收的工作见 [SUBAGENT_TASKS.md 当前基线与近期执行矩阵](SUBAGENT_TASKS.md)。核心顺序是：只读刷新实际运行清单和目标身份 → 冻结逐交易所主数据/分页及来源grant合同 → 建立真实源到原始工件/仓/API的受控样本 → 按完整instrument×dataset分母对账head/interior/tail → 评估跨进程预算及旧worker/permit fence → 满足各域门槛后进行自然周期、备份恢复和唯一写者切换。真实数据请求经统一预算，不能因五路并行而重复扩大供应商流量。

## 1 验收矩阵

| ID | 验收场景 | 通过标准与所需证据 | 主责与复核 |
| --- | --- | --- | --- |
| AC01 | 范围与基线 | 重新冻结两个仓库和未提交差异hash；源文件、实际DB任务（含inactive）、systemd/cron/worker、进程、表、消费者、OpenData重叠能力均有带环境身份/采集时间的清单；各自分母明确且双向anti-join无未解释项。旧盘点中的1,066个脚本候选和1,103个任务只能作为历史快照，不能代替当前刷新或被当作现行总数。 | A，D/E复核 |
| AC02 | HTTP契约与兼容 | v1旧消费者fixture保持；v2 schema/错误/时间窗口/权限、空页、游标终止和版本兼容正反例通过；不静默截断 | A/E互审 |
| AC03 | 精确身份和范围 | 返回错symbol/venue/currency/频率/复权、超范围、重复键、混页publication均被拒绝；HTTP200不掩盖语义错误 | E，B/C复核 |
| AC04 | 金融语义 | 七类资产及其他主题逐数据集验证原生/标准字段、单位、日历、时区、复权、有效期、空值；NAV/收益/价格、精确合约/连续/TAS分开 | B/C互审 |
| AC05 | 全历史覆盖 | 对全A股目标范围按交易所建立当前与退市证券分母，以权威全市场目录、实际分页终止/总量/版本证据核验完整性，并保留跨板/换码和稳定instrument身份。对每个`instrument_id × 必需股票dataset`分别确定独立有证起点和目标终点：活跃证券从独立上市/挂牌起点核到验收时按有证来源发布周期应已到达的最新预期业务日及对应publication watermark；退市证券核到独立证据支持的有效终止边界，并按该dataset的预期业务键/报告期核对。逐证券×数据集检查head/interior/tail与缺失分类；`request_end`若早于相应目标终点，只能证明有限窗口，任何短窗口/分区迁移/样本请求都不能完成全历史回补。起止边界、交易所日历、分页、生命周期或source证据未知/受限时保持UNKNOWN/SOURCE_LIMITED，不得用MAX/COMPLETED、当前目录、总行数或成功请求宣称完整。当前API尚不支持BSE时保持NOT_SUPPORTED/UNKNOWN，不能从全A范围删除；对应新增控制任务为`204-B05-03`。 | B/D，A复核 |
| AC06 | 发布和崩溃一致性 | 在raw/ODS/DWD/publication/watermark各边界故障注入，读不到半批；重复提交不重复事实；跨库outbox可恢复 | A，D复核 |
| AC07 | PIT与研究重放 | 同snapshot两次运行输入哈希一致；未来披露、未来公司行动、后来修订不能进入过去as_of；未知可得性不伪装已知 | E，A/B复核 |
| AC08 | 性能和故障消费 | 冻结硬件/数据量/并发/索引下记录p50/p95/p99与内存；分页/导出遵循上限；超时/429/503有界重试；API故障不调用旧数据源 | E，D复核 |
| AC09 | 权限与许可 | 普通读Key不能ingest/执行任意脚本/看ODS敏感域；请求主体对目标dataset/instrument/purpose具精确READ_DATA，且source grant覆盖实际供应商产品/endpoint/市场/历史/用途；跨租户/封存研究集/导出越权失败；grant须在排队后台任务实际执行、读取前和报告保存前复核，吊销/轮换/过期生效，日志无密钥。服务身份不能扩大用户授权。 | A，E复核 |
| AC10 | 来源与质量 | 每个数据集有来源产品/endpoint和实际请求参数证据；源真实样本→原始响应字节/脱敏manifest→规范库→发布API逐字段对照；分页终止、重复/遗漏、时间/单位及字段漂移可复核，源空和质量拒绝分开；未具备真实源证据不标verified。用户概括性授权声明不代替AkShare函数到实际上游产品的映射。 | B/C互审 |
| AC11 | 逐脚本与逐任务适配 | 每个旧脚本/任务有映射与处置，参数/频率/业务范围不漏；新任务默认disabled；辅助文件不生成task；合并任务保留旧身份映射 | B/C，D复核 |
| AC12 | 存量迁移与环境防线 | 先验包/环境/库身份；错误目标立即退出；dry-run使用只读角色且无业务持久变化；分区行键/值/元数据/证据hash对账 | D，A复核 |
| AC13 | 单写者与运行恢复 | 两调度器竞争、跨进程/worker source额度、worker租约过期后恢复、手动/自然槽重叠、中途kill、取消与重试；交接每步崩溃后重入；每业务写域只有有效owner，旧token写失败。跨版本启用配额V3前，须可信证明所有V2 worker已停止、已提交permit已耗尽或被强制隔离，旧进程凭证/网络请求路径被fence；无可信verifier时V3默认禁用并保留V2工作路径。另验证THS HTTP所有发送入口在预留预算前失败关闭、release持久化和并发上限；人工声明不能替代运行态证明。 | D，A复核 |
| AC14 | 自然运行与freshness | 小时任务连续48次、日任务连续7个应运行交易/发布周期；周/月任务至少2次/1次自然周期，另做确定性重放；每周期source→published→coverage可追踪 | D，B/C复核 |
| AC15 | THS旧缺陷接续 | D04：默认dry-run独立连接确认无ODS/DWD/发布/覆盖写入；D05：首/中/尾缺口续跑补齐，同输入幂等，部分失败可恢复；替代路径也适用 | D/B，A复核 |
| AC16 | 产品与管理UI | 七类行情、搜索、主题、策略准备、缺失/过期/权限/故障场景；opendata任务创建/暂停/取消/补数/日志/DQ；旧书签有明确迁移入口，权限不扩大 | E/D互审 |
| AC17 | 切换 备份与回滚 | 在隔离环境恢复metadata+warehouse+artifact并校验；演练旧→新、新→旧writer；回滚不丢新已提交数据、不更改旧snapshot；测量RPO/RTO | D，A/E复核 |
| AC18 | 最终只通过API | ai构建/安装包无源SDK/采集启动hook/仓库DSN；运行网络限制为opendata数据API，DB权限撤销后全部数据消费测试仍通过；代码、配置、cron和实际进程联合核验 | E，A/D复核 |

上述自然周期门槛是本迭代建议值，M0可依据实际频率和源SLA调整并记录理由，不能事后为绕过失败缩短窗口。月度任务未到自然触发点时可以DEV_DONE，但natural_cycle仍NOT_RUN；可先阶段交付，整体条件不能冒充已满足。

质量核验采用独立oracle：迁移前后分区键集合和规范序列化哈希全量比对；金融值抽样从源原始工件独立解释，与实现的同一转换函数不能互作证明。价格按tick/Decimal规则比较，浮点指标用每域记录的绝对/相对容差；不得统一套一个误差容忍所有单位问题。所有非等值必须分类，裁决前隔离而非自动通过。

## 2 存量迁移对象与顺序

| 对象 | 迁移策略 |
| --- | --- |
| 数据源/接口/脚本登记 | 保留legacy_id/hash/配置版本；变成Provider/Job定义映射，秘密重新注入 |
| 任务/执行/claim | 任务定义转换后disabled；历史执行作为只读历史导入；过期claim保留审计但不激活旧租约 |
| 主数据/日历 | 先迁生命周期/别名和日历，再迁事实，无法确认身份的行保留legacy隔离层 |
| 原始证据/ODS/事实表 | 分区导出，row_count、业务键hash、值hash、语义标签、artifact hash；源文件可分块搬运 |
| 覆盖/DQ/publication | 以事实重算为准，旧“完成”标记不得直接复用为新认证 |
| progress/cursor/cooldown/universe | 携带原版本、任务身份、已验范围和校验和转换；不重置至零，不直接沿用旧有效lease |
| 股票成交额sidecar/语义白名单/日历证据 | 作为独立必要资产登记，保留关联键、复权与证据版本 |
| ai研究/回测工件 | 保持原内容hash/授权及引用不变；新运行用opendata snapshot，旧引用有只读解析入口 |

采用expand/migrate/contract：先增加兼容schema和新读能力，迁移并验证，再切写者和消费者，最后回收旧入口。生产迁移按实际数据量测量窗口，不在请求处理时执行DDL。元数据库与仓库迁移都需从受支持旧版本升级及恢复演练。

历史大表建议先在一致性快照下批量复制，再以可靠的提交序列/updated watermark或数据库CDC补增量；没有可靠变更标记时，最终切换暂停写入并对变化窗口重拷/复核，不能只按MAX业务日期追加，因为旧日期也会被修订。工具可重入并记录完成分区。数据库名称和地址按环境清单校验，不能靠文件名推断目标库。

## 3 单数据域切换步骤

切换单位不是单个task：**同一数据集/来源/目标sink的全部写入入口**必须一起受控，包含多个旧task、手工CLI、systemd、补数shard与派生写入。

1. **准备**：冻结波次清单、源/目标环境指纹、两仓commit、合同/镜像/迁移版本、旧job映射和回滚条件。备份可恢复；目标读能力先部署，新job仍disabled。
2. **历史复制**：用旧数据快照和源工件导入目标staging，逐分区对账，错误进入隔离清单。导入只复制事实，不新抓一次全市场。
3. **影子读取**：同一旧源证据/数据版本分别查询两条链，比较键、值、单位、freshness、覆盖和业务页面。影子代码禁止写生产发布表，不重抓全量供应商数据。
4. **停止旧派发**：对波次加维护/禁止手动执行标记，停用对应旧jobs/timers/shards，等待在途退出。若更新跨运行配额/worker版本，还要枚举所有旧版worker、重启策略与已提交permit，核实permit已完成/取消/失效；不能仅观察新版本计数器为空。超过预算用现有取消机制终止，记录最后有效run和提交水位。
5. **封写并补尾**：用DB写权限/网关fence使旧身份无法再写受迁域；对 source quota 切换，还须用可信控制面验证旧worker即使复活也不能访问供应商、旧permit无法继续发请求。人工停机声明不能替代可验证证据。没有可信verifier时，新quota版本保持disabled并继续使用经当前路径接受的旧版；不得切成新门禁却遗留可绕过门禁的旧worker。复制最终增量及修订，对账通过后在唯一ownership记录中递增epoch、CAS转移到opendata。跨库环境不靠两个各自的布尔开关保证排他，使用可验证的凭据封写和唯一交接记录。
6. **启用新任务**：导入断点、冷却和范围；依据上次成功occurrence及实际发布日重算下次运行和补偿槽，不跳过切换期间的应运行周期。仅对应opendata writer身份获得写权。
7. **切换读流量**：按数据域/租户/场景从内部测试→小流量→全量；在同一次业务请求及整个回测中固定数据版本，不能随机混用新旧值。
8. **观察**：验证自然周期、实际数据发布、覆盖与告警，同时确认旧端口/调度/手动入口无写权限。性能、超时、错标的/错单位、缺口、重复写及越权任一重大问题触发回滚评估。
9. **收尾**：证据通过后标该域CUTOVER_ACCEPTED。保留旧只读快照和安全回滚制品至少30天，且满足来源许可、备份及恢复要求；旧在线采集必须停用。到期后审查再删除旧表/文件/密钥，不把删除与首次切换放同一次发布。

全量切换完成后ai撤掉仓库账号和出网采集权限，禁止异常时重新启用AKShare/THS/其他源fallback。兼容期未切域的旧代码有明确台账与退出日期；这属于过渡状态，不得标最终ai-only-REST完成。

### 交接状态与崩溃重入

唯一全局交接账本设在opendata metadata库，按 `dataset/source/sink_partition` 主键记录owner、epoch、阶段、两端环境身份、尾部manifest及receipt；只有D的交接服务可推进，A复核权限。worker不能自行修改owner。每个仓库写入事务同时验证本仓sink-fence表中的epoch/允许身份并锁定对应记录，事务完成后才推进watermark；旧任意SQL脚本在改造前不能只靠这一逻辑防线，必须撤销其写权限并验证拒写。

全局metadata与两侧仓库不假设分布式事务。顺序为先确认旧侧封写，再提交owner，再授予新侧权限/安装新epoch；各步有独立回执，状态不明即停止，不自动开任一方。若旧任务共用无法按表隔离的写账号，须先拆账号，或把共享该账号的全部sink作为同一切换组，不能以局部切换名义留下旁路。

| 持久阶段 | 重启/失败后允许动作 |
| --- | --- |
| PREPARED / OLD_DRAINED | 重查实际在途和入口；未证实排空不得封写后推进，旧owner不变 |
| OLD_FENCED | 独立测试旧身份拒写，确认fence/权限已生效；两边均不派发，重做最终增量 |
| TAIL_VERIFIED | 按manifest确认目标事实与旧最终水位一致，再CAS修改全局owner/epoch |
| OWNER_COMMITTED | 重查旧拒写与新owner；幂等配置目标sink-fence/新权限，新任务仍disabled |
| NEW_READY / NEW_ACTIVE | 校验新权限和epoch后启任务；按occurrence幂等补偿，重复enable不产生第二个run |
| 任意不一致或UNKNOWN | 保持封写，人工检查回执与实际权限/库状态；禁止凭超时推断交接成功 |

文件类sink同样通过发布服务及manifest控制，不给两端可变共享目录写权。回滚执行对称流程并递增epoch，不能复用旧token。AC13/AC17逐点在停旧、封旧、尾部复制、owner CAS、新权限配置及新任务启用后注入崩溃，验证可重入、无双写且已提交事实不丢失。

## 4 回滚的两种层次

**读服务回滚**：优先回退到兼容的opendata上一版本服务/上一publication；紧急期间ai可读已授权、已冻结、明确显示时效的本地REST工件。交互页面能展示过期标记，严格新鲜度的研究/交易准备拒绝运行。不得因故障静默使用不同来源，或借用管理员凭据。

**生产者回滚**：先停止opendata派发、排空并封写新worker；保存新已提交publication和新增raw；对齐两个仓库的尾部/修订数据和checkpoint，给旧writer授予新epoch后再启动旧任务。恢复旧writer只用于受控过渡回滚，必须留审计并重新安排切换。不能同时打开两侧，也不能整库回滚覆盖新数据和用户研究结果。

跨仓发布可独立回退应用版本，前提是schema仍向后兼容。不可逆DDL/数据删除推迟到回滚窗口后，单独评审；一般优先forward-fix。回滚触发阈值在M0冻结：身份/单位/PIT/权限错误零容忍；关键数据连续2个应到周期未发布、API错误率超过1%持续10分钟等为初始运行阈值，按真实负载调整并留证据。

## 5 验证层次与运行命令

开发阶段以录制/脱敏fixture、独立数据库、HTTP模拟和故障注入验证逻辑；必须连接上游的测试单独标记，受统一配额控制。单元测试不能替代真源、迁移恢复和自然调度。

以下是仓库既有命令入口，实际执行前由各owner确认当期依赖和测试路径，输出与两仓源码SHA绑定：

```bash
# ai-for-investor后端，在 src/backend 下按变更选用相关用例
pytest tests/market_data_platform/test_opendata_provider.py
pytest tests/test_akshare_scheduler.py
# ai-for-investor前端，在 src/frontend 下
npm run typecheck
npm run build
# opendata，在仓库根目录；先盘点现有baseline，再跑受影响用例及要求的gate
make gate
```

新增contract、cutover、全历史、故障注入用例名和命令在对应PR落档；此处不把未创建的测试文件伪装成现有命令。受影响测试通过后执行发布必须的综合检查，不能通过删失败/跳过、降低分母或复用旧SHA的绿灯发布。

## 6 证据和状态报告

每份验收收据包含：case_id、工作包、数据集/任务/脚本ID、两仓commit及dirty hash、依赖/镜像/配置版本、schema/publication/raw hash、环境身份、范围/业务键/时间窗口、命令、开始结束时间、预期/实际、失败/跳过、复核人。收据不含密钥或私人数据；原始证据在受控存储，仓库保存可定位的脱敏索引。

每周分别报告：已处置脚本/总脚本、已映射任务/总任务、DEV_DONE、SOURCE_VERIFIED、数据覆盖状态、DEPLOYMENT_VERIFIED、自然周期、已切域和未闭源限制。历史完整性未满足的项目不能凭SOURCE_LIMITED或运行成功转为PASS。

阶段发布允许核心先切，整体验收要求本迭代冻结的全部必需项通过。源不可用等外部条件可单独BLOCKED并保持需求开放；若产品正式调整范围，记录调整前后分母和影响，不改写原历史要求。
