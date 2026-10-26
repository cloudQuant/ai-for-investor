# 迭代204子代理任务清单

本清单把 IMPLEMENTATION_PLAN.md 的35个工作包细化为 **87个**可独立分派、可验收的子任务。它是执行拆分，不是完成报告；当前7个子任务为DEV_DONE，6项为IN_PROGRESS，74项为PLANNED；第二批跨多个父工作包的局部交付另见WAVE2_STATUS，不以局部能力关闭整行验收。DEV_DONE仅覆盖该行交付，不会把父工作包标成完成，也不表示已合入dev、已部署或真实数据已验证。实际提交与验证记录见 DEVELOPMENT_STATUS.md。

第二批已按独占文件集成11条开发任务，第三批又分派6条任务，跨多个父工作包推进；其实际交付与剩余验收面见 [WAVE2_STATUS.md](WAVE2_STATUS.md)。下表保留完整任务验收门槛，库内能力或局部链路完成不会自动关闭要求外部证据、生产worker或完整业务场景的任务。

## 验收边界与并行约定

- `CODE/OFFLINE` 表示代码、静态资料、fixture、mock、owned SQLite 或离线对账可验收；它不证明真实源可用、全历史完整或生产部署成功。
- `REAL_SOURCE` 需要真实供应商/交易所请求或真实返回证据，记录数据集、标的/业务键、参数、观测时间、来源和许可边界；fixture不能代替。
- `DEPLOYMENT` 需要目标部署环境中的运行/权限/恢复/切换证据；本地启动不算部署验收。`NATURAL_CYCLE` 必须等真实源的约定发布周期到达并观察到结果；手工触发、mock和缩短等待不能代替。
- 混合类型的子任务只有分别完成对应验收面后才算该子任务验收。真实源不可得、历史保留不足或许可未知时，产出限制证据和复查条件，需求保留开放，不能填造成功状态。
- M1可由股票日线、标的目录、日历、覆盖、一个补数任务、一个自然调度和一个研究快照的代表样本启动。20个代表案例、首批六个子任务和本清单不要求先把1066个文件全盘完毕；批量盘点与M1并行。代表样本覆盖之外的文件仍留在范围分母中。
- `owner/建议代理` 的 A–E 对应 IMPLEMENTATION_PLAN.md 的职责；括号内为已知子代理名。root负责总集成和跨仓裁决。六个首批任务由对应代理在各自隔离 worktree/branch 开发；其他任务可在下一波重分配。
- 每个子代理在自己的仓库隔离 worktree 和 branch 提交小 PR/提交；opendata 与 ai-for-investor 分别管理分支。root逐项 cherry-pick、review并运行与影响面相符的测试，先集成到本地集成分支，后续经PR合入 `dev`。禁止多个代理同时修改同一共享文件；共享 schema、总路由、依赖锁和 Alembic 序列由指定 owner 排队集成。发生接口变化先更新契约并让消费者同步，不把数周后的大批量合并作为计划。
- 前置依赖仅写本清单任务ID；空表示可直接开始。依赖链无环，部分任务可并行。工作包整体状态按 IMPLEMENTATION_PLAN.md 单独管理，子任务状态不可推导成父包 ACCEPTED。

证券/衍生品长尾任务进入开发时继续按一个模型族或不超过20个源条目拆执行批次，每批绑定独占文件清单和台账行；87项是当前控制任务，不要求把607/449个候选文件塞给一个长期子代理。并行数量依据依赖和资源预算调整。

## A：平台与数据契约

