# 子代理开发与集成记录

## 当前开发基线（2026-10-27）

截至今日，ai-for-investor 与 OpenData 均以 `dev` 为开发基线，本地与远程只保留 `master`、`dev`。AFI PR #52–#58、#62、#64–#66 与 OpenData PR #5–#10 已合入；合并只表示各 PR 的交付范围已集成，验收范围与未完成项仍以本文后续记录为准，迭代204整体尚未完成。

## 历史记录：隔离集成状态

以下记录的是当时的隔离集成分支状态，不代表当前分支布局或最新合并状态。

两仓使用下表的隔离集成分支，未push、未合入dev、未部署。第二批11条分支完成契约、账本、持久发布与快照、授权、v2 REST/SDK和AFI输入边界；其1,120项组合、AFI157项、独立MySQL7项和SDK安装5项结果见 [WAVE2_STATUS.md](WAVE2_STATUS.md)。这些是第二批的历史收据，不冒充第三批重跑。

第三批按6个控制任务拆成7条执行任务，已集成子进程执行、raw证据、主机清单、统一提交、迁移dry-run、OpenAPI门禁及股票wire身份校验。分支、审查修复、组合回归及限制见 [WAVE3_STATUS.md](WAVE3_STATUS.md)。35个工作包细分为87个控制任务，各域适配仍继续按不超过20个源条目的批次拆分；本批局部能力不会自动关闭完整任务。

真实只读库确认1,103个任务、1,066条脚本注册和1,042张旧仓库表。主机报告保留权限/截断与writer身份未知，迁移预演保留1,103个BLOCKED、0个ready。完整gate、真实源、全历史迁移、生产worker、自然周期和恢复切换仍未验收。

## 首批历史

日期：2026-10-26（Asia/Shanghai）。执行方式：主代理拆分、分派、审查与集成；6个开发子代理分别在独立worktree/branch提交，另安排独立代码审查。现有35个工作包已细分为87个子任务，本批完成6项代码与离线验证，81项仍待推进。完整迁移尚未完成。

## 历史记录：隔离基线与交付分支

| 仓库 | 输入基线 | 本地集成分支与路径 |
| --- | --- | --- |
| ai-for-investor | `c720a261c`；原工作区有大量203未提交改动。此次修改的两个源/测试文件均确认与HEAD一致；203脚本从原目录只读盘点 | `codex/od204-afi-integration`，`/home/yun/.codex/worktrees/od204-integration/ai-for-investor` |
| opendata | `dev@61800c18`，原工作区干净 | `codex/od204-subagent-integration`，`/home/yun/Documents/opendata-od204` |

原目录中的业务代码和运行状态未被覆盖。AFI迭代文档同步更新开发记录；代码保留在隔离分支供审阅。尚未push、创建PR或合入dev。后续普通变更PR仍指向dev，不能直接提交master。

opendata代码集成截至 `f29b8e72`，AFI代码截至 `c9076d462`；新增跨模块组合测试与操作手册由主代理另行提交。子代理各自的实现提交已按审查顺序cherry-pick，提交历史可复核。

## 首批子任务

| 子任务 | 开发代理 | 交付与离线结论 | 后续边界 |
| --- | --- | --- | --- |
| 204-D05-01 | dev_inventory | AST只读扫描、JSON/CSV、可选任务JSON双向映射、哈希、解析失败不漏项、报告输出保护 | 生产DB任务、systemd/cron/其他脚本和运行中进程仍需独立导出对账 |
| 204-A06-01 | dev_coverage | 日粒度head/interior/tail、重复/意外日期；未知日历/起点不报完整，源保留与快照归档分别处理 | 未接真实主数据、日历、仓库或coverage API；不证明字段质量和许可 |
| 204-D02-01 | dev_runs | Job/Run合同、UTC计划槽、显式人工请求键、独立payload hash与完整可重放快照、有界输入重验证 | 尚无任务派发或worker接线 |
| 204-D02-02 | dev_ledger | 显式Engine的SQL持久账本、幂等enqueue、单行CAS领取、租约/心跳、终态/取消、旧token拒绝 | 未纳入Alembic；token只保护账本，不保护仓库写入；MySQL/PostgreSQL需真实独立验证 |
| 204-E02-01 | dev_client | v1分页请求/响应、行/页预算、16MiB流式响应上限与脱敏错误；保留latest-view | 不含通用业务键去重、固定快照、异步client、整体分页deadline或v2导出 |
| 204-E02-02 | dev_consumer | AFI逐行symbol精确匹配、严格日期、分页回显/重复页/超量拒绝；流式单响应/累计字节与provenance预算 | 仍只支持既有股票日线合同；未改变PIT、数据来源、采集开关或全部业务读路径 |

这6项均为子范围DEV_DONE，不代表A06、D02、D05或E02整个工作包ACCEPTED。SOURCE_VERIFIED、生产迁移、DEPLOYMENT_VERIFIED、自然周期与切换状态均保持NOT_RUN。

## 集成审查处理

独立审查发现并已修正：同一次claim误更新多条记录；自然计划槽因请求参数漂移生成新key；冻结模型中的可变JSON绕过初始验证；HTTP完整读入后才检查大小；源当前保留边界错误排斥已归档旧数据；缺失/截断日历及单日快照可能误报COMPLETE；盘点报告输出可覆盖输入及错误分类重复计数。

主代理新增identity与ledger组合测试，验证同槽参数冲突、时区等价重投、重启后复用、人工/自然槽隔离、复用补数请求键却改变范围时拒绝。测试使用临时SQLite文件和MockTransport，不使用生产数据库或真实供应商。

## 验证结果

- AFI组合：股票日线REST适配器与Provider契约共 **75 passed**。
- opendata组合：本批新模块、独立SDK及其ingest/export/warehouse/PIT相关回归，共 **442 passed、1 skipped、6 deselected**；skip为需显式启用的安装测试，deselected为真实服务e2e。独立启用安装用例后另获1 passed，验证最小/全extras wheel均能脱离源码与system-site安装使用。
- scoped coverage：本批5个受检生产模块语句与分支综合 **92.18%**，使用单独临时coverage配置和数据文件，目标阈值85%；各模块为盘点85.44%、覆盖100%、身份96.37%、账本91.30%、SDK92.66%；这不是整仓覆盖率或make gate结果。
- Ruff/format、Bandit及新/修改目标文件的定向mypy通过；普通mypy追踪既有依赖时仍报告 `opendata/data/models/base.py:67–68` 两处redundant-cast。未通过忽略它们宣称整仓绿灯；定向mypy使用 `--follow-imports=silent` 检查6个目标生产文件。
- Python3.10语法检查通过；本轮实际测试运行时为Python3.13.5，不等于已经完成Python3.10运行矩阵。
- 真实旧目录扫描 **1,066文件、0语法/文件系统错误**；源文件集合及SHA-256与起始CSV一致，source_verification全部NOT_VERIFIED。脱敏报告位于 `/tmp/od204-receipts/legacy-inventory.json`，SHA-256为 `49a9520c9705edae369cdfd7552b43be32aa54d3bc3b86d67de007c2524b498e`。

工具环境使用隔离 `/tmp/od204-quality-env`，Ruff 0.15.20、mypy 2.3.1、Bandit 1.9.4，与opendata声明版本一致；未修改原项目依赖环境。第一次按dotted module限定coverage时触发导入初始化问题，改为按文件系统source范围采集并在report中列出受检模块后，组合覆盖率命令正常完成。一次AFI组合命令引用不存在的测试文件未收集测试，已纠正为实际的 `test_provider_contracts.py` 后取得75项通过。

## 首批交付时的后续入口

下一批按依赖推进：204-A02-01至03冻结首个股票样板的API/数据合同与fixture；204-D02-03为账本分配Alembic并验证目标数据库；204-D03-01/03建立受限执行器和统一Run入口，再接持久服务；204-B02-01/02与A05/A06接线完成采集→仓库→REST→AFI→研究快照。

生产切换仍必须执行既定逐域对账、单写者、自然周期和回滚门槛。未执行数据采集、DDL、调度启停、source Key变更或生产发布；不能用本批离线结果关闭1,103个旧任务、全部脚本或全历史恢复要求。

第四批五条模块开发流和公共请求保护已集成；metadata迁移、实际子进程到REST的联调和1813项最终组合结果见 [WAVE4_STATUS.md](WAVE4_STATUS.md)。角色规划与CLI库内SPI不代表实际main或systemd已接线。

第五批各局部工作流已有定向验证：AFI图表路径230 passed；OpenData A2静态resolver 1,189个文件、783个mypy roots无失败；DataFrame边界366 passed、1 skipped且三模块覆盖95.3795%；MySQL worker 41 passed、覆盖91.2467%，但有16个SQLite ResourceWarning，远程TLS未执行；七个默认数据库目标guard 20 passed。公开验证manifest将这些结果汇总为局部代码与隔离集成验证通过；生产验收仍未完成。root合入并复核fixture专用修复31cfd70ba62dee6e1243d7ea9100a15532e49f95后，同一58文件组合2199 passed、25 deselected，fixture/guard定向22 passed；最终Ruff、format、mypy、Bandit、named gates与A2均在31cfd70ba62dee6e1243d7ea9100a15532e49f95通过（1,189个A2文件、783个mypy roots、0个失败；333个docs/evidence文件仍按既有规则排除）；wave5私有证据归档已冻结（121个文件、12,400,793 bytes），公开验证manifest状态为SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED、NOT_PRODUCTION_ACCEPTED。整仓make gate NOT_RUN。两次未经批准的目录级测试已完成只读审计，但外部数据库和文件副作用仍保持未知。范围、收据和限制见 [WAVE5_PLAN.md](WAVE5_PLAN.md) 与 [WAVE5_STATUS.md](WAVE5_STATUS.md)。