| 子任务ID | 父WP | 状态 | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-A01-01 | A01 | PLANNED | A / root | CODE/OFFLINE | 记录两仓基线提交、脏文件路径与哈希、运行时/依赖版本、数据库迁移head、工具版本；秘密只记录存在性，不读出或复制。 | — | 脱敏基线清单可重现；两个仓库身份和采集时间明确，脏改动有保留位置与恢复步骤。 |
| 204-A01-02 | A01 | PLANNED | A / root | CODE/OFFLINE | 建立所有权与ADR索引，标记共享契约、总路由、公共依赖、迁移序列、provider域、客户端和UI文件owner。 | 204-A01-01 | 每个共享文件有唯一集成owner；文档写明两个仓库的PR目标分支和集成责任。 |
| 204-A02-01 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 冻结v1兼容约束和v2 OpenAPI骨架：端点、认证、闭/半开区间、分页、错误信封、版本字段。 | 204-A01-01 | OpenAPI可解析；每项拟议能力标明现存或待实现；v1既有响应语义有契约测试。 |
| 204-A02-02 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 逐数据集身份、instrument、业务时间/事件时间/可得时间、单位/币种、Decimal、空值、质量和许可schema。 | 204-A02-01 | schema示例覆盖股票日线、基金NAV、曲线或财务修订中的不同语义；非法单位/日期可被验证器拒绝。 |
| 204-A02-03 | A02 | PLANNED | A / 契约代理 | CODE/OFFLINE | 提供黄金fixture、错误fixture和可本地运行的mock服务，供opendata API及AFI client并行开发。 | 204-A02-01, 204-A02-02 | 同一fixture能驱动服务端与客户端合同测试；含空结果、部分覆盖、越权、过期cursor和分页样例。 |
| 204-A02-04 | A02 | IN_PROGRESS | A / 契约代理 | CODE/OFFLINE | 加入OpenAPI兼容性门禁、schema版本规则和破坏性变更检查。 | 204-A02-03 | CI能拒绝至少一个故意破坏v1/已发布v2合同的样例；兼容扩展路径有说明。 |
| 204-A03-01 | A03 | PLANNED | A / 元数据代理 | CODE/OFFLINE | 定义dataset/schema版本、来源、负责人、许可和域注册表的元数据模型及首个迁移提案。 | 204-A02-02 | 唯一共享registry owner确认迁移序列；升级/降级或备份恢复边界有离线验证记录。 |
| 204-A03-02 | A03 | PLANNED | A / 元数据代理 | CODE/OFFLINE | 定义instrument稳定ID、别名生效区间、上市/退市/到期生命周期和交易日历版本接口。 | 204-A03-01 | fixture覆盖换码、退市、基金份额类别、到期合约、节假日及未知边界；不以当前代码回填历史身份。 |
| 204-A04-01 | A04 | IN_PROGRESS | A / 存储代理 | CODE/OFFLINE | 增加raw响应证据引用与受控artifact manifest合同，包含请求摘要、内容hash、采集时刻、状态和保留策略。 | 204-A03-01 | 单测证明密钥/Cookie不会进入manifest或日志；ODS记录可定位证据或明确SOURCE_LIMITED。 |
| 204-A04-02 | A04 | PLANNED | A / 存储代理 | CODE/OFFLINE | 建立ODS到DWD的来源血缘、转换版本、修订链、可得时点和固定publication/snapshot版本字段。 | 204-A04-01, 204-A03-02 | fixture中修订前后值可追踪；严格PIT未知的数据不能伪装成已知。 |
| 204-A04-03 | A04 | PLANNED | A / 存储代理 | CODE/OFFLINE | 定义候选分区验证、原子publication指针和跨metadata/warehouse receipt/outbox的可重放提交。 | 204-A04-02, 204-D02-01 | 故障注入证明提交状态不领先事实数据，重复receipt可幂等重放；不宣称跨库原子事务。 |
| 204-A05-01 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现兼容v1只读端点及固定latest-view行为，沿用既有闭区间和count语义。 | 204-A02-03, 204-A03-01 | 合同测试验证旧请求/响应；普通读身份不能触发provider抓取或写入。 |
| 204-A05-02 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现v2目录、标的、日历、records、coverage和snapshot只读服务的首批端点。 | 204-A04-03, 204-A03-02 | fixture验证publication固定、业务日期半开窗口、逐标的覆盖和稳定排序cursor；未发布分区不可见。 |
| 204-A05-03 | A05 | PLANNED | A / API代理 | CODE/OFFLINE | 实现分页/行数/响应体/超时边界、异步大导出入口、scope/许可门禁及稳定错误码。 | 204-A05-01, 204-A05-02 | 超限明确报错或返回导出状态，不静默截断；scope隔离测试通过，429/503语义稳定。 |
| 204-A06-01 | A06 | DEV_DONE（仅代码/离线） | A / dev_coverage | CODE/OFFLINE | 实现逐标的日粒度head/interior/tail缺口纯函数；输入预期交易日/生命周期边界和观测业务日期，输出缺口段及状态，不接数据库、不抓源、不判定上市边界真伪。 | 204-A02-02 | 纯函数单测覆盖首尾缺口、内部缺口、停牌/不适用、退市、空观测、重复输入和未知边界；父WP A06仍未完成。 |
| 204-A06-02 | A06 | PLANNED | A / 质量代理 | CODE/OFFLINE | 为首批dataset配置主键、重复、单位、时间、跨表和发布质量规则及严重级别。 | 204-A03-02, 204-A06-01 | 每条规则有数据集适用范围与失败样例；未知不被转换为默认0或COMPLETE。 |
| 204-A06-03 | A06 | PLANNED | A / 质量代理 | REAL_SOURCE | 为源受限/缺历史记录真实请求参数、最早可回溯点、许可/保留证据、责任人及复查触发条件。 | 204-B01-02, 204-C01-02 | 证据指向可审查的源响应/官方说明；未回传记录清楚标为未知或SOURCE_LIMITED并保留历史需求。 |
| 204-A07-01 | A07 | PLANNED | A / root | CODE/OFFLINE | 形成跨仓发布manifest和合同/依赖兼容门禁，绑定opendata commit、AFI commit、client版本、schema及数据publication。 | 204-A02-04, 204-A05-03, 204-E06-02 | manifest可重现这组二进制/契约组合；未验证的数据面单独标NOT_RUN。 |
| 204-A07-02 | A07 | PLANNED | A / root | DEPLOYMENT | 汇总最终范围、未迁项、源限制、回滚条件、运营owner与阶段发布说明，提交关闭/阶段发布评审。 | 204-A07-01, 204-B07-03, 204-C07-02, 204-D07-03, 204-E07-02 | 逐WP、数据域、源/仓/API、部署、自然周期和历史覆盖分别给证据；任何未通过项不被描述为全量完成。 |

## B：证券数据适配

| 子任务ID | 父WP | 状态 | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-B01-01 | B01 | PLANNED | B / 证券代理 | CODE/OFFLINE | 按冻结CSV分批处置607个证券候选资产，记录旧脚本hash、输入参数、数据集、provider、落库、消费者、许可和REUSE/EXTEND/CONSOLIDATE等决策。 | 204-A01-01 | 每个候选保留一个可追溯处置或待查原因；统计与原清单anti-join解释一致，不把文件数当数据集数。 |
| 204-B01-02 | B01 | PLANNED | B / 证券代理 | REAL_SOURCE | 选10个证券代表案例，实测简单、复权、财报PIT、多表、源限流/失效等源能力与字段语义。 | 204-A01-01 | 每例记录真实源、参数、时间戳、返回边界、许可待核项和成本；作为M0输入，不等待607项映射。 |
| 204-B02-01 | B02 | PLANNED | B / 证券代理 | CODE/OFFLINE | 完成股票日线M1样板Provider、标准映射和fixture，分离不复权价、成交量/额单位与源字段。 | 204-A02-02, 204-B01-02 | 黄金fixture稳定重放，唯一业务键和空值/单位合同通过；源真实性另由下一任务验收。 |
| 204-B02-02 | B02 | PLANNED | B / 证券代理 | REAL_SOURCE | 对选定股票真实抓取日线，核对源参数、交易日、原始响应、字段及许可/历史保留边界。 | 204-B02-01 | 样本与真实源可逐字段比对；上市起点证据与源最早返回日分开记录，异常不被填平。 |
| 204-B02-03 | B02 | PLANNED | B / 证券代理 | CODE/OFFLINE | 形成股票universe/上市退市、公司行动、复权因子版本和财报公告PIT映射规则。 | 204-A03-02, 204-B02-01 | fixture覆盖换码、退市、除权、前后复权锚定、公告时间与platform available_at；无证据时PIT标unknown。 |
| 204-B03-01 | B03 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立基金/ETF交易价格、单位净值、累计净值、万份收益和七日年化的独立数据集及映射。 | 204-A03-02 | 合同测试证明字段不混用、单位与公布时点明确；缺失NAV不会由交易价格补值。 |
| 204-B03-02 | B03 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立可转债个券与国债/信用收益率曲线的分离模型及证券字段映射。 | 204-A03-02 | fixture验证曲线tenor/日期/单位和个券价格、收益率不是同一表义；源/历史证据列待核项。 |
| 204-B04-01 | B04 | PLANNED | B / 证券代理 | CODE/OFFLINE | 接入指数定义、历史成分有效期和估值分母，支持退市证券与历史universe回测。 | 204-A03-02 | fixture按as_of重建历史成分；当前成分不被反向套用到历史。 |
| 204-B04-02 | B04 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立证券事件及长尾Provider字段漂移隔离、映射版本和错误工单模板。 | 204-A03-02 | 故意新增/改名源字段会落入隔离并产生可读差异，既有已发布字段不被静默改写。 |
| 204-B05-01 | B05 | PLANNED | B / 迁移协作代理 | CODE/OFFLINE | 制定证券历史ODS/DWD、成交额sidecar和旧复权数据的迁移映射/分区dry-run。 | 204-A04-02, 204-B02-01 | dry-run报告旧新行数、主键冲突、来源血缘、单位和复权基准差异；不写目标库。 |
| 204-B05-02 | B05 | PLANNED | B / 迁移协作代理 | REAL_SOURCE | 对批准的证券分区执行迁移后逐标的/逐分区head、interior、tail与行级抽样对账。 | 204-B05-01, 204-A06-02 | 对账报告包含预期分母、差异/未知/源限制及证据；不能只以MAX日期、行数或成功运行判完整。 |
| 204-B06-01 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 把首批股票/基金共源脚本按业务模型合并为可版本化Provider模板和TaskDefinition映射。 | 204-A03-02, 204-B02-01 | 不同旧参数仍可追踪到新模型；共用文件有单一owner，provider不在业务读API里抓取。 |
| 204-B06-02 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 按批完成剩余证券候选文件处置，保存资产清单总分母及未决项。 | 204-B01-01 | 所有候选逐项有处置、负责人、依赖和阻塞证据；不把HELPER_ONLY误建为定时任务。 |
| 204-B06-03 | B06 | PLANNED | B / 证券代理 | CODE/OFFLINE | 建立旧证券task_id/参数hash到脚本hash、dataset、provider/model、job/version、sink和验收收据的映射。 | 204-B01-01, 204-D01-01, 204-D05-01 | 双向anti-join能发现未映射旧任务和无旧来源新任务；默认导入disabled。 |
| 204-B07-01 | B07 | PLANNED | B / 证券代理 | REAL_SOURCE | 对证券域样板及分批Provider做真实源/仓/API比对、质量核验与数据权利审查。 | 204-B02-02, 204-B03-02, 204-B04-02 | 每个数据集分别有源响应、落库和API证据；许可未知与历史边界缺失单独登记。 |
| 204-B07-02 | B07 | PLANNED | B / 运维协作代理 | DEPLOYMENT+NATURAL_CYCLE | 在目标环境运行证券代表日更/补数任务，观察至少一个源定义的自然发布周期。 | 204-B07-01, 204-D06-02 | worker、publication、API freshness及自然周期收据可关联；人工补跑不替代自然周期。 |
| 204-B07-03 | B07 | PLANNED | B / C交叉评审 | CODE/OFFLINE | 完成证券源语义交叉审查和运维/源受限runbook。 | 204-B07-02, 204-C07-01 | C审阅并记录异议关闭；runbook含限流/授权/漂移/恢复路径和数据限制。 |