全量控制任务仍为87项：8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；204-E03-01仍是局部完成。1,103个旧任务、完整历史head/interior/tail、角色/CLI/UI及全部AFI消费者接线、自然周期、备份恢复和单写者切换均保持开放。截至第五批冻结时点，第六批HTTP边界分支3d16400c尚未由root合入或测试；stock进程切片仍开发中、默认关闭且权限未知。后续第六批合入、回归及修复进展另行记录，不计入第五批验收收据。

## 第六批局部进展（第五批冻结后）

此处记录第五批冻结之后的独立进展；不会回写或改变第五批提交、测试与121文件归档收据。HTTP客户端/request-budget边界工作已在OpenData提交`0efe35f8b155461c401b06379f304b040340b322`上运行11个明确测试文件，288 passed、1 deselected，覆盖率合计92.97%（`http_client.py` 90.1980%，`request_budget.py` 98.4375%）。worker资源清理专用测试21 passed，并把ResourceWarning及pytest unraisable warning作为错误；这仅验证测试资源清理，不是生产shutdown验收。早期覆盖不足、HTTP模块未达门槛及fixture错误的中间结果保留在 [WAVE6_STATUS.md](WAVE6_STATUS.md)，没有降低门槛或增加排除。

股票日线进程切片的独立review在生产快照`451458da2076bb27623f1621ecdcdd3b9d5880f9`给出P1/P2范围内STATIC GREEN；root合入`a5078a90`、`285a1fad`、`81549aea`后，首轮三文件测试161 passed、1 failed，覆盖率报告90.92%。失败为正向fixture在固定handler合同校验前替换`executor.run`；测试专用修正`5b8de0f2`经review并合入`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`。修正后三文件测试168 passed，wire/job覆盖分别91.3978%和92.4786%，合计92.2179%。修正改用synthetic envelope解码与父端normalization，不声称job.fetch/Popen或上游调用通过。作者报告的Ruff、strict mypy、Bandit、format未由reviewer重跑；此slice仍默认disabled、未生产注册、rights UNKNOWN。

root已在合入提交`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`运行69文件显式组合：2,529 passed、26 deselected、无报告warning；其中1项cache integration node显式deselect，另25项沿用既有e2e排除。质量锚点`2464dd13839acc00f4102d551601af2de8d72a60`上Ruff/format覆盖112 Python文件、production mypy 58 core+3 client、Bandit 61文件及named gates通过；全量A2为1,192 resolver文件、783个mypy roots全通过，333个docs/evidence文件按既有规则排除。149,323条历史Ruff发现仍NOT GREEN，5,130项support缺口及16项active-evidence缺失仍OPEN。fresh `make secret-check`使用Gitleaks 8.30.1扫描821个提交，0泄漏，配置/manifest/scanner未变；新生成的两个公开JSON之后由固定版本Gitleaks单独扫描，exit 0、0 findings，收据在Wave 6私有归档之外。Wave 6冻结私有归档共135个文件、18,198,311 bytes，两个公开manifest已生成。第五批A2不作为Wave 6证据。完整`make gate`仍NOT_RUN。其余87项控制任务计数、1,103个旧任务、真实来源与许可、完整历史、全部AFI消费者、生产角色/CLI/UI、自然周期、备份恢复和单写者切换均保持开放。具体范围与收据见 [WAVE6_PLAN.md](WAVE6_PLAN.md) 和 [WAVE6_STATUS.md](WAVE6_STATUS.md)。

## 第七批离线接线与证据归档局部收口

第七批围绕管理员手工reviewed-run路径，新增OpenData侧独立runtime、admin API、`create_reviewed_app()`与OpenData前端管理页。工作分工、共享合同、导入副作用和验收边界见[WAVE7_PLAN.md](WAVE7_PLAN.md)；本节按root精确收据记录局部离线结果，不代表生产接受。

| 范围 | 精确source锚点与结果 | 限制 |
| --- | --- | --- |
| OpenData frontend | `c52663b2ec6e0070fe404ef10edb5e93bb53288c`：6个Vitest文件，29 passed、6.44秒；官方`npm run build`通过，包含`vue-tsc` | 保留Vite chunk warning：最大`index` JavaScript chunk 1,287.10 kB，超过600 kB提示；不推导生产性能或部署状态 |
| Run identity/ledger | `ad76bc7fb3a5de068d2d338d18901993f6f75605`：9个显式文件248 passed、20.83秒；identity 96.1749%，ledger 90.6667% | 两个目标分别达到90%门槛；限于离线身份与账本路径，不证明生产DB、多进程、部署或自然运行 |
| reviewed runtime/admin API/app | `b4a1f630ad48781d21440724971562ec946374d3`：4个显式文件70 passed、10.56秒，无skip/warning，raw/verification exit 0；runtime 96.1390%、API 85.3186%、app 96.2025% | 三个目标分别达到门槛（pipeline/runtime 90%，API/app 85%）；API略高于85%底线。与独立ledger结果分开记录 |
| OpenData static | `b4a1f630ad48781d21440724971562ec946374d3`：Ruff/format 120 Python文件、production mypy 61 core+3 client文件、Bandit 64 production文件均PASS；3.10 grammar PASS | Python 3.10 runtime NOT_RUN；质量锚点`f7aec5da6c30de03b48e88e7abbdcd748bde0934`只更新zero-dependency census 643→646（vendor325/client3/total974），未改Python，93 pins与12 AST例外保持不变 |
| Named gates | 质量锚点`f7aec5da6c30de03b48e88e7abbdcd748bde0934`上`make brand-check zero-dep-check public-api-quality published-openapi-check` PASS；974文件scanner无新增upstream reference，2,495个public callables的docstring/annotation覆盖100%，OpenAPI v1 140路径/v2 6路径兼容 | 这是四项named gates，不是A2或完整`make gate` |
| Cross-stream combined | 质量锚点`f7aec5da6c30de03b48e88e7abbdcd748bde0934`：74个显式文件2,627 passed、26 deselected、142.09秒，无报告warning | 25个既有e2e及1个cache integration node明确排除；空owned CWD、74个绝对测试路径、仓库`pytest.ini`；未产出coverage报告 |
| A2 | 同一质量锚点：1,200个resolver文件、786个mypy roots全部exit 0 | 333个docs/evidence文件按既有策略排除；149,323条历史Ruff发现仍NOT GREEN，5,130项support和16项active-evidence缺口仍OPEN |
| Secret scan | 固定版本Gitleaks 8.30.1扫描861个提交，0泄漏；两个后续公开JSON在owned copy目录单独扫描，exit 0、0 findings | 独立公开文件扫描收据位于冻结归档之外 |
| 私有归档与公开证据 | `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave7`：106 files，10,544,281 bytes；目录0700、文件0600；验证JSON SHA-256 `017a69ea56a87c7ff3b09b472ba7464447683923707e8ea01e928f40d842f685`，归档JSON SHA-256 `6125ec2ae14432d8c3b22497edcf0b8f850817a8baea88fb4324d9285a3e096a` | 独立归档审查36项全部通过，106个文件的哈希、大小、权限及报告事实匹配；审查收据在冻结归档之外。公开JSON在OpenData本地提交`df8bf9b51ac634e2d55863127077ef37292ead4e`生成，之后单独扫描通过 |

保留的前置结果：前端4文件首轮14 passed/2 failed，后续15 passed/1 failed；create调用为0的失败来自detached wrapper上的测试`button.click()`未提交未挂载表单，修正为显式form submit并保留button enabled/type断言；logout测试改为等待router `afterEach`后再断言`/login`。最终6文件合并测试29项通过，早期失败收据仍保留。API首个宽范围命令47 passed、10 skipped、10 warnings，总覆盖79.11%，不能作为验收：pytest-asyncio已安装，但`-c`误指向`pyproject.toml`而未加载`pytest.ini`中的`asyncio_mode=auto`，10个未显式标记的async用例因此被skip。后续4文件67 passed但API覆盖84.7645%，低于85%并判FAIL；增加3个media-type / 请求body不读取边界用例后才得到上述70 passed、API 85.3186%的接受结果。较早的ledger/runtime/app失败、warning或85.83%覆盖结果仍在收据中保留；这些W7运行使用环境allowlist与owned SQLite。CLI phase fixture错误、覆盖不足或配置选择问题均单独保留；ResourceWarning审计仅指出可能的test-owned cleanup候选，具体归因未证实，不将这些中间结果描述为隔离失效。

reviewed app只挂载认证与reviewed routes，未借此改变legacy `main`/API routes/调度默认行为。Runtime worker与RunLedger共享同一个显式注入的metadata Engine对象。取消由ledger立即标记`CANCELLED`并fence旧token；最终状态为CANCELLED（含重复取消）时返回`outcome=cancelled`，SUCCEEDED/FAILED返回`outcome=terminal`，该字段不表示本次请求触发状态转换。worker本身停止仍为协作式，当前`close()`只停用新adapter，不取消已运行job。运行时导入可能eager-load pipeline/model/core settings并创建默认Engine，API package initializer可能加载legacy router；定向执行需从无`.env`目录并使用环境变量allowlist，显式使用临时owned SQLite，不把default-Engine guard称为通用沙箱。