## C：衍生品与其他数据适配

| 子任务ID | 父WP | 状态 | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-C01-01 | C01 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 按冻结CSV分批处置449个其他域候选文件，记录source/provider/模型、参数、sink、消费者、许可及文件关系。 | 204-A01-01 | 每项留处置或待查状态，common脚本按语义重新归属；总分母anti-join有解释。 |
| 204-C01-02 | C01 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 实测10个跨期货、期权、FX/crypto、宏观/归档代表源案例及访问/保留边界。 | 204-A01-01 | 每例记录真实源身份、UTC观测时刻、请求/响应摘要、源限制和许可待查项；不等待449项映射。 |
| 204-C02-01 | C02 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 定义期货/期权精确合约、连续/主力/TAS、结算/收盘、持仓与乘数的独立schema和转换。 | 204-A02-02, 204-C01-02 | fixture覆盖夜盘业务日、到期合约、连续拼接边界、负价合法性和单位；不得压成单一OHLCV语义。 |
| 204-C02-02 | C02 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 对指定期货/期权源进行真实参数和交易所日历/合约字段核对，含年度归档边界。 | 204-C02-01 | 源端合约身份、字段、返回起点/终点及授权证据逐项存档；源没有提供的历史留未知。 |
| 204-C03-01 | C03 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 建立FX base/quote、crypto venue/base/quote、小时/日桶、UTC边界及来源时区映射。 | 204-A03-02, 204-C01-02 | 跨UTC午夜/DST样例保持正确业务日；币对方向、计价单位和频率不能静默转换。 |
| 204-C03-02 | C03 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 对选定FX与crypto真实端点核对历史保留、时间戳、限速和日内/日线语义。 | 204-C03-01 | 真实响应与原生时间/币对对照可复现；源快照未覆盖时期不被生成。 |
| 204-C04-01 | C04 | PLANNED | C / 采集代理 | CODE/OFFLINE | 把浏览器capture、年度归档下载和商品期权文件解析封装成有界Provider/Run输入输出。 | 204-C02-01, 204-D03-01 | fixture测试验证超时/退出码/临时文件清理、hash和重复导入幂等；web worker无阻塞浏览器进程。 |
| 204-C04-02 | C04 | PLANNED | C / 采集代理 | REAL_SOURCE | 对获准的浏览器/年度归档入口执行真实拉取并确认许可、来源hash和可恢复点。 | 204-C04-01 | 保留真实响应/文件manifest与失败证据；登录/验证码/WAF阻断形成停止和人工处置规则。 |
| 204-C05-01 | C05 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 建立宏观/财务外部主题数据vintage、修订、公布时刻与可得时刻合同。 | 204-A03-02, 204-C01-02 | fixture可重放旧版/修订版；无历史vintage证据的回测数据标PIT_UNKNOWN。 |
| 204-C05-02 | C05 | PLANNED | C / 衍生品代理 | CODE/OFFLINE | 将宏观/财务主题与opendata迭代2模型清单交叉映射，裁定复用、扩展或保持独立。 | 204-C05-01 | 每个重叠项只有一个实现owner与schema；无需把全套迭代2模型重新实现。 |
| 204-C06-01 | C06 | PLANNED | C / 迁移协作代理 | CODE/OFFLINE | 生成原始文件、进度/cooldown/checkpoint和旧数据库映射，定义可回放迁移manifest。 | 204-A04-01, 204-C02-01 | manifest包含hash、时间范围、文件归属、source与旧任务关系；缺映射项显式保留。 |
| 204-C06-02 | C06 | PLANNED | C / 迁移协作代理 | CODE/OFFLINE+REAL_SOURCE | 对批准的衍生品/其他域分区dry-run并按业务键、日历、单位、覆盖做前后对账。 | 204-C06-01, 204-A06-02 | 报告将离线结构差异与真实源可得性分栏；无写操作的dry-run先通过，未解决差异不宣称迁移完成。 |
| 204-C07-01 | C07 | PLANNED | C / 衍生品代理 | REAL_SOURCE | 汇总期货、期权、FX/crypto、宏观/长尾各域的source/warehouse/API实测及许可证据。 | 204-C02-02, 204-C03-02, 204-C04-02, 204-C05-02 | 每个dataset独立给出通过/受限/未知状态及起止范围证据；跨域汇总不能遮盖单项失败。 |
| 204-C07-02 | C07 | PLANNED | C / 运维协作代理 | DEPLOYMENT+NATURAL_CYCLE | 对选择的衍生品/其他域任务完成目标环境运行、自然周期观察、恢复演练和runbook。 | 204-C07-01, 204-D06-02 | 自然发布周期、UTC日桶、续跑收据可关联；B完成语义交叉评审后才申请该域切换。 |

## D：调度、迁移与运维

| 子任务ID | 父WP | 状态 | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-D01-01 | D01 | IN_PROGRESS | D / 运维代理 | DEPLOYMENT/READ_ONLY | 只读导出实际task/run/claim、crontab/systemd/进程、checkpoint、脚本参数、目标库/表及版本。 | 204-A01-01 | 记录身份、时间、命令与读取边界；不触发生产任务、不暴露secret；与脚本资产清单差异列成待查。 |
| 204-D01-02 | D01 | PLANNED | D / 运维代理 | DEPLOYMENT | 记录目标环境/数据库指纹、允许目标白名单、账号权限分离和恢复基线。 | 204-A01-01, 204-D01-01 | 只读校验能拒绝错误仓库或数据库身份；备份恢复演练步骤有owner，不执行未批准写入。 |
| 204-D02-01 | D02 | DEV_DONE（仅合同/纯函数） | D / dev_runs | CODE/OFFLINE | 定义声明式Job/Run UTC canonical身份合同及规范化/幂等身份纯函数：job版本、UTC计划时刻、分片、运行类型；补数含明确范围和request id。 | 204-A02-02, 204-D01-01 | 固定向量覆盖时区等价时刻、DST、定时与补数不冲突、重试同身份；明确本任务不含durable repository/lease/worker接线。 |
| 204-D02-02 | D02 | DEV_DONE（仅ledger离线） | D / dev_ledger | CODE/OFFLINE | 在独立opendata-od204-ledger分支实现显式Engine注入的SQL持久Run ledger、幂等入队、CAS状态/租约/token、heartbeat、终态和取消；提供owned SQLite双实例行为测试。 | 204-D02-01 | 双ledger实例竞争同一Run时只允许一个有效claim；过期token不能推进状态，重复enqueue幂等，心跳/终态/取消有行为测试。当前不含Alembic接入、调度/worker运行接线或warehouse write fence；父WP D02未完成。 |
| 204-D02-03 | D02 | DEV_DONE（MySQL/SQLite迁移） | D / 运维代理 | CODE/OFFLINE | 为Run ledger分配唯一Alembic迁移序列并集成到目标数据库迁移体系，保持双库版本治理。 | 204-D02-02 | 迁移owner确认revision无多head；warehouse 0010唯一head承接至0011；literal up/down已在独立MySQL8.0.46与SQLite验证，metadata head0006保持独立。PostgreSQL行为未验证；父D02未关闭。 |
| 204-D02-04 | D02 | PLANNED | D / 运维代理 | CODE/OFFLINE | 把持久ledger接入统一Run service与worker入口，加入持久环境下多进程竞争/崩溃恢复测试。 | 204-D02-02, 204-D02-03, 204-D03-03 | worker只能经Run service领取和结算；重启后租约可恢复，旧token不能写入终态或事实数据。 |
| 204-D03-01 | D03 | IN_PROGRESS | D / 运维代理 | CODE/OFFLINE | 实现Provider task executor协议、统一日志/退出码和可终止的有界子进程执行器。 | 204-D02-01, 204-B02-01 | fake provider验证超时、取消、stdout/stderr截断和临时资源回收；API事件循环不被阻塞。 |
| 204-D03-02 | D03 | PLANNED | D / 运维代理 | CODE/OFFLINE | 实现重试/预算/并发/供应商限速/退避、自然槽与显式补数分流及分片规则。 | 204-D03-01 | fake时钟/源模拟证明限速共享、Retry-After受尊重、源WAF不无限重试、历史恢复有独立预算。 |
| 204-D03-03 | D03 | IN_PROGRESS | D / 运维代理 | CODE/OFFLINE | 让APScheduler、手工API、CLI、systemd外壳统一提交同一Run入口。 | 204-D02-01, 204-D03-01 | 多入口相同任务映射同一occurrence身份；systemd不再直写warehouse或绕过fencing。 |
| 204-D04-01 | D04 | PLANNED | D / 运维代理 | CODE/OFFLINE | 提供管理员JobDefinition/Run/DQ/coverage后端接口、授权scope、操作者审计和安全取消。 | 204-A02-03, 204-D02-04, 204-A06-02 | 未授权请求被拒绝；审计包含操作者/对象/动作/request_id；取消不可中断阶段真实显示状态。 |
| 204-D04-02 | D04 | PLANNED | D / 运维代理 | CODE/OFFLINE | 实现opendata运维控制台的任务、执行、下次运行、覆盖、隔离、补数/取消/重放和容量页面。 | 204-D04-01 | 页面仅调用受权限保护API，关键操作有确认/结果反馈，失败原因可追踪，不内嵌任意脚本参数。 |
| 204-D05-01 | D01,D05,B01,C01 | DEV_DONE（仅静态盘点工具） | D / dev_inventory | CODE/OFFLINE | 实现opendata/migration_inventory.py、CLI与tests，把AST源文件和可选JSON任务映射整理成可重跑JSON/CSV及双向差异报告，拒绝输出覆盖源/输入；不查生产库、不执行脚本或抓源。 | 204-A01-01 | CLI对相同输入给稳定输出；单测覆盖入口/辅助/哈希、解析失败、重复/缺失映射、路径与输出保护；不宣称源、任务或数据迁移完成。 |
| 204-D05-02 | D05 | IN_PROGRESS | D / 迁移代理 | CODE/OFFLINE | 实现存量Job/执行/checkpoint迁移的只读dry-run、显式apply闸门、备份和目标指纹校验。 | 204-D01-02, 204-D02-03, 204-A04-03 | dry-run拒绝未知目标并汇报导入/跳过/冲突；默认disabled；apply必须检查部署身份与备份可恢复性。 |
| 204-D05-03 | D05 | PLANNED | D / 运维代理 | DEPLOYMENT | 在隔离恢复环境验证元数据/warehouse备份、artifact manifest和迁移后状态的恢复流程。 | 204-D05-02 | 记录RPO/RTO实测、缺失工件与恢复偏差；恢复演练不覆盖生产数据。 |
| 204-D06-01 | D06 | PLANNED | D / 可观测性代理 | CODE/OFFLINE | 连接request/run/source/publication的trace_id，建设低基数日志、trace和指标埋点。 | 204-D03-03, 204-A05-03 | 本地追踪可串起一笔mock查询到Run/publication；instrument维度明细放事件而非高基数标签。 |
| 204-D06-02 | D06 | PLANNED | D / 可观测性代理 | DEPLOYMENT | 配置按源周期的数据freshness告警、API/worker/磁盘/备份SLO仪表盘和故障演练。 | 204-D06-01, 204-D05-03 | 目标环境触发测试告警并可恢复；SLO标为初始目标且经实测校准，未演练前不写已达标。 |
| 204-D07-01 | D07 | PLANNED | D / root+运维代理 | DEPLOYMENT | 以dataset/sink为单位制订新旧单写者fence、影子读、切换清单和分波授权。 | 204-D05-02, 204-D06-02, 204-E06-01 | 每波明确唯一writer、回滚owner、断点和观测窗口；逐dataset检查对应B07/C07真实源、部署和自然周期收据，按单域门禁推进，不等待无关域全量完成。 |
| 204-D07-02 | D07 | PLANNED | D / 运维代理 | DEPLOYMENT | 对单波执行重复投递、worker崩溃/租约过期、源失败和回滚演练。 | 204-D07-01 | 证明旧/新写者不会并发产生重复事实，回滚后可按publication/Run追踪恢复。 |
| 204-D07-03 | D07 | PLANNED | D / 运维代理 | DEPLOYMENT | 在逐域切换验收后停用旧systemd/worker/凭据并保留可审计退役记录。 | 204-D07-02 | 每项旧入口有owner、最后运行和禁用证据；紧急恢复路径经评审，未覆盖域保留旧机制状态。 |