本批离线接线和证据归档已局部收口：106文件私有归档的独立审查36项全部通过，0失败，旧Wave 6归档也保持不变；审查收据为`/tmp/od204-receipts/wave7-archive-independent-audit.json`。最终manifest与公开JSON哈希、secret scan见上表；公开文件扫描收据位于冻结归档之外。质量锚点`f7aec5da6c30de03b48e88e7abbdcd748bde0934`上的120文件static、四项named gates、74文件combined及A2已通过；历史Ruff发现和证据缺口仍按表中范围开放。Python 3.10 runtime与整仓`make gate`均为NOT_RUN。不得借用Wave 5/6收据补齐第七批门禁，也不得将以上隔离验证描述为真实源、生产权限、部署、自然周期或全历史已验收。开放任务分母保持87项（8 DEV_DONE、9 IN_PROGRESS、70 PLANNED）；1,103个旧任务、1,066个脚本候选、完整历史head/interior/tail、source rights、全部AFI消费者、自然周期、备份恢复与单写者切换继续OPEN。详情见[WAVE7_STATUS.md](WAVE7_STATUS.md)。

## 第八批股票标的目录REST接线与专项验证

共享profile、contract和三处相同hash的合成fixture已冻结；OpenData新增registry publication投影及严格table/none无时间窗分支，AFI新增默认关闭配置、async adapter、权限校验及stock selector UI。adapter完整验证有界快照后才搜索，失败不读本地warehouse/cache/seed兜底，unknown availability保留unknown/null，alias要求显式业务生效日。增量发布中的旧行publication元数据已按store的delta/latest-view语义修正，并在完整快照内检查ID与sequence双向一致。

OpenData代码锚点`ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`；AFI代码锚点`6b8f13c6d6c7d8cec360ebed63ae7098288a5a2c`。OpenData精确4文件112 passed、producer/API覆盖98.9071%/89.8862%；AFI精确3文件在独立Python3.11.15锁文件子集环境203 passed、adapter/helper覆盖92.5532%/94.6809%；前端新增18项与兼容91项通过，类型检查和稳定源码构建通过；真实producer→owned SQLite store→v2 ASGI API→AFI adapter的2项wire bridge通过。两仓scoped static、AFI最终route/UI、adapter、测试、bridge及锁环境静态审查均通过。早期功能/coverage/setup/source-fence失败保留，不以最终通过覆盖历史；原共用环境低于AFI依赖下限的问题已通过独立锁文件子集重跑解决，未声称完整extras/full CI或Python3.10 runtime通过。

OpenData全量A2静态通过（1,203 resolver文件、787个mypy roots全部exit0，既有333个docs/evidence排除策略不变）；149,323条历史Ruff发现和support/active-evidence缺口仍开放。固定Gitleaks8.30.1扫描872提交0泄漏；162文件、14,408,256 bytes私有归档及25项独立核对全部通过，旧W7归档不变。公开元数据误报经独立确认和字段结构修正后复扫0发现，失败及修正链保留在冻结归档之外。精确证据来自多个提交的分项运行，10个相关production文件当前字节与通过运行一致，不是一轮current-HEAD组合测试。整仓make gate、生产来源/授权、完整历史与切换仍开放。当前没有启用真实provider、DatasetGrant、新selector flag或旧任务。原AFI255个受保护源码文件与既有基线逐字节一致；这不证明任何外部数据库或进程状态。

只读财报映射覆盖12个三大报表脚本，并在既有运行快照中找到12个历史task ID；11项为EXTEND建议、1项为Sina Provider的REUSE候选。映射不证明当前调度、来源权利、财报PIT/修订语义或迁移就绪，也不改变1,103任务、1,066脚本与87项控制任务分母。实现分工、精确收据和开放边界见 [WAVE8_PLAN.md](WAVE8_PLAN.md) 及 [WAVE8_STATUS.md](WAVE8_STATUS.md)。

## 第九批 Sina 财务报表raw-wire切片

W9在OpenData `9ff72ad668ce161f5132bf866b251acd3c80bbba` 完成source-native `fzb` parser及有界wire seam。最终root隔离运行只选parser与wire两文件、使用`--noconftest`及独立Python 3.13.5环境：85 passed、159.20秒；contract/parser/wire statement+branch coverage分别95.9732%、93.3472%、90.8046%，均达到90%目标。首轮76 passed、3 failed及parser覆盖88.8889%的失败继续保留；修复未降低coverage门槛或增加排除。

Ruff、format、mypy、Bandit、zero-dep self-test/check、public API与brand scoped static通过（979 runtime files、2,499 public callables）；Python 3.10 grammar通过但runtime未运行。A2完成1,209 resolver files、791 mypy roots均exit 0，Gitleaks 8.30.1扫描894 commits为0 leaks。仍有149,323条历史Ruff findings NOT GREEN、5,055个blocked archived candidates、19项manifest errors及active evidence/support gaps按既有policy保持OPEN。80文件、2,064,005 bytes私有归档已冻结（目录0700、文件0600）；独立archive audit 24/24 checks，80/80文件及2个ZIP的CRC/path核验全部通过，旧W7/W8归档不变。公开validation与archive JSON在metadata commit `fbb57d546cf149bb8990dcf2088c6b4d1ec2bcaf`生成，固定Gitleaks复扫0 findings。完整`make gate`、remote CI、Python 3.10 runtime和生产接受均未完成。正向测试只证明一份录制Sina响应及fake transport行为，不证明source rights、单位、revision、其他市场或全历史。完整收据和首轮失败见 [WAVE9_STATUS.md](WAVE9_STATUS.md) 与 [WAVE9_PLAN.md](WAVE9_PLAN.md)。

## 第十批 Sina 七项候选投影（scoped offline QA完成）

W10冻结合同SHA-256为`2ec501ad7d20e9802a4dc1aef3911ec7e6a9b0d8f5af231072e780fdf75b9c9a`。合同DTO（commit `954e79c9`）和projector（commit `d0abab97`）均静态review GREEN并集成到root OpenData source `1bd226690acd7e4bbd620a480f7e6271c38297fd`。唯一隔离测试文件（author commit `be057bb0927a710a8e5b233fd28a9b262f0f9f4a`）经独立review后由root以`--noconftest`运行：65 passed、44.23秒；合同/projector statement+branch coverage为97.5309%/95.3608%。测试复用未变更的W9-owned Python 3.13.5、17-pin虚拟环境。

Ruff、format、mypy、Bandit、zero-dep/self-test、public API及brand scoped gates通过（981 runtime files、2,501 public callables 100%）；Gitleaks 8.30.1历史扫描905 commits、0 leaks。Whole-resolver A2未为W10运行，W9 A2结果不复用为W10证明。49文件、766,405 bytes私有归档的独立audit通过，验证全部W10文件及W7/W8/W9共348个旧归档文件；一个HTML ZIP CRC/path、权限与provenance pins通过核对。两个公开manifest的独立secret scan为0 findings。整仓`make gate`、remote CI、Python 3.10 runtime与生产接受仍未完成。投影只按七组精确source ID/title输出namespaced候选，始终`partial`并保留原始值/state/metadata/时间/ordinal；不得据此推导会计单位、修订、PIT、source rights或生产资格。完整证据见 [WAVE10_STATUS.md](WAVE10_STATUS.md) 与 [WAVE10_PLAN.md](WAVE10_PLAN.md)。

该批不注册Sina provider、不创建生产grant、不持久化候选、不修改`FinancialStatement`/DWD/PIT或启用任务748。父级87项矩阵仍为8 DEV_DONE、9 IN_PROGRESS、70 PLANNED；1,103项旧任务、1,066个脚本候选、完整历史、自然周期与切换继续OPEN。**W10关闭时**，W11仍处设计阶段且合同未冻结；此后合同已冻结并进入实现，当前工作包与验收状态见 [WAVE11_PLAN.md](WAVE11_PLAN.md)。W10工作包、依赖和验收见 [WAVE10_PLAN.md](WAVE10_PLAN.md)。

## 第十一批 Sina instrument/capture快照发布

合同、独占工作流及逐run收据见[WAVE11_PLAN.md](WAVE11_PLAN.md)与[WAVE11_STATUS.md](WAVE11_STATUS.md)。最终source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`上的13文件核心回归469 passed、1 deselected、0 warnings，238.35秒；helper/platform/store/writer/API/client/producer/migration八个production targets coverage分别为100.0000%、93.0612%、94.1392%、99.5327%、89.6552%、90.0533%、90.8088%、100.0000%，全部达到模块floor。早期12文件首轮FAIL及fixture、warning和coverage问题仍保留在收据中，不由复跑覆盖。OpenAPI gate在同一source精确1文件24 passed、6.89秒，checker coverage 95.4693%；v1 baseline不变，reviewed v2 baseline已更新。

同一source的scoped static覆盖9个production targets和7个新增test files（16文件、8项组件），全部PASS；zero-dependency census为983个文件（655 runtime、325 vendor、3 client），public callables为2,507。53-pin hermetic environment独立安装审计通过，external guard单独9 passed、0.10秒。最终A2通过：1,222 complete-resolver files、796 unique mypy roots均exit 0；full-history Gitleaks扫描976 commits、0 leaks。149,323条历史Ruff findings、5,055个blocked archived candidates和19项manifest errors按既有policy保持OPEN；不等同完整`make gate`。root已在OpenData source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`冻结W11归档：182文件、6,554,821 bytes、3个HTML ZIP，目录0700、文件0600；两个公开JSON的Gitleaks复扫0 findings。独立归档审查已PASS，核验182/182文件、6,554,821 bytes、3个ZIP CRC与安全路径，共25项检查且0 findings；W7/W8/W9/W10既有397个归档文件未变，5/5当前source-run receipt pins匹配归档字节。公开metadata-only commit为`aee076c83c1067a35da009fa2e8c061445401f72`，与运行锚点分开记录。W11完成局部离线收口，未获生产接受。