## E：ai-for-investor消费端与业务回归

| 子任务ID | 父WP | 状态 | owner/建议代理 | 类别/验收面 | 具体交付 | 前置依赖 | 验收条件 |
|---|---|---|---|---|---|---|---|
| 204-E01-01 | E01 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 清点AFI所有行情、数据库DSN、文件、直接源SDK、页面与任务读路径，记录调用点和旧功能。 | 204-A01-01 | 搜索结果与运行时路由/后台任务交叉核对；每个读路径归属具体业务场景和责任人。 |
| 204-E01-02 | E01 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 建立功能场景、频率、单位、日期边界、错误和权限回归矩阵。 | 204-E01-01 | 覆盖回测/优化、行情页、搜索、扫描器、信号和研究快照；标出旧行为与目标接口差异。 |
| 204-E02-01 | E02 | DEV_DONE（仅同步SDK v1分页） | E / dev_client | CODE/OFFLINE | 实现opendata同步SDK现有v1 GET的分页请求/响应校验、行/页预算和流式响应字节上限；保持latest-view，不提供固定版本或跨页快照保证。 | 204-A02-03 | mock测试验证页号/大小回显、count为当前页行数、终止条件、超页/超行及流式超限关闭；不含async、整体deadline、通用业务键去重或v2导出。 |
| 204-E02-02 | E02,E03 | DEV_DONE（仅AFI输入校验） | E / dev_consumer | CODE/OFFLINE | 在现有AFI股票日线v1适配器核对响应symbol、严格业务日期和分页元数据，拒绝重复页；流式读取并限制单响应/累计字节，保留原窗口转换与过滤。 | 204-A02-03, 204-E02-01 | 单测覆盖错/缺symbol、非法日期、首尾过滤、错误分页类型/回显/count、重复页/超行/超字节及关闭；不声称新增cursor/snapshot/其他资产支持。 |
| 204-E02-03 | E02 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 为async FastAPI读路径加独立Async HTTP适配器或薄REST层，确保不在事件循环调用同步SDK。 | 204-E02-01, 204-E02-02 | async并发测试确认无同步阻塞；请求使用共同OpenAPI fixture，适配层不复制provider/清洗逻辑。 |
| 204-E02-04 | E02 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 统一认证、单位/时区、deadline、有限重试、request_id、429/503/空结果错误映射。 | 204-E02-03, 204-A02-04 | 重试只覆盖幂等读且受总deadline限制；scope/许可错误不重试；可区分合法空、未覆盖、无权和中台不可用。 |
| 204-E03-01 | E03 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 将行情列表、搜索、覆盖/主题卡等首批业务读路径改到REST client。 | 204-E02-04, 204-A05-01 | API级测试证明业务路径无数据库直读/源SDK调用，页面字段/单位和分页行为符合场景矩阵。 |
| 204-E03-02 | E03 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 迁移单标的分析、扫描器、信号所需行情读路径并明确频率不可用时的业务响应。 | 204-E02-04, 204-A05-02 | 集成fixture验证symbol、日期、频率及缺口提示；不静默降频、换源或改变策略语义。 |
| 204-E03-03 | E03 | PLANNED | E / 消费端代理 | CODE/OFFLINE | 补齐迁移业务页面和关键API回归，保持已有分析功能并标记暂不可用能力。 | 204-E03-01, 204-E03-02 | 既有场景矩阵逐项有通过/限制结果；错误提示可行动且不把质量部分数据冒充完整。 |
| 204-E04-01 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 为研究快照/导出增加publication、schema、过滤条件、内容hash与来源manifest引用。 | 204-A04-03, 204-E02-04 | 相同固定snapshot可重放同一工件；哈希/契约不匹配时拒绝加载。 |
| 204-E04-02 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 将回测/优化输入绑定固定snapshot、PIT要求、数据版本与明确的时间窗口。 | 204-E04-01, 204-A05-02 | 对冻结fixture重跑结果可核验；不满足严格PIT/缺口阈值时明确失败或降级为标注研究。 |
| 204-E04-03 | E04 | PLANNED | E / 研究工件代理 | CODE/OFFLINE | 实现sealed数据集、用户/租户研究权限和导出/工件访问控制。 | 204-E04-02, 204-A05-03 | 越权和跨租户测试拒绝读取/导出；授权缓存随权限变化失效。 |
| 204-E05-01 | E05 | PLANNED | E / UI协作代理 | CODE/OFFLINE | 将旧数据管理入口加兼容提示/跳转到opendata控制面，保留必要只读摘要入口。 | 204-D04-02, 204-E03-03 | 旧URL可解释地跳转或展示只读视图；无管理权限用户看不到操作入口。 |
| 204-E05-02 | E05 | PLANNED | E / UI协作代理 | CODE/OFFLINE | 为保留的AFI行情/可用性页面接入真实coverage/freshness状态。 | 204-E05-01, 204-A05-02 | 状态明确区分PARTIAL/UNKNOWN/SOURCE_LIMITED/NOT_APPLICABLE；无coverage时不显示“完整”。 |
| 204-E06-01 | E06 | PLANNED | E / 集成代理 | DEPLOYMENT+REAL_SOURCE | 对授权样本执行新旧影子读比对，记录行、字段、单位、来源、时间边界和差异。 | 204-E03-01, 204-E04-02, 204-D06-01 | 同一固定窗口能逐标的对照；影子阶段不重复触发全量真实抓取、不把旧错误当基准正确。 |
| 204-E06-02 | E06 | PLANNED | E / 集成代理 | DEPLOYMENT | 验证AFI在opendata超时、限流、源受限、权限失败和部分覆盖时的降级/恢复体验。 | 204-E06-01, 204-E02-04 | 目标环境的故障注入保留request_id并返回正确业务状态；服务恢复后可重试且无重复提交。 |
| 204-E07-01 | E07 | PLANNED | E / 集成代理 | CODE/OFFLINE | 在对应业务路径切换并具备回滚条件后，移除AFI采集SDK、仓库DSN和采集启动hook。 | 204-D07-01, 204-E06-02 | 静态依赖/运行时扫描无未批准直连；保留的专有研究数据路径有单独归属声明。 |
| 204-E07-02 | E07 | PLANNED | E / 集成代理 | CODE/OFFLINE+DEPLOYMENT | 检查安装包、容器、CI secret、环境变量和启动配置边界，确认只保留必要opendata client与身份。 | 204-E07-01, 204-D07-02 | 构建产物不含opendata内部包/服务DSN/源密钥；目标环境AFI只持有最小读scope。 |

## 首批子任务精确范围

| 子任务 | 当前代理 | 本轮明确不包含 |
|---|---|---|
| 204-D05-01 | dev_inventory | 真实生产任务/数据库读取、执行脚本、真实源验证、完整迁移导入。 |
| 204-A06-01 | dev_coverage | 数据源边界背书、数据库/仓库接线、coverage API或历史数据完整性结论。 |
| 204-D02-01 | dev_runs | durable repository、Alembic、worker/调度接线、真实部署或warehouse write fence。 |
| 204-E02-01 | dev_client | AFI异步调用接线、v2 snapshot/export、大批量无界下载或源选择/清洗逻辑。 |
| 204-E02-02 | dev_consumer | 所有消费页迁移、真实源校验、绕过错误symbol时自动猜测/回退。 |
| 204-D02-02 | dev_ledger（独立分支 opendata-od204-ledger） | Alembic/运行接线/warehouse write fence；该ledger必须由root与dev_runs契约集成后再并入主线。 |

下一波可按接口和文件owner把PLANNED任务重分配给现有子代理或新代理。若任务依赖的合同尚未合入，可先用本清单的fixture/冻结接口推进离线代码；涉及共享文件、真实凭据、生产写操作、部署或自然周期的工作按对应owner和验收面排队，不能因代理空闲而并发改同一文件或提前标记通过。