W10保持CLOSED；本批不改变父级87项矩阵的8 `DEV_DONE`、9 `IN_PROGRESS`、70 `PLANNED`计数。**截至W11冻结收口时**，W12处于并行实现与集成阶段，执行验证尚待完成；后续scoped结果见下节。全量`make gate`、remote CI、Python 3.10 runtime、source rights/retention、生产cohort、全历史、财务单位与revision/PIT、自然周期、备份恢复及单写者切换继续OPEN；W11离线收口不代表生产接受。

## 2026-10-27 W11冻结后的AFI freshness scoped进展

本节只记录W11冻结之后的增量，不回写或改变[WAVE11_STATUS.md](WAVE11_STATUS.md)中的历史合同、收据与结论。用户已选择首批证券范围为**全A股**；这只是业务范围决策，不证明权威全量标的全集、上市/退市历史或来源权利已经具备。

| 控制任务 | 本次可确认的完成子范围 | 仍未完成的父任务范围 |
| --- | --- | --- |
| 204-E02-04（仍为PLANNED） | [AFI PR #48](https://github.com/cloudQuant/ai-for-investor/pull/48)为OpenData异步请求增加有界deadline/请求与重试保护，覆盖该任务的一部分传输层边界。 | 尚不能据此关闭统一认证、所有消费场景的单位/时区、request_id及429/503/合法空/未覆盖等完整错误语义矩阵。 |
| 204-E03-01（仍为IN_PROGRESS） | 既有[WAVE5_STATUS.md](WAVE5_STATUS.md)记录的股票1d图表REST直读仍仅是一个查询路径；本次[OpenData PR #3](https://github.com/cloudQuant/opendata/pull/3)与[AFI PR #49](https://github.com/cloudQuant/ai-for-investor/pull/49)又补上固定`stock_daily`域级freshness REST读取代理。 | 本次没有扩展到行情业务列表/搜索、逐标的coverage、主题卡及其他消费者；既有标的目录选择器不证明生产全集。域级freshness不是这些业务读路由，也不等于逐标的覆盖证明。 |
| 204-E05-02（仍为PLANNED） | AFI PR #49在行情页为OpenData模式接入域级`stock_daily` freshness状态；只读固定域接口，失败不以AFI本地coverage替代。 | 未完成逐标的coverage/完整性状态、全历史状态分类及旧数据管理入口兼容。接口的`missing`只表示中台未测得freshness，不能解释为确定无数据。 |

此次为scoped离线证据：OpenData PR #3对应的API专项为73 passed、freshness覆盖率98%，另有HTTP专项1 passed；AFI PR #49后端19 passed、前端20 passed，`vue-tsc`与构建通过。具体范围与限制记录于上述PR。该证据只覆盖所列合同、代理和页面路径，不是全仓门禁、真实全A股数据验证或生产验收；AFI PR #48与#49均为独立合并增量，不改变W11收据。

全A股权威全集及稳定身份映射、北交所与退市历史的可授权来源、逐标的全历史覆盖，以及生产凭证/部署/自然周期验证仍未完成。不得从当前目录选项、日线行或财报脚本反推全集或历史退市覆盖。父级87项控制任务分母和状态计数不变；上述子范围不足以将204-E02-04、204-E03-01或204-E05-02标为完成。

## W12 OpenData 新浪财报 scoped 验证

[OpenData PR #4](https://github.com/cloudQuant/opendata/pull/4)已合入。其单标的离线fixture专项为405 passed，data与pipeline目标模块覆盖率各不低于90%、合计92.27%；随后在最终dev基线上运行的对应精简回归为85 passed。以上仅为本地scoped证据，不是全量A股或生产数据验收。

该能力默认禁用，尚未获得live来源授权或生产验证。长JSON响应、发布事务时限及生产心跳/负载行为仍待验证；本记录不改变W11冻结记录，也不将相关父任务标为完成。

## 2026-10-27 AFI PR #52/#53 合入后的消费端与证券范围状态

本节记录当前 `dev` 已合入的两个 AFI PR 及其验收边界，不改变历史 wave 收据，也不自动关闭父级控制任务：

| PR | 已合入范围 | 证据及未覆盖范围 |
| --- | --- | --- |
| [AFI PR #52](https://github.com/cloudQuant/ai-for-investor/pull/52) | 合入官方全 A 股来源核验文档；代码侧无数据采集或证券主数据实现。 | [来源记录](OFFICIAL_A_SHARE_UNIVERSE_SOURCES.md)区分了沪深北与全国股转的网页证据、读取限制和许可待核项。该文档不证明已取得全量证券名录、退市历史或数据再分发授权。 |
| [AFI PR #53](https://github.com/cloudQuant/ai-for-investor/pull/53) | 在 `MARKET_DATA_OPENDATA_ENABLED` 路径下，将 `/api/v1/realtime/ticks/historical` 的精确股票日线请求路由到 OpenData，并保留关闭开关时的既有路径。 | 对应定向验证为 **21 passed**；Provider HTTP 由 `httpx.MockTransport` 截获，其他依赖使用测试隔离 SQLite/stubs。该运行禁用了 pytest-timeout 插件，因此对 `timeout`、`timeout_method` 两项 pytest 配置产生警告。测试只证明限定请求、投影与错误边界，不证明真实 OpenData 服务/供应商数据、生产数据库、部署、负载或自然周期运行。测试文件：[test_opendata_direct_query.py](../../../src/backend/tests/test_opendata_direct_query.py)。 |

PR #53 的 qfq 路由与字段投影通过 MockTransport 合同验证，不等于 qfq 因子来源、锚定日、版本或数值质量已验收；成交量单位换算和真实数据质量也未独立验收。二者均保持 OPEN。

### OpenData PR #5：Sina 离线 enqueue 组件

[OpenData PR #5](https://github.com/cloudQuant/opendata/pull/5) 已合入 `dev`，交付的是默认不接入生产的离线 enqueue/journal 组件，不是已启用的新浪采集任务。局部验证为 **132 项 SQLite/scheduler-stub 测试通过**：fanout pipeline 覆盖率 **94%**、journal pipeline **98%**、合计 **96%**；Alembic `0013` 迁移另有 **44 项 SQLite 专项测试通过、覆盖率 79%**。这些证据未验证 MySQL 或 PostgreSQL；尤其跨进程锁行为和数据库时钟语义没有实测，不能外推为跨数据库支持。

真实 job 仍禁用且未经审查，source grant 状态为 **UNKNOWN**；当前固定 manifest 仅含 **SH/SZ**，不含 BSE。尚待定义并验收每个 slot 的版本化 manifest，以及 fanout journal/账本的保留策略。OpenData PR #6 后续加入离线 slot 对账，但不改变这些来源和生产边界；上述离线测试不访问真实 Sina 来源，也不构成真实采集、来源授权、生产部署或自然调度验收。

Sina fanout 仍未完成生产验收：进程停机或最大实例变化时可能漏掉调度 slot；离线对账器没有生产入口、告警或补采能力；交易日历对账、全局跨进程配额与协调仍未解决。process-v1 worker 仍 disabled 且没有 schedule；其 slot 约束必须先与对账 cron 方案协调，再讨论接线。来源权限、BSE 范围与历史映射、全 A 生命周期以及逐标的全历史覆盖继续 OPEN。在上述风险及证据项关闭前，不得将 fanout 标为完成或生产可用。

### OpenData PR #6：离线 UTC cron slot 对账

[OpenData PR #6](https://github.com/cloudQuant/opendata/pull/6) 已合入 `dev`，仅实现单代 slot 的离线 UTC cron 对账。专项 **167 项 SQLite 测试通过**；reconciler 覆盖率 **100%**、journal **95%**、合计 **96%**。它没有生产调用入口、告警或补采/重放能力，不是 job 调度接线或真实采集验收。

process-v1 目前仍 disabled 且没有 schedule；将它接到 slot 对账 cron 前，必须先解决两者的 slot/代际约束。MySQL/PostgreSQL、交易日历对账、generation rollover 和历史初始 slot 边界均为 **NOT_ASSESSED**；单一 SQLite 离线结果不能证明数据库锁、时钟或跨代行为。对账命中 group 只证明该组已登记，不证明当时选取了哪些证券或采集成功；初始时间是 exclusive 下界，其之前为 **NOT_ASSESSED**。全 A（含北交所/BSE）、来源授权与生产上线验收仍未完成。

### OpenData PR #7：离线 SQLite source attempt token-bucket gate

[OpenData PR #7](https://github.com/cloudQuant/opendata/pull/7) 已合入，增加离线 SQLite source attempt token-bucket gate。专项 **101 项隔离测试通过**，覆盖同机两个进程竞争；source 模块覆盖率 **90.26%**。这只验证本地 SQLite 隔离范围，不证明多主机协调或 MySQL/PostgreSQL 的锁与时钟语义。

该 gate 未接入 HTTP 请求路径或真实 Sina grant；Sina 仍禁用，授权状态为 **UNKNOWN**。它不提供日/run 总额度、严格滚动窗口或在途并发上限。授权证据是人工声明，不是法律自动验证；保存的策略快照不能完整重算；备份恢复和生产接线仍待验证。因此本 PR 不构成真实来源授权、生产限流或上线验收。

### OpenData PR #8：HTTP source attempt 门禁接线切片

[OpenData PR #8](https://github.com/cloudQuant/opendata/pull/8) 已合入 `dev`。专项 **352 项隔离测试通过**；HTTP client 模块语句+分支综合覆盖率为 **90.446%**，request budget 模块为 **98.571%**。HTTP 门禁通过显式注入进行验证，隔离持久化使用 SQLite。

该切片没有接入真实新浪来源或调度，其他 HTTP/采集调用路径也没有被门禁覆盖；测试不证明生产数据源授权、跨主机竞争、生产数据库行为或生产部署。它不改变 Sina 禁用、grant **UNKNOWN**、策略证据、备份恢复及生产接线仍待验收的状态。

**全 A 股全集及全历史覆盖仍未完成**：包含北交所在内的权威当前目录、退市对象、跨代码身份映射和逐标的实际起点均没有经本次 PR 验收。PR #52 的官方来源调查是调查文档，不是数据源落地；PR #53 的历史日线读取路由也不提供历史 universe 分母或 lifecycle 证据。不得以新浪行情最早记录、当前目录或已成功查询替代上市/退市证据。`204-E02-04`、`204-E03-01`、`204-E05-02` 及其父级状态需按既有验收标准逐项更新，不能因 PR 合入自动标完成。

## 2026-10-27 AFI PR #56 上证50 benchmark reader

[AFI PR #56](https://github.com/cloudQuant/ai-for-investor/pull/56) 已合入 `dev`，增加默认关闭、可选使用 OpenData 的上证50 benchmark reader。#56 合并后又补充了三场景真实 ORM 回归，覆盖 `score_pending → apply_outcome` 并使用内存 SQLite；这项后续补测与本文档更新一并交付。测试文件整套 **23 passed**，Provider HTTP 使用 `httpx.MockTransport`、股票行情使用 fake；隔离运行有 `timeout`、`timeout_method` 两项 pytest 配置警告。这些结果不构成生产 source、真实行情或生产数据库验收。实现和测试见 [opendata_sse50_benchmark.py](../../../src/backend/app/services/stock_signal/opendata_sse50_benchmark.py) 与 [test_stock_signal_opendata_benchmark.py](../../../src/backend/tests/test_stock_signal_opendata_benchmark.py)。

以下生产与业务验收仍未完成：生产数据库上的 `score_pending` 持久化；真实数据源授权与数据落库；逐日历史 coverage；与 Eastmoney 的跨源对照；运维告警。个股 20 日收益可计算、但 benchmark 不可用时，`outcome_status` 仍可能为 `scored`，相应的 `benchmark_*_return` / `excess_*_return` 字段可能为 null；不可用原因目前只写日志，未持久化，也没有相应告警。需要在有授权的真实数据与目标生产数据库上完成验证，并补齐可审计原因和告警后，才可评估上线。

PR #56 仅覆盖上证50 benchmark 读路径，不改变全 A 股权威全集、BSE、退市与跨代码身份映射、逐标的全历史覆盖仍未完成的结论；不得据此关闭相关历史恢复任务或宣称全 A 股历史已验收。

## AFI PR #62 benchmark 区间对齐

AFI PR #62 已合入 `dev`，对齐 benchmark 与个股回报的区间边界；定向验证为 **24 项后端、2 项前端测试通过**，覆盖区间匹配、年化以及 ledger fail-closed degraded/UI 提示行为。生产 NAV、收盘盯市、TWR 和实盘行为仍未验证，FF 问题仍未解决；不能据此宣称 benchmark 全链路已完成或改变迭代204整体未完成的状态。

## 2026-10-27 AFI PR #64–#66 与 OpenData PR #9–#10 局部进展

### AFI PR #64：SSE50 历史重算 fail-closed

[AFI PR #64](https://github.com/cloudQuant/ai-for-investor/pull/64) 已合入 `dev`。当请求日期不是当天时，在读取日历、获取成分股或创建 run 之前拒绝历史和未来重算；当天流程仍使用 Asia/Shanghai，并保留 19:10 收盘后边界。run snapshot/key 记录 universe evidence 和 digest，但当前成分仅是 current-only，仍为 **UNVERIFIED**；provider-attested 数据只检查合同与时间边界，没有独立来源验证。

两个定向 stock-signal 测试文件 **11 项隔离测试通过**，使用 synthetic providers 与内存 SQLite；pytest-timeout 未加载，出现 `timeout`、`timeout_method` 两项配置警告。历史拒绝（含注入 PIT provider）、收盘时间、scope/evidence 和幂等均有覆盖。历史重放仍不可用：没有可信的历史成分、输入和预测时点语义；19:10 是固定限制，较早的自定义 cron 会被拒绝。真实 provider 和生产数据库未测试。

### AFI PR #65：来源授权证据记录

[AFI PR #65](https://github.com/cloudQuant/ai-for-investor/pull/65) 已合入，新增新浪、Eastmoney、THS/Fuyao 及相关交易所/指数数据的官方公开条款和未决许可问题。文档评审包含 whitespace check 与独立来源/适用性审查；没有访问实时金融源、用户数据库或生产授权。公开页面、公开 API 文档不等于获得自动采集、留存或下游使用授权；实际合同适用性仍须确认。因此来源授权状态仍为 **UNKNOWN**，该文档不是法律结论，也不自动创建 grant。

### OpenData PR #9：股票历史窗口候选规划

[OpenData PR #9](https://github.com/cloudQuant/opendata/pull/9) 已合入 `dev`。它基于传入的 instrument registry、task 和 dataset contract，生成确定性的股票日线回补窗口候选：按已验证的 alias segment 拆分为现有查询合同接受的有界闭区间；unknown 起点、过时 lifecycle、alias gap、未验证 BSE 路由和不确定退市边界保留为 blocker。定向 **16 项隔离内存测试通过**，目标 pipeline 模块 statement+branch 综合覆盖率 **94.8949%**；Ruff、format、Bandit、导入静默的 mypy 与独立 lifecycle/alias review 通过。

候选是可构造的 RunRequest DTO，但 planner 不执行 dispatch；当前股票 job 仍 disabled、unreviewed，若候选被另行提交给其他 reviewed job，RunService 不会自动强制这些 blockers。它不检查 publications、交易日历或 source retention，因此窗口只是基于生命周期证据的计划范围，不是观测到的真实 head/interior/tail gap。未装载权威全 A、未发生产 grant，也没有采集数据；恢复与生产验收仍开放。

### OpenData PR #10：四个独立指数日线数据集

[OpenData PR #10](https://github.com/cloudQuant/opendata/pull/10) 已合入 `dev`，离线准备上证50、沪深300、沪深500、沪深800四个相互独立且不可混读的 index-daily dataset contract 与 reviewed-job 模板。各自固定一个指数并校验请求代码、区间、归一化记录和 publication identity；拒绝空/非法 batch。**24 项隔离测试通过**，使用 synthetic THS 记录、临时 SQLite 与进程内 v2 API；provider contract 覆盖率 **92.857%**、pipeline **98.214%**，定向静态检查和独立审查通过。

作业仍 disabled、unscheduled、unreviewed，source rights 为 **UNKNOWN**；生产 fetch guard 会在 provider 调用前拒绝，fixture 测试替换了 guard 与 transport，不代表获得真实授权。未测试 live provider、生产数据库或自动调度。当前映射中 OHLC 单位为指数点、volume 为股、amount 排除；来源权利、质量、历史覆盖和 provenance 对照仍未验证，000016 与 000906 尚无独立跨源比对。该 v2 immutable publication 也不是旧 DWD pipeline 验收。

### AFI PR #66：默认关闭的 OpenData 指数 benchmark reader

[AFI PR #66](https://github.com/cloudQuant/ai-for-investor/pull/66) 已合入，新增默认关闭的 OpenData v2 published-snapshot 路径，范围为沪深300、沪深500和沪深800风险 benchmark endpoint。路径检查当前用户 `READ_DATA` 权限、专用 route capability、display/backtest source-use authorization，再检查 coverage 并绑定到已取证 publication；失败不回退到 AkShare。

定向 **219 项 synthetic 隔离测试通过**，使用内存 SQLite、进程内 ASGI 和 MockTransport；pytest-timeout 配置警告保留。覆盖率优先拒绝、grant/purpose/capability、publication pin、分页、旧路由回退保护和响应映射有测试，但当前 OpenData coverage 恒为 **UNKNOWN**，source rights 与数据质量也 UNKNOWN，index jobs disabled/unreviewed，生产 grants/config 未验证；因此该 reader 不是生产可用功能。它仅校验 SHA 字段格式和 identity binding，不在 client 重算 row/content hash；真实 source、生产数据库及全量指数历史均未测试。

Portfolio Fama–French（FF）路径尚未迁移。启用该 flag 后，三个指数的其他旧 `BenchmarkService` 调用（包括 FF 路径）会 fail closed，而不是继续旧源回退。该增量不改变父级控制任务分母或完成统计，也不能关闭指数来源授权、历史覆盖、生产部署等开放事项。

## 2026-10-27 OpenData PR #12–#17 与 AFI PR #69、#71 增量

以下 PR 均已合入各自仓库的 `dev`，仅关闭其明确限定的代码或文档子范围。PR 合并和局部离线验证不等于数据已接入生产、全 A 股数据已采集或全历史恢复已完成；迭代204整体仍未完成。

| PR | 已合入的限定范围 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #12](https://github.com/cloudQuant/opendata/pull/12) | Sina 日线 v2 离线归一化合同与 fixture 驱动的期货、期权、可转债记录归一器；未提供线上抓取或旧 v1 发布接线。 | 缺失成交额保留为 `null`，不伪造为零；真实源调用、v1 数据修复、质量/单位确认、调度和生产仓库接线仍未验收。 |
| [OpenData PR #13](https://github.com/cloudQuant/opendata/pull/13) | 扩展发布记录集完整性读取及 coverage 证据评估的局部实现，按固定 publication、合同和有界记录集计算证据。 | 当前证据及 pin 不能替代独立来源真实性和生产授权；没有真实采集、生产数据库验证或生产 grants。来源/数据生命周期覆盖、数据库方言与运维操作仍有未验证边界。 |
| [OpenData PR #14](https://github.com/cloudQuant/opendata/pull/14) | 将 Fuyao 来源尝试门禁作为可选依赖接入 THS transport / financial fetcher 调用路径，门禁拒绝时不发起来源请求。 | 可选 gate 尚未由生产调度器和可信 grant 工厂配置；不包含生产凭证、全局日/run 额度或跨主机协调。没有真实 Fuyao 抓取、落库或自然周期运行验收。 |
| [OpenData PR #15](https://github.com/cloudQuant/opendata/pull/15) | 增加历史查询窗口与证券生命周期评估的纯评估切片，使请求窗口状态与全生命周期覆盖证据分开表达。 | 不采集、不补数，也不证明窗口内存在完整观测；权威证券全集、上市/退市及停牌日历证据、真实 publications 和 source retention 均未因此获得。全生命周期历史恢复保持开放。 |
| [OpenData PR #16](https://github.com/cloudQuant/opendata/pull/16) | 纯规划器输出不可直接执行的财报候选，并附带阻断项。 | 规划器本身没有调度、抓取或落库能力，也不会阻止其他生产入口执行；外部来源证据未经认证。该候选不证明证券全集、BSE/退市覆盖或历史修订/PIT 语义；全 A 股财报 backfill、生产调度和落库仍未验收。 |
| [OpenData PR #17](https://github.com/cloudQuant/opendata/pull/17) | 为跨仓消费链路提供真实 HTTP wire 上的 synthetic 样本联调。 | 使用合成数据和本机 URL 策略验证；没有访问真实数据源，也不证明 source grant、数据质量、全 A 股覆盖或生产调度。 |
| [AFI PR #69](https://github.com/cloudQuant/ai-for-investor/pull/69) | 记录用户对 AkShare 与 Fuyao 数据使用的授权声明，以及仍未明确的适用数据范围和限制。 | 记录的是用户声明，不构成对供应商合同、底层端点权限、市场/历史范围、频率、留存期限或下游分发的独立核验，也不自动创建可执行生产 grant。未据此启动真实采集。 |
| [AFI PR #71](https://github.com/cloudQuant/ai-for-investor/pull/71) | 接入 OpenData v2 synthetic HTTP wire 联调样本及本机 URL 策略验证。 | 与 OpenData PR #17 的联调结果为 **1 项 synthetic HTTP wire 测试通过、8 项本机 URL 策略测试通过**。这是测试环境协议/地址策略证据，不是对真实供应商数据、实际 source grant、quality、全 A 股历史或生产调度的验收。 |

### 跨仓验证与待办

OpenData 发布/coverage wire 与 AFI v2 消费端已完成本机 synthetic 联调：真实 HTTP wire 合成样本 **1 passed**，本机 URL 策略 **8 passed**。这些结果验证测试环境中的请求/响应路径及地址策略；测试数据是合成样本，不代表真实来源接入或来源授权已核验，也不证明数据 quality、全 A 股及历史覆盖、生产 jobs/provider 接线或自然调度已完成。生产端点、凭证和部署仍需单独验收。

用户已选择全 A 股作为首批目标范围，并声明 AkShare、Fuyao 可使用；这不表示系统已取得经核验的权威全 A 股含北交所及退市证券目录，也不证明逐证券上市起点、历史别名、数据保留边界、全量数据或内部生产 API 已就绪。完整历史仍需按标的和业务键核对 head、interior、tail；未知边界必须继续标记，不能以当前目录或最新记录代替历史分母。

完整 mypy 检查仍受历史依赖问题影响，按用户要求暂缓处理；CI 问题也暂缓。这里不把两项暂缓写成通过，也不据此降低代码验收或生产验收边界。后续合并前仍应按各 PR 的限定证据审查；真实来源与全 A 生命周期证据、财报运行/发布链路以及部署和自然周期验收完成后，再更新对应父级控制任务状态。

## OpenData PR #18–#20 增量

以下 PR 已合入 OpenData `dev`。它们各自的专项测试与覆盖率只支持所列局部代码范围，不表示全 A 股数据采集、历史恢复、PIT 或生产财报链路已验收。

| PR | 已合入的限定范围 | 局部证据与未完成事项 |
| --- | --- | --- |
| [OpenData PR #18](https://github.com/cloudQuant/opendata/pull/18) | 财报精确观察使用独立值对象表达。 | 专项 **59 项测试通过**，目标模块 statement+branch 综合覆盖率 **94.17%**。这是值对象切片，不代表接入真实财报抓取、raw archive、source attempt 账本、生产响应解码或调度，也不证明历史修订/PIT 完整。 |
| [OpenData PR #19](https://github.com/cloudQuant/opendata/pull/19) | 新浪股票代码解析对错误/不支持的符号 fail closed。 | **57 项测试加 2 项补充测试通过**，目标范围覆盖率 **100%**。北交所及证券代码 `689` 仍不支持；不得将拒绝非法符号的覆盖率解释为全市场代码支持或全 A 股覆盖。 |
| [OpenData PR #20](https://github.com/cloudQuant/opendata/pull/20) | THS 财报数值以原始 `Decimal` 表达，避免在该切片中提前转换为浮点数。 | 专项 **73 项测试通过**，目标模块 statement+branch 综合覆盖率 **96.71%**。测试使用独立内存解码器；raw archive、source attempt 持久账本、真实 HTTP 响应、单位语义绑定及生产接线均未完成或未验收。该切片不构成全 A 股财报采集或 PIT 历史修订支持。 |

## OpenData PR #21：THS 原始响应实体字节切片

[OpenData PR #21](https://github.com/cloudQuant/opendata/pull/21) 已合入 OpenData `dev`。Fuyao transport 会在成功响应结果中返回 HTTPX 解压后的 response entity bytes，并在对象 `repr` 中隐藏字节内容；因此这里的“原始”指解码前的响应实体内容，不是压缩传输层上的原始 wire bytes。响应大小上限在 HTTPX 缓冲并解压后检查。定向测试 **190 项通过、7 项 e2e 排除**，客户端目标范围 line+branch 覆盖率 **95.8%**。

响应字节虽已随 transport 成功响应返回，仍未接入财报 decoder 或 raw archive；没有真实生产响应验证。跨仓 HTTP wire 验证仍使用 synthetic 样本；上述结果不代表真实来源响应、raw archive、source attempt、单位绑定、数据质量、全 A 股覆盖、PIT 历史或生产调度已完成。

## OpenData PR #22：合成 Fuyao transport 到精确 decoder 联调

[OpenData PR #22](https://github.com/cloudQuant/opendata/pull/22) 已合入 OpenData `dev`，用 `MockTransport` 合成响应串联 Fuyao transport 与精确财报 decoder，**3 项测试通过**。这是测试级拼接：没有接入生产 `Fetcher`，没有真实来源响应或 raw archive，也不验证历史修订/PIT、全 A 股覆盖或生产调度。该结果不能改写 PR #21 的生产边界；真实响应、存档与生产 Fetcher 接线仍待完成。

## 未合并的 Fuyao 精确财报入口

当前有一项 Fuyao 精确财报入口实现保留在 OpenData 本地，只有 **2 个未跟踪文件**（源码与测试），尚未验收或合入 `dev`。其合成测试为 **147 passed**，statement+branch 综合覆盖率 **99.16%**，双重 review 已完成；这些证据只覆盖 synthetic 数据下的代码路径。

按 `CODE_QUALITY.md` §5.2，验收还需要真实来源的 income、balance、cashflow 响应证据。当前缺少这三类真实响应样本，因此不能将该入口视为验收完成或提交合并。源码和测试仍保留在本地；受限权限备份及测试证据位于 `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-exact-fetcher/`。

当前执行进程未发现 Fuyao API key；这只描述当前进程环境，不证明其他环境或部署不存在凭证。用户已声明 AkShare 与 Fuyao 可使用，无需重复确认该声明；真实响应证据和具体入口验收仍未完成。该本地实现不代表全 A 股覆盖、历史 PIT 能力、生产调度或生产落库已经完成。

## 2026-10-27 OpenData PR #23–#25 增量

以下三个 PR 已合入 OpenData `dev`，只记录各自完成的文档或隔离代码范围，不改变迭代204整体未完成状态。

| PR | 已合入范围与验收证据 | 局限与未完成事项 |
| --- | --- | --- |
| [OpenData PR #23](https://github.com/cloudQuant/opendata/pull/23) | 增加数据权利登记文档，记录用户声明 AkShare 与 Fuyao 数据可使用及后续需核对的来源、范围和限制。 | 这是声明与治理记录，不是对供应商合同、具体端点、市场/历史范围、频率、保留期限或内部 API 用途的独立核验；没有因此创建可用于生产抓取的 grant。 |
| [OpenData PR #24](https://github.com/cloudQuant/opendata/pull/24) | 增加受限的内容寻址 raw-evidence reader。它校验请求上下文与状态、可信 UTC 上界、manifest/body 摘要及文件系统安全属性，并限制证据大小。专用隔离测试 **28 项通过**，目标文件语句与分支覆盖率 **96.43%**；定向 Ruff、导入静默 mypy、Bandit 和安全 review 通过。 | 摘要用于完整性比对，不是签名或来源真实性证明；同一有效用户仍可能修改其可写文件。reader 尚无生产消费者、备份/恢复、生产 API ACL 或真实采集接线；不能据此认定 raw archive 已形成生产级不可变存储。 |
| [OpenData PR #25](https://github.com/cloudQuant/opendata/pull/25) | 使用一份录制的 Sina 财报响应 fixture（103 行，单只上交所证券资产负债表样本），通过真实 HTTP transport 路径、已审查的子进程 worker、归档、SQLite 发布和 REST 分页完成端到端隔离验证；专项 **2 项测试通过**。 | fixture 不是本次 live 上游抓取，样本元数据也未独立验证来源签名/授权；测试不证明完整财报类型、字段单位、数据质量、全 A 股或北交所覆盖、逐标的历史起点/缺口、PIT/修订语义、生产数据库、生产 API、备份恢复或自然调度已验收。 |

本段记录的是 PR #23–#25 合入时的历史状态：当时财报 capture/observation schema 与 store 尚未合入 `dev`。后续 schema 和 store 的合并状态分别见 OpenData PR #26、#27 节。Fuyao 精确财报入口仍缺真实 income、balance、cashflow 响应证据，继续保持未验收和未合并状态。

全 A 股仍是首批目标范围，不是已完成的数据覆盖事实。全市场权威证券目录（含北交所与退市对象）、逐证券实际上市起点、数据源可保留的历史边界、按业务键核对 head/interior/tail 的证据均未由 #23–#25 提供。没有建立可回放的 PIT/历史修订数据，也没有启用线上采集任务或自然周期调度；上述范围继续 OPEN。

## OpenData PR #26：独立财报 archive schema

[OpenData PR #26](https://github.com/cloudQuant/opendata/pull/26) 已合入 `dev`，新增独立的财报 archive Alembic migration chain 与四张财报 capture/observation 相关表。本节只确认 schema/migration 的局部交付，不表示 capture store 或采集服务已经接线。

验收证据保存在 [`2026-10-27-financial-migration`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-financial-migration>)：隔离 SQLite migration 专项 **27 项通过**；`env.py` 覆盖率为 **94.44%**，revision 覆盖率为 **89.87%**。在新建的隔离 **MySQL 8.4.0** 实例中完成了真实 upgrade；保留一条 capture 记录后尝试 downgrade，迁移按设计拒绝降级，且版本、四张表和记录均保留。Ruff、format、导入静默 mypy 与 Bandit 的定向静态检查记录也保存在该目录。

边界：没有实测 MySQL 8.0；没有生产数据库、生产部署或线上写入验证。独立 schema 与应用层约束不会阻止有数据库写权限的主体直接篡改或删除数据，因此不构成数据库防篡改/WORM 保证；也没有 raw evidence 到 schema 的生产 writer、备份恢复或运维接线。该迁移不证明全 A 股/北交所历史覆盖，也不建立 PIT 或历史修订能力。

财报 observation store 在最初与未验收的 Fuyao 精确财报 fetcher 耦合实现阶段尚未验收。该阶段首次测试为 **4 failed、12 passed**，目标文件覆盖率 **69.18%**；失败和覆盖率原始记录分别保存在 [`first-pytest-failed.log`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/first-pytest-failed.log>) 与 [`first-coverage.json`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/first-coverage.json>)。这是早期失败历史，不代表之后解耦和修复阶段的结果；后续验证及合并状态见 PR #27 节。早期实现与失败证据继续保留。PR #26 本身只交付 schema/migration，不能单独视为完整的财报落库链路。

## 2026-10-27 AFI PR #79–#80 与 OpenData store 解耦后的局部进展

### AFI PR #79：财报同比数据缺失时不再用相邻披露替代

[AFI PR #79](https://github.com/cloudQuant/ai-for-investor/pull/79) 已合入 `dev`。当来源没有提供同比值时，不再把相邻披露（例如年报与后续季度）误算为同比增长；使用来源给出的同比值，缺失时显示数据不足。两项离线定向测试通过，覆盖年报/季度相邻披露及保留来源同比值；定向 Ruff 与独立 review 通过。证据：[pytest.log](</home/yun/Documents/ai-for-investor/var/reports/afi204/2026-10-27-financial-yoy/pytest.log>)。这些测试不验证真实上游对同比字段的定义、覆盖或数值质量；相关单位/语义仍需来源级核验。

### AFI PR #80：财报分析叙述绑定到可用证据

[AFI PR #80](https://github.com/cloudQuant/ai-for-investor/pull/80) 已合入 `dev`。报告区分报告期与披露时间，不再无证据断言盈利稳定、股东回报、两位数 ROE 或数据质量；缺值明确呈现，参考价格与实时行情分开，分析文字根据可用财务、价格和新闻证据表达。网络关闭且配置隔离下 **19 项定向离线测试通过**，定向 Ruff 与独立 review 通过；证据：[pytest.log](</home/yun/Documents/ai-for-investor/var/reports/afi204/2026-10-27-financial-report/pytest.log>)。该改动没有补足公告时点历史证据，因此不能支持历史 PIT 分析。财务字段单位与来源百分比语义、既有财务评分逻辑及行业专用模板假设仍未完成或验证；CI 修复仍按前述约定暂缓。

### OpenData financial observation store：PR #27 合并前的解耦回归收据

store 已从未验收的 Fuyao 精确财报 fetcher 解耦；合并前的隔离回归使用合成输入，**54 项测试通过**，目标 store 文件语句与分支综合覆盖率 **93.11%**。收据：[decoupled-pytest.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/decoupled-pytest.log>)、[decoupled-coverage.json](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/decoupled-coverage.json>)。早期首次运行的 4 failed/12 passed 与 69.18% 记录继续保留为历史，不被后续结果覆盖；该预合并回归结果由 OpenData PR #27 的 SQLite 收据再次确认。

在上述预合并收据时，store 尚未合入 `dev`；当前状态见下方 PR #27。合成数据不等于真实 Fuyao 上游响应或授权/字段语义验收。源码、测试副本与分阶段证据继续保存在 [`2026-10-27-pending-financial-store`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store>)。

以上增量不改变全 A 股仍为目标而非已完成覆盖的状态，也不建立 PIT、单位/来源百分比语义、评分或行业模板能力。逐标的全历史、财报修订历史、真实来源到 OpenData 的生产采集、调度、发布及 AFI 全部消费者迁移仍保持 OPEN。

## OpenData PR #27：financial observation store 合并与受限验收

[OpenData PR #27](https://github.com/cloudQuant/opendata/pull/27) 已合入 `dev`，交付独立的财报 observation store：在事务前验证归档响应和 decoder references，再使用调用方提供的数据库连接插入或比较 capture、observations、source pointers 与 quarantined rows。它是可复用的存储原语；**未接入生产 RunLedger worker/job、实际采集任务、调度或 REST API**。后续 PR #28 增加了使用真实 RunLedger SQLite 路径的合成数据事务测试，见下节；尚未形成生产采集/查询链路。

验收证据保存在 [`2026-10-27-pending-financial-store`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store>)（该历史目录同时保存失败与修正后的收据）：常规隔离 SQLite 回归为 **54 passed、4 个仅 MySQL 用例 skipped**，statement+branch 综合覆盖率 **93.11%**；结果见 [final-sqlite-pytest.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/final-sqlite-pytest.log>) 与 [final-sqlite-coverage.json](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/final-sqlite-coverage.json>)。独立临时 **MySQL 8.4.0** 实例上的 4 个 opt-in 用例通过，覆盖事务提交/回滚、精确数值，以及 capture replay、共享 observation 和冲突 capture 的真实锁等待行为；测试实例及随机 schema 已清理。MySQL 收据见 [final-mysql-pytest.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/final-mysql-pytest.log>) 与 [final-mysql-results.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/final-mysql-results.log>)。

初次 MySQL 隔离运行因 pytest 临时 fixture 路径不在私有 `TMPDIR` 下而失败；失败发生在 fixture 路径断言，记录见 [mysql-first-pytest-failed.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/mysql-first-pytest-failed.log>) 和 [mysql-first-results.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/mysql-first-results.log>)。修正隔离目录设置后的上述独立 MySQL 8.4 重跑通过，初次失败仍作为验收审计记录保留。

局限仍明确：MySQL **8.0 未测试**；source identity 与单位映射属于 operator declaration，mapping digest 未对完整单位映射表重新计算核验；单次 capture 最多 **64 行**，超限即拒绝、不静默截断。raw filesystem 写入与 SQL 事务不具原子性，且直接数据库 UPDATE/DELETE 未被阻止，故不提供 WORM/数据库防篡改保证。用例使用合成输入，未验收真实 Fuyao 响应、授权、source field/unit semantics、全 A 股或北交所历史完整性；PIT 与财报修订历史也未完成。

该 PR 的定向 Ruff、Bandit 和导入静默 mypy 通过；相应记录见 [bandit.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/bandit.log>) 与 [target-mypy.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/target-mypy.log>)。full-import mypy 仍报告既有的第三方 YAML/requests stubs 与其他模块类型问题，未作为通过项；记录见 [full-import-mypy-failure.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-financial-store/full-import-mypy-failure.log>)。AFI #79/#80 已合入，但财报字段单位/来源百分比语义、公告时点 PIT、既有评分逻辑和行业模板假设仍未完成；OpenData store 合并也不改变全 A 股完整历史、Fuyao 上游采集与生产 REST/调度接线尚未完成的状态。

## OpenData PR #28：RunLedger SQLite 事务集成测试

[OpenData PR #28](https://github.com/cloudQuant/opendata/pull/28) 已合入 `dev`，增加真实 RunLedger SQLite 路径上的 **3 项合成数据事务测试**：成功提交、callback 失败回滚，以及 callback 执行后租约到期时回滚。三项测试通过；证据：[pytest.log](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-runledger-financial/pytest.log>)。

该验证覆盖 SQLite 上的本地测试级事务接线，输入仍为合成财报数据。MySQL RunLedger 并发/事务行为、生产 worker/job、真实 Fuyao 上游采集、调度和 REST 发布仍未完成；不得将这三项测试解释为生产 RunLedger 接线或真实财报数据验收。

## OpenData PR #29–#30：财报 capture 只读巡检与脱敏断言

[OpenData PR #29](https://github.com/cloudQuant/opendata/pull/29) 已合入 `dev`，增加有明确 scope、预算和分页边界的只读财报 capture integrity audit；它只核对被选中的 capture 与已验证 manifest/response body 的引用，不记录响应内容，也不修改或清理数据。使用 SQLite 与 synthetic evidence 的定向验证为 **40 项测试通过**，statement+branch 综合覆盖率 **98.25%**。测试范围不证明数据库完整性、来源真实性/授权、全历史覆盖或无 orphan 文件，也未验证 MySQL、备份恢复、生产调度或 REST 接线。

[OpenData PR #30](https://github.com/cloudQuant/opendata/pull/30) 已合入，为异常输出增加 **2 条脱敏断言**并通过定向隔离测试：malformed scope 与 timezone 错误不应泄露底层私有异常文本。该增量只验证错误文本边界，不扩展 #29 的数据、数据库方言或生产验收范围。

## 北交所 920202 Eastmoney market-code 单次探测

查询目标交易日为 **2026-10-26**；对北交所证券 **920202** 的 Eastmoney 候选 market code `0` 探测于 **2026-10-27 23:45（Asia/Shanghai，UTC+08:00）**在本地执行并生成证据。第一次运行在网络请求前被隔离环境拒绝；第二次仅发出一次请求，返回 `HTTP_NETWORK_FAILURE`，没有取得响应或报文，也没有自动重试。日志保存在 [`2026-10-27-bse-single-probe`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-bse-single-probe>)（[`runtime-refused.json`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-bse-single-probe/runtime-refused.json>)、[`probe-result.json`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-27-bse-single-probe/probe-result.json>)）。脚本中的 `rights_evidence` 文本不是供应商 grant，也不是对合同或数据权限的独立核验。因此 market-code 映射仍未验证；这不是成功采集或真实源响应证据。

用户关于 AkShare 与 Fuyao 可使用的声明已记录，不因本次网络失败重复请求授权。BSE market mapping、可用上游响应、北交所与全 A 股权威证券全集及全历史仍待逐项验证；当前探测不能关闭这些开放项，也不证明 PIT 或生产采集已完成。

## 2026-10-28 局部增量：OpenData PR #31、AFI PR #83–#84

以下更新仅记录各 PR 明确限定的代码与隔离验证结果。它们不改变迭代204整体仍未完成的状态。

| PR | 已合入的限定范围与验证 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #31](https://github.com/cloudQuant/opendata/pull/31) | 增加 runtime database URL endpoint 守卫，拒绝非允许的 URL query 配置，防止通过 query 参数重定向到未经允许的连接选项。定向隔离测试与目标静态检查通过。 | 守卫只验证配置 URL 的 endpoint/query 约束；没有确认运行时实际连接的数据库实例 UUID，也没有核验目标任务表是否为 InnoDB。因此不能据此证明运行实例身份、事务快照条件或生产数据库安全性。 |
| [AFI PR #83](https://github.com/cloudQuant/ai-for-investor/pull/83) | 增加 `.BJ` 与 `CN-BJSE` 及沪深北代码的身份往返离线测试；定向隔离测试 **4 项通过**。 | 这是标识符解析/序列化往返，不是北交所真实行情、数据源路由、证券全集、市场覆盖或历史数据验证；不改变北交所及全 A 股覆盖仍待验收的状态。 |
| [AFI PR #84](https://github.com/cloudQuant/ai-for-investor/pull/84) | 从本机现存 Python 字节码恢复缺失的 `run_with_core_environment.py` 包装脚本，并通过 **6 项隔离单元测试**及一次受限环境中的真实进程替换 smoke。PR 已合入 `dev`。 | 2026-10-28 00:06（CST）的一次历史恢复 service 尝试因缺少 `run_with_core_environment.py` 退出。包装脚本恢复合并后，systemd timer 自动触发了后续尝试；截至 00:28 的只读检查，记录显示 timer 于 00:28:04（CST）触发，service 随后于 00:28:05 以状态码 2 退出，原因是缺少 `run_full_history_recovery_worker.py`。这些后续触发由 timer 自动执行，本轮没有手动启动或重启主服务或恢复 service；本次只读状态检查时，timer 仍为 enabled、active/waiting。主服务没有重启；恢复 worker 缺失问题与启动包装脚本修复是两个独立问题，恢复任务仍未成功运行。 |

OpenData 迁移工作清单仍在开发，尚无通过项目覆盖率门槛的证据，也未合并。它不得用于启动迁移任务或授权作业。全量旧任务迁移、全 A 股含北交所的逐标的真实数据与完整历史核对、生产数据库身份与存储引擎验证、自然调度及恢复演练仍保持开放；迭代204整体未完成。

## OpenData PR #32 与恢复 worker 候选（2026-10-28）

[OpenData PR #32](https://github.com/cloudQuant/opendata/pull/32) 已合入 `dev`。迁移 worklist 定向验证 **95 项测试通过**，覆盖率记录为 **99% / 91%**。本机私有的 2026-10-26 历史清单包含 **1,103 个任务与 10 个 helper**，均未分配、待审且禁用；它基于历史快照，正式使用前必须刷新并重新核对。

恢复 worker 候选源码副本和测试记录保存在 [`2026-10-28-recovery-worker-candidate`](</home/yun/Documents/ai-for-investor/var/reports/afi204/2026-10-28-recovery-worker-candidate/>)；隔离测试 **44 项通过**，收据见 [pytest.log](</home/yun/Documents/ai-for-investor/var/reports/afi204/2026-10-28-recovery-worker-candidate/pytest.log>)。这仍是候选验证：当前 `dev` 缺少所需 controllers/providers/scheduler 接口；强杀后的恢复行为、来源证据与授权、自动执行安全尚未验收。因此不得恢复为可运行的 worker 入口。systemd timer 仍会自动触发恢复 service，而该 service 因 worker 脚本缺失继续失败；没有成功恢复运行。

以上均为局部交付与隔离证据；迭代204整体仍未完成。

## OpenData PR #33：runtime inventory 实例身份与快照边界（2026-10-28）

[OpenData PR #33](https://github.com/cloudQuant/opendata/pull/33) 已合入 `dev`。联合隔离回归 **213 项通过**；定向覆盖率为 runtime inventory **89%**、历史迁移 planner **93%**。本次验证保持既有历史 `1.0` 清单哈希不变。验收证据与日志保存在本机私有目录 [`2026-10-28-pending-inventory-identity`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-inventory-identity>)。

在一次性 MySQL 8.4 实例的 Unix socket 路径上，内部事务/实例身份验收通过：校验了 UUID pin、InnoDB 一致性快照，并确认 MyISAM 表会被拒绝。该结果只覆盖本机隔离 socket 测试；TCP 连接及运行服务实际 endpoint 集成未测试。生产 service 的配置来源和预期 UUID pin 仍需独立核实。本次没有读取生产数据或对生产执行 DDL；任何后续生产核验必须保持生产 DDL 禁用，并在确认配置来源与实例 pin 后另行审查。不能将此 PR 视为生产数据盘点或数据库接线验收。

以上只关闭局部代码与隔离验证范围；生产 inventory、数据读取、完整历史恢复、自动调度和切换仍未验收，迭代204整体未完成。
