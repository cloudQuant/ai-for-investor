# 子代理开发与集成记录

## 当前开发基线（2026-10-28）

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

## Fuyao 精确财报入口早期候选（该记录时未合并）

截至该候选状态记录时，Fuyao 精确财报入口实现保留在 OpenData 本地，只有 **2 个未跟踪文件**（源码与测试），尚未验收或合入 `dev`。其合成测试为 **147 passed**，statement+branch 综合覆盖率 **99.16%**，双重 review 已完成；这些证据只覆盖 synthetic 数据下的代码路径。

按 `CODE_QUALITY.md` §5.2，验收还需要真实来源的 income、balance、cashflow 响应证据。截至该候选阶段，三类真实响应样本均缺失，因此不能将该入口视为验收完成或提交合并；文末记录的后续 partial run 只补充了部分观察，不满足完整验收要求。源码和测试仍保留在本地；受限权限备份及测试证据位于 `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-pending-exact-fetcher/`。

截至 **2026-10-27** 的该次检查，当前执行进程未发现 Fuyao API key；这只描述当时该进程环境，不证明其他环境或后续运行的凭证状态。该本地实现不代表全 A 股覆盖、历史 PIT 能力、生产调度或生产落库已经完成。后续一次受控 Fuyao 运行的有限响应证据见本文末尾；不在文档中记录凭证值。

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

## OpenData PR #34–#35：来源声明与北交所路由保护（2026-10-28）

以下两个 PR 均已合入 OpenData `dev`，仅记录局部代码与隔离验收，不改变迭代204整体未完成状态。

| PR | 已合入范围与局部证据 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #34](https://github.com/cloudQuant/opendata/pull/34) | 增加六组来源结构声明校验；定向隔离测试 **19 项通过**，目标覆盖率 **96%**。日志保存在本机私有目录 [`2026-10-28-fuyao-evidence-declarations`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-evidence-declarations>)。 | 结构声明校验不构成真实上游响应或来源真实性证据；未接入 recorder 或部署。Fuyao 财报 fetcher 仍未验收，所需真实来源证据和生产接线仍开放。 |
| [OpenData PR #35](https://github.com/cloudQuant/opendata/pull/35) | 为 AkShare/Eastmoney 股票日线增加 BSE fail-closed 路由保护，阻止未知市场码；沪深既有行为保留。联合隔离测试 **207 项通过**，三个目标模块覆盖率为 **91% / 92% / 92%**。日志保存在本机私有目录 [`2026-10-28-bse-route-guard`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-bse-route-guard>)。 | 北交所真实源数据、路由映射及逐证券历史覆盖仍未验证；该保护不会生成或补齐 BSE 行情，也不证明全 A 股历史完整。 |

PR #34–#35 的合入与隔离测试只支持各自限定范围；真实来源、生产采集及全 A 股含北交所的完整历史仍待验收，迭代204整体未完成。

## OpenData PR #36：MySQL warehouse migration compatibility（2026-10-28）

[OpenData PR #36](https://github.com/cloudQuant/opendata/pull/36) 已合入 OpenData `dev`。迁移 `0014` 将 MySQL 版本列宽由 **32 扩展为 64**，并在业务 DDL 前核验 `0013` marker 存在且没有 partial 状态；迁移 `0015` 在 MySQL 8 上为 no-op，同时保留 SQLite 原有 gate。定向隔离测试 **33 项通过**，两个目标模块覆盖率为 **87% / 100%**。验收日志保存在本机私有目录 [`2026-10-28-pending-warehouse-revision`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-warehouse-revision>)。

在一次性 MySQL 8.4 Unix socket 实例上，以合成的 `0013` 状态进行实际 upgrade 至 `0015`，再 downgrade 至 `0014` 和 `0013`；downgrade 仅在空表场景验证通过。partial 状态恢复未验证，须单独审查。未运行 `0001`–`0013` 的完整历史迁移链；MySQL TCP、生产数据库及 MySQL 9 均未测试。已有 partial marker 状态不能盲目重试，须先核实数据库状态并按运维流程处理。本次没有生产迁移或数据读取；此 PR 不构成生产升级验收，迭代204整体仍未完成。

## OpenData PR #37–#38 与未合并候选（2026-10-28）

以下记录仅覆盖 PR 的局部代码与隔离验收。它们不改变迭代204整体未完成状态，也不代表旧库已迁完或生产链路已验收。

| PR / 候选 | 已完成范围与局部证据 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #37](https://github.com/cloudQuant/opendata/pull/37) | 已合入 `dev`，修正离线 Sina fixture 成功发布用例的 worker 长租约设置。对应成功用例 **1 项通过**；timeout/cancel 用例 **2 项通过**。 | 先前 **12 个文件的组合运行有失败**，后续针对用例修正与重跑不代表该 12 文件组合整套通过；本次不记录为整套绿灯。验证使用离线 fixture，不证明真实 Sina 抓取、生产租约/并发或全量财报发布。 |
| [OpenData PR #38](https://github.com/cloudQuant/opendata/pull/38) | 已合入 `dev`，允许旧股票日线 ODS 的 `成交额` 保留 `NULL`，并与真实数值 `0` 区分；不填零、不删行。定向隔离测试 **106 项通过**，迁移 `0016` statement+branch 覆盖率 **100%**，迁移脚本 **88.12%**；覆盖率收据保存在本地私有、非仓库存档 [`coverage-final.txt`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-legacy-null/coverage-final.txt>)。一次性隔离合成 **MySQL 8.4** 验收成功，初次失败及重跑记录均保留在私有证据目录。 | MySQL 结果仅是合成 schema/数据场景，不能证明生产迁移、全量旧数据迁移、`0001`–`0016` 完整历史链、DWD 消费、REST/API、迁移锁或生产运行安全。上述覆盖率只描述聚焦测试中指定模块，不能单独证明迁移工具和数据迁移已完整验收。全量数据对账与下游 `NULL` 处理仍待完成。 |
| Fuyao one-shot 私有候选 | 离线合成用例 **34 项通过**，实现保存在本地私有候选中。 | 截至该候选记录时，未制作或验证真实上游录制；当时的执行环境未确认可用凭证。该候选本身不构成真实 Fuyao 响应、采集或数据语义验收。 |

截至本段记录时，Sina capture discovery API 与 Fuyao financial fetcher 均未合并；后续 Sina API/Store 合入状态见 OpenData PR #44。Sina discovery 继续硬关闭。上述局部测试与 MySQL 合成验证都不改变来源真实性、生产权限配置、全 A 股及逐标的全历史、PIT、调度与部署仍开放的结论。

## 2026-10-28 OpenData PR #39 与 AFI PR #91、#93

以下记录 PR 的限定交付和隔离证据；迭代204整体仍未完成。

| PR | 已合入范围与局部证据 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #39](https://github.com/cloudQuant/opendata/pull/39) | 已合入 `dev`，新增 Sina capture discovery 所需的 `0017` 查询索引迁移。定向隔离测试 **72 项通过**，statement+branch 覆盖率 **97.46%**。在隔离 MySQL 8.4 上用合成 marker 和最小环境 DDL 验证 upgrade、downgrade、re-upgrade；同时验证 MDL 1205 后重试、已有合成数据及旧索引保留。 | 隔离快照表没有种子记录；未验收 API、Store、执行计划/扫描预算（EXPLAIN）、PIT、完整历史迁移链或真实数据。Sina capture discovery API 仍硬关闭，新增索引不代表查询端点已经可用。 |
| [AFI PR #91](https://github.com/cloudQuant/ai-for-investor/pull/91) | 已合入 `dev`。因扫描器可能把代理指标当成真实报价，停用所有即时、计划和预计算扫描；旧历史数据不删除并标记为 `legacy_unverified`，管理功能保留。前端新建计划表单默认关闭 schedule；编辑时保留已知设置。后端 **8 项**、前端 **21 项与 44 项**测试通过，定向 typecheck 与 Ruff 通过。 | 相关扫描功能现处于暂停状态。OpenData 数据来源、字段单位及时间语义合同尚未验收。现存历史记录被标为未验证，不应作为真实报价或有效扫描结果使用。 |
| [AFI PR #93](https://github.com/cloudQuant/ai-for-investor/pull/93) | 已合入 `dev`。API/ORM 新建记录的 `schedule_enabled` 默认值改为 `false`；POST upsert 和 PATCH 在请求省略该字段时保留已有值；非布尔输入在写入前以 **400** 拒绝。**21 项隔离测试通过**，Ruff 通过，收据见本机私有目录 [`ruff-final.log`](</home/yun/Documents/ai-for-investor/var/reports/afi204/2026-10-28-pending-scanner-schedule/ruff-final.log>)。 | 数据库列的 server default 仍为 `true`，此次未修改；本次未批量改写既有行。请求省略该字段时保留原值，显式传入 `true` 或 `false` 仍可更新既有行。恢复任何扫描执行前必须先盘点现存启用记录，并确认启用范围。即时、计划和预计算扫描仍全部停用；此修正不恢复执行，也不改变该状态。 |

OpenData PR #39 只为后续 discovery 查询提供索引基础，没有启用 Sina discovery，也未补足 source evidence 或 PIT。AFI PR #91 暂停相关扫描，直到消费端可依赖经验证的 OpenData 数据合同。**截至本段记录时**，Fuyao one-shot fetcher 尚未合并，真实 income、balance、cashflow 响应证据仍待补齐；后续受控运行只取得有限响应，见文末更新，不能追溯改变该段当时状态或替代完整验收。以上进展均不证明全 A 股真实数据、全历史恢复、生产调度或端到端查询链路已验收。

## 2026-10-28 AFI PR #96–#97：数据治理管理员权限边界

[AFI PR #96](https://github.com/cloudQuant/ai-for-investor/pull/96) 与 [AFI PR #97](https://github.com/cloudQuant/ai-for-investor/pull/97) 已合入 `dev`，只收紧 AFI 后端的管理员身份判定，不代表 OpenData 数据接线或迭代204整体验收。

| PR | 已合入范围 | 隔离验证与边界 |
| --- | --- | --- |
| #96 | 旧数据治理七个路由统一经过 `require_data_admin_user`，兼容权限矩阵验证普通登录用户返回 **403**、匿名请求返回 **401**。 | 专项 **4 项通过**；本次 pytest 输出有 **2 条 pytest-timeout 配置警告**。该结果覆盖旧路由 guard，不是部署环境或生产数据库验收。 |
| #97 | `/auth/me`、数据管理、quant tools 和 audit 均按数据库当前 `ADMIN` 角色判权；bootstrap 拒绝同名普通用户接管管理员；禁止注册配置管理员名及其等价别名。 | 扩展隔离组合 **31 项通过**：`test_auth` 16、`test_quant_tools` 3、`test_admin_identity` 5、`test_data_governance_compat` 4，以及 `test_db.py` 3 个定向节点：创建默认管理员、重复初始化幂等、启动时禁止自动 bootstrap 管理员。使用内存 SQLite 并隔离网络；结果有 **2 条 pytest-timeout 配置警告**。这不是完整后端回归。 |

存量兼容风险：过去仅凭配置用户名、数据库中没有 `ADMIN` 角色的账号，现在不会获得管理员权限；同名普通账号也会被 bootstrap fail closed 拒绝接管。需要先人工核验账号身份，再通过受控流程授予数据库角色；本次不批量提升存量账号。MySQL collation 与并发竞态只由 fake 模拟覆盖，未在部署环境或真实 MySQL 上验收，因此不能据此宣称生产管理员授权边界已验证。

`test_db.py` 的三个用例具体为 `test_create_default_admin_when_not_exists`、`test_create_default_admin_is_idempotent` 和 `test_ensure_database_ready_never_bootstraps_admin_at_startup`；没有运行该文件的完整套件。

## 2026-10-28 当前局部能力与待验收项

此前的 OpenData 凭证检查仅覆盖当时仓库和当前可见运行环境：只找到 `.env.example` 中空白的 `FUYAO_API_KEY` 配置项，Docker 配置未检查；此记录不推断其他环境或后续运行的凭证状态。后续受控 Fuyao runs 已取得有限真实响应，具体结果见本文末尾；该记录不包含任何凭证值。

| 待验收项 | 当前证据 | 仍未验收的范围 |
| --- | --- | --- |
| [OpenData PR #45](https://github.com/cloudQuant/opendata/pull/45)：旧 `stock_daily` 只读源盘点计算器 | 已合入 `dev`（`fb12786ca86885e8378bcfbb261f64148d63beba`）；**50 项 fake-only 测试通过**，branch-inclusive 覆盖率 **99.18%**。一次性隔离测试 harness 中，合成 **MySQL 8.4** 两连接 MDL 检查通过。 | 这是一次 harness 观察，未绑定源实例元数据，不是生产 publisher/迁移链路验收；只支持该合成两连接场景。工具不执行迁移，也不证明真实源库快照/内容、真实数据对账或全历史恢复。 |
| OpenData Sina capture discovery API/Store | [OpenData PR #44](https://github.com/cloudQuant/opendata/pull/44) 已 squash 合入 `dev`（`e883aea8172228d56c50e112093d023e2c7a2111`）。当前主干四文件离线/隔离回归 **116 项通过**，包含一份已录制 Sina FZB fixture 及合成用例；此前候选回归 **232 项通过**，Store branch-inclusive 覆盖 **90.43%**、API **88.64%**。一次性合成 **MySQL 8.4.0** 上，基于 `0017` 索引完成受控查询验收：同一事务 `REPEATABLE READ`、查询计划检查及 **10,000/10,001** 逻辑结果边界通过；publication 超过 10,000 条时在 facts 查询前拒绝，返回行溢出时通过 10,001 行逻辑上限拒绝。验收收据位于 OpenData 私有目录 [`mysql-query-acceptance`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-sina-guard-v2/mysql-query-acceptance>)。 | API 仍硬关闭。回归包含录制 fixture 与合成样本，不代表实时抓取或广泛市场覆盖。MySQL 结果仅代表一次性隔离验收；10,000 行预算是逻辑结果边界，不是物理 I/O 上限，也不代表真实数据或生产 MySQL/API 行为。真实来源数据、PIT、历史完整性与生产接线仍未验收。 |
| OpenData Fuyao fetcher 与受限采集 | OpenData PR #50 已合入 `dev`，当前交付为显式 DI helper：**147 项 synthetic isolated 测试通过**，目标模块 statement+branch 覆盖率 **99%**，Ruff 通过。先前两个受控 run 得到的六种 endpoint/期间样本、manifest pin 与六实体 hash/size 核对详见本文末尾。 | helper 未注册到系统、未调度、未接入 API 或财报存储，smoke 不含 archive。source-attempt gate 仍待真实接线时验收；官方文档单位说明不代表实际数据单位已验证。PIT/修订、季度单季/累计语义、全 A 股及完整历史、生产接线均未验收。 |
| [OpenData PR #46](https://github.com/cloudQuant/opendata/pull/46)：publication outbox 本地事件 | 已 squash 合入 `dev`（`9201370133e6207480ed1f7ecc3899d79af2ba6a`）；**246 项隔离测试通过**，Store 覆盖率 **90%**、outbox 覆盖率 **98%**。隔离合成 MySQL 8.4 验收通过，包括强制 outbox INSERT 故障（errno 1644）后恢复到已提交 baseline、并发场景及 `0017→0018` 迁移。证据见本机私有目录 [`mysql-acceptance-forced-failure`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-publication-outbox/mysql-acceptance-forced-failure>)；首次部分结果与第二次完整结果均保留。 | 仅验收本地 publication outbox 事件切片，不代表控制任务 **204-A04-03** 完成。此次 MySQL 验收未覆盖 `0017` 之前的迁移链；跨服务 relay、独立 receipt、post-commit visibility seal、生产数据库/接线及生产历史可见性仍未验收；不补造历史可见时间。 |

AFI 扫描器仍按 PR #91 的 fail-closed 状态暂停；用户看到的旧结果继续标记为 `legacy_unverified`。PR #96–#97 只修正授权判定，不会启用扫描或使旧结果变成可信数据。迭代计划任务快照截至2026-10-29（Asia/Shanghai）为 **98 项（8 DEV_DONE、11 IN_PROGRESS、79 PLANNED）**；各局部 PR 与合成/隔离测试不会自动关闭父级控制任务。

全 A 股逐标的真实采集和逐证券 head/interior/tail 历史核对、PIT/修订历史、Fuyao 财报完整来源响应与语义验收、完整旧任务迁移、生产 MySQL/API/授权/自然调度与备份恢复仍未完成或未验收。Fuyao 当前只有本文记录的受限 partial 响应观察。**迭代204整体仍未完成。**

## 2026-10-28 OpenData PR #41–#43：快照、回补规划与重复键规则

以下 PR 已合入 OpenData `dev`，结果均来自合成数据和隔离测试，只支持各自限定的代码范围，不表示真实全 A 股数据、历史覆盖或生产数据质量已验收。

| PR | 已合入范围与局部证据 | 限制与未完成事项 |
| --- | --- | --- |
| [OpenData PR #41](https://github.com/cloudQuant/opendata/pull/41) | 发布前按规范化业务键拒绝同批重复记录。选定回归 **61 项合成/隔离测试通过**，目标模块覆盖率 **98%**。 | 这是一个局部重复键数据质量规则，不是完整 DQ 框架；不证明跨批/历史仓库无重复，也不验证其他字段、单位、来源真实性或数据完整性。 |
| [OpenData PR #42](https://github.com/cloudQuant/opendata/pull/42) | 增加证券参考数据快照编解码切片。**24 项合成/隔离测试通过**，语句+分支覆盖率 **93%**。 | 快照是合成样本，不是经权威来源核实的全 A 股证券目录；不证明北交所、退市证券、跨代码身份、实际上市起点或生命周期历史完整。 |
| [OpenData PR #43](https://github.com/cloudQuant/opendata/pull/43) | 增加基于显式快照输入的历史回补候选规划适配。**7 项合成/隔离测试通过**，目标模块覆盖率 **100%**。 | Planner 只生成不可执行的候选，不 dispatch、不采集、不写库；它不证明 publication 中真实存在对应缺口，也不证明数据源保留范围、逐标的真实起点或 head/interior/tail 历史完整。 |

截至本段记录时，PR #41–#43、#45 与 #46 均只关闭各自限定的代码范围；当时 Fuyao 三类真实响应证据仍缺失、recorder 未进行真实上游采集。后续受控 Fuyao run 仅形成本文末尾所述的 partial 观察，不改变未验收状态。Sina discovery API/Store 已按 OpenData PR #44 合入 `dev`，但 API 继续硬关闭。PR #46 的 publication outbox 本地事件已通过所列隔离验收；跨服务 relay、独立 receipt、post-commit visibility seal 与生产接线仍未完成，因此 204-A04-03 继续开放。以上切片均不证明生产接线、全 A 股真实覆盖、完整历史、PIT/修订历史或迭代204整体完成。

## OpenData PR #47：metadata receipt schema 与 migration 0008

[OpenData PR #47](https://github.com/cloudQuant/opendata/pull/47) 已合入 `dev`（`8f83a609855e5859c099004bc31d13193778a51b`），增加空 metadata receipt schema 与 migration `0008`。SQLite 隔离测试 **22 项通过**，两个目标模块的 branch-inclusive 覆盖率均为 **100%**。在合成 MySQL 8.4 场景中，实际执行 `0007` 与 `0008` 的 upgrade bodies；验收覆盖无历史回填、InnoDB、collation、unique、9 项选定 CHECK，以及空表和非空表 downgrade。证据保存在本机私有目录 [`2026-10-28-pending-metadata-receipt`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-metadata-receipt>)。

此 PR 只验收 schema/migration 的限定范围：未运行完整迁移链，未实现或验收 receipt writer、relay、API 或 JSON hash，也未在生产环境验收。最初两次 MySQL harness 失败记录仍保留；失败收据仅记录 stage 与 error type，根因属于事后分析推断，不能从收据独立复核。这些失败记录不改变本次限定通过范围，也不应被删除或改写为成功。PR #47 不关闭 **204-A04-03**；relay、独立 receipt 流程、visibility seal 与生产接线仍待验收，迭代204整体仍未完成。

## OpenData PR #48：受限单票 Eastmoney 试采工具

[OpenData PR #48](https://github.com/cloudQuant/opendata/pull/48) 已合入 OpenData `dev`（`09dde2dd8e751909f95307bb73f6a914dfcc2356`），增加受限单票试采工具。**59 项无网络合成测试通过**，脚本 statement+branch 综合覆盖率 **99%**，`ruff check` 与 `ruff format` 均通过。证据日志保存在本机私有目录 [`pytest-final.log`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-akshare-pilot/pytest-final.log>)。

工具的采集路径直连 Eastmoney，并将试采限制为固定股票与固定时间窗口；生产 policy 保持不变，admission 仅在本地短期有效，同一私有目录内使用同一 nonce 防重，不构成全局幂等保证。**15 秒是软截止时间**，不能视作严格的网络/进程硬超时。PR #48 的合成验证未发起真实上游请求；后续一次固定窗口试采观察另见下文。PR #48 不验证行情数值、全历史、全 A 股覆盖或生产可用性，也不改变迭代204整体未完成状态。

## OpenData PR #49：本地 receipt writer 与 #48 后续试采观察

[OpenData PR #49](https://github.com/cloudQuant/opendata/pull/49) 已 squash 合入 OpenData `dev`（`5bd4a6f61988c00080b324b1fe5879c2bd0c79de`），实现本地 receipt writer。`sqlite/pytest-v6.log` 与 `pytest-v4.log` 各记录 **54 项隔离测试通过**；目标模块 statement+branch 综合覆盖率 **98.4%**（`coverage.xml`：179/181 lines、70/72 branches）。同目录 `pytest-final.log` 记录的是 **32 项**，不作为此处 54 项或覆盖率的依据。在合成 MySQL 8.4 场景中，以合成 `0006` 状态实际执行 `0007` 与 `0008`；双连接 `REPEATABLE READ` current-read、身份冲突、rollback、选定 CHECK 与存储引擎守卫均按该隔离场景验证通过。证据保存在本机私有目录 [`2026-10-28-pending-receipt-writer`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-receipt-writer>)。

此验收不认证 producer 身份，也未独立验证 receipt contract；现有 publisher 标签范围较 writer 接受范围更宽，部分事件会被拒收。跨服务 relay、API、完整迁移链及生产环境仍未验收，因此 PR #49 不关闭 204-A04-03，也不代表生产发布链路已完成。

另一次 OpenData PR #48 的 AkShare-labelled Eastmoney 固定窗口试采记录为 network failure，状态码为 null，响应 body 未保存。现有记录无法确定请求是否实际发送，且没有重试；不能据此认定 Eastmoney 已收到请求或返回了错误，也不能证明行情数值、真实采集成功、历史完整性或全 A 股覆盖。证据保存在本机私有目录 [`2026-10-28-akshare-live-pilot-attempt`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-akshare-live-pilot-attempt>)。Fuyao 仍未验收；迭代204整体仍未完成。

## OpenData Fuyao 受控财报运行：partial 响应观察

运行 `20261028T024955Z-43949558cbc5` 的结果为 **partial**。income 年报、income 季报与 balance 年报各返回一行 `HTTP 200`，对应 entity SHA 与私有记录匹配；balance 季报的业务状态为 `transport_failed`，记录中 `http_status` 字段缺失，因此 HTTP 状态码未知；cashflow 年报与季报均为 `not_attempted`。没有重试。证据保存在 OpenData 本机私有目录 [`20261028T024955Z-43949558cbc5`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-fuyao-financial-capture/20261028T024955Z-43949558cbc5>)。

这次运行没有检查 source-attempt gate，不证明 producer 身份或 contract 已验证；有限响应也不构成 PIT、完整财报类型、修订历史、全 A 股数据、全历史或生产运行验收。生产调度、历史覆盖与端到端接线仍待验收。文档不记录凭证值。

## OpenData Fuyao 财报补采：六种组合各一份样本

后续补采 run `remaining-20261028T031741Z-b6a0666c8667` 对 balance 季报、cashflow 年报与 cashflow 季报 **3/3** 返回 `HTTP 200`、每项 1 行；新 manifest pin 旧 manifest SHA。与先前 run `20261028T024955Z-43949558cbc5` 合并观察后，income 年报/季报、balance 年报/季报、cashflow 年报/季报六种组合现各有一份真实样本，六个 entity 的 hash 与 size 核对通过。证据位于本机私有目录 [`remaining-20261028T031741Z-b6a0666c8667`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-pending-fuyao-financial-capture/remaining-20261028T031741Z-b6a0666c8667>)。

先前 run 的 balance 季报仍保留为 `transport_failed`、`http_status` 字段缺失；这次补采是另一独立 run，不能推断先前失败的最终 outcome。source-attempt gate 未检查；这批样本不验证字段单位真实性、PIT/修订历史、全 A 股或完整历史，也不证明生产调度、生产落库或 API 接线。**截至该两次采集记录时**，Fuyao fetcher 尚未合并；后续 OpenData PR #50 的当前代码状态与验收边界见下文。文档不记录凭证或响应正文。

## OpenData PR #50：Fuyao 显式 DI fetcher helper

[OpenData PR #50](https://github.com/cloudQuant/opendata/pull/50) 已合入 OpenData `dev`（`1415d8159114a618890b51aae388fd5ac78e0616`）。交付范围是显式 dependency-injection helper；没有注册到系统、接入调度、API 或财报存储。回归验证 **147 项 synthetic isolated 测试通过**，目标模块 statement+branch 覆盖率 **99%**，Ruff 通过。日志见 [`2026-10-28-fuyao-fetcher-regression`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-fetcher-regression>)。

一项离线 smoke 通过：使用 `MockTransport` 提供六个真实捕获 entity，并以 synthetic、未验证的单位声明和临时 SQLite gate 验证受限路径；该 smoke 不包含 archive。证据见 [`2026-10-28-fuyao-six-fixture-smoke`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-six-fixture-smoke>)。此前官方 Fuyao 文档关于单位（金额原币元、EPS 元/股）及时间说明的核对证据保存在 [`2026-10-28-fuyao-public-contract`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-public-contract>)；这只记录文档口径，不验证捕获数据的单位真实性。日志和证据均不在本文复述原始响应内容。

source-attempt gate 尚未在真实接线下验收；季度数据为单季还是累计、PIT/修订语义、全 A 股与完整历史及生产运行仍未验收。PR #50 合并并不等于 fetcher 已注册、运行或验收完成；文档不包含凭证或原始数据。

## OpenData PR #51–#52：参数摘要与财报期间覆盖评估器

以下 PR 已合入 OpenData `dev`，只记录局部代码和隔离证据，不表示 Fuyao 生产采集或完整历史已验收。

| PR | 已合入范围与局部验证 | 限制与兼容性边界 |
| --- | --- | --- |
| [OpenData PR #51](https://github.com/cloudQuant/opendata/pull/51) | 已合入（`cea574596fed991a591847312edcd98fb848c3bb`），实现冻结参数的 v1 summary，并抽取 legacy helper。**173 项 synthetic 测试通过**；三个目标范围覆盖率记录为 **93% / 99% / 96%**。首次 `umask` 相关失败记录保留。证据见 [`2026-10-28-fuyao-request-summary`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-request-summary>)。 | 客户端提供的参数声明不是上游请求参数或响应内容的证明。`RawEvidenceError.__module__` 已变更；异常的 pickle 兼容性随之改变，新异常 pickle 与旧版本也不兼容。调用方或跨版本持久化消费者仍需检查该兼容边界。 |
| [OpenData PR #52](https://github.com/cloudQuant/opendata/pull/52) | 已合入（`78bb6846fa934c5bd6ab33479b5f12e27a38f9aa`），增加纯财报期间覆盖评估器；最终 **38 项隔离测试通过**，目标模块覆盖率 **91%**；首次测试 **1 项失败**的记录保留。它使用显式期间槽位和证据：`observed` 只表示存在对应证据；`missing` 只有在所有适用证据门禁同时通过时才可判定，包括期间应期、到期后扫描完成、inventory 一致、lifecycle 与精确 obligation/due 关联、扫描 scope/crosswalk/cursor 与失败/隔离项核对、source-history 一致，以及不存在冲突、未来或不可用版本证据。证据见 [`2026-10-28-financial-period-coverage`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-financial-period-coverage>)。 | 评估器不采集或自行验证上游来源，也不证明证据覆盖完整或来源保留边界。该切片不建立 PIT/修订历史，也没有真实全 A 股接线；生产采集、全市场范围与完整历史仍未验收。 |

PR #51–#52 的局部通过不改变 PR #50 的运行边界：Fuyao helper 尚未注册到系统、调度、API 或财报存储；source-attempt gate 仍需在真实接线时验收。季度单季/累计语义、单位真实性、PIT/修订历史、全 A 股与生产运行仍开放。本文不包含 API key 或原始响应数据。

## OpenData PR #53：Fuyao observation capture prepare bridge

[OpenData PR #53](https://github.com/cloudQuant/opendata/pull/53) 已 squash 合入 `dev`（`c99268b73006017f6dbe462f0ca7b6bd64725f1f`）。它把显式提供的 Fuyao fetch result 接到 raw-evidence 写入和现有 store prepare 流程，产出供调用方事务使用的 prepared capture；最终 **32 项 synthetic 隔离测试通过**，目标分支覆盖率 **100%**。源码 `opendata/pipeline/fuyao_observation_capture.py` SHA-256 为 `9d1a1d6e4504e0b22df97517ca56c766e986e9cca9129d515077c05a0a1c2e5f`；测试 `tests/test_fuyao_observation_capture.py` SHA-256 为 `3b2567069ed701a86e4d30d759539f00c8d145d866eab6eb276ae62551fd1693`。私有失败与最终验证收据（含最终 pytest/coverage 日志及较早失败记录）保存在 [`2026-10-28-fuyao-capture-bridge`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-capture-bridge>)。

此 bridge 不提交数据库事务、不接调度，也不验证真实来源血缘；来源、attempt/reservation、profile 与映射等上下文仍由调用方声明。文件系统 raw evidence 与数据库事务不原子，prepare 后续失败可能留下 orphan；当前 manifest 不能单独恢复完整业务上下文。重复调用没有跨调用幂等保证，可能产生新的 manifest/capture ID，但不能据此声称每次调用必定生成不同 manifest；同一 prepared 对象在调用方事务内的重用遵循现有 store 语义。结果不构成 PIT、财报修订历史、全 A 股覆盖或完整历史验收。

## OpenData PR #54：SZSE 退市种子声明结构校验（2026-10-28）

[OpenData PR #54](https://github.com/cloudQuant/opendata/pull/54) 已 squash 合入 `dev`（`ac18990af71f804412b54f2cd8fd1f5209a35f14`）。`opendata/data/szse_delisted_seed.py` 与 `tests/test_szse_delisted_seed.py` 的最终 SHA-256 分别为 `5f5bfa1ff1e04d23cebe192ec9f92e6d2e46ce1a69320097a25cf4ad2b4b1c4b`、`dc2ff4c7c8c54b2d6361eb96b237418800ee34e79107eb33dcfe1e593abc01b7`。**45 项 synthetic 测试通过**，目标模块 branch-inclusive 覆盖率 **99.4%**。五轮运行日志（包括失败与最终记录）保存在 OpenData 本机私有目录 [`2026-10-28-szse-delisted-seed`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-szse-delisted-seed>)；最终日志为 [`final-pytest.log`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-szse-delisted-seed/final-pytest.log>)，首轮失败记录为 [`first-run-pytest.log`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-szse-delisted-seed/first-run-pytest.log>)。

该代码只校验调用方提供的声明结构及其内部引用一致性；固定 profile 只核对输入的来源标识与摘要声明。不打开或读取 PDF，不验证其中日期文本，也不独立验证声称的来源独立性或真实性。未接入来源 registry / instrument registry，也未生成 canonical `instrument_id`。此次 synthetic 验证不评估全 A 股证券全集、北交所真实退市名单、逐证券历史起点或完整历史。该 PR 只关闭声明结构校验的局部代码范围，不改变迭代204整体仍未完成的状态。

## OpenData PR #55：Fuyao transport attempt trace（2026-10-28）

[OpenData PR #55](https://github.com/cloudQuant/opendata/pull/55) 已 squash 合入 `dev`（`bd9a7ebd482e53548f0fbc7c78df1a376497bcc3`），增加 HTTP client 成功路径的 attempt trace。最终 **152 项 synthetic 隔离测试通过**，输出有 **2 条 `PytestUnknownMarkWarning`**；`http_client.py` statement+branch 综合覆盖率为 **97%**。首轮 **60 项通过**，但 coverage 为 **62%**、未达到 90% 门槛；该轮记录保留在私有证据中。`opendata/data/providers/ths/transport/http_client.py` 与 `tests/test_fuyao_transport.py` 的 SHA-256 分别为 `e55bf322a8e2c68d03f10bd431f75d732727b496b311db168533d5dc2b015c81` 和 `11a5bf0cfe9964c8d9ac8a21500d9a5dbd8b8c4570cd95633dec1b2548b48452`。验证收据位于 OpenData 本机私有目录 [`2026-10-28-fuyao-transport-attempt-trace`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-transport-attempt-trace>)。

attempt trace 只随最终成功响应暴露；如果中间尝试失败后请求最终成功，响应可带有这些尝试的 trace。终止错误没有 trace 载体，因此不能据此推断所有请求尝试都可由调用方读取。记录本身不能证明请求已被上游接收，也不能证明来源授权有效。目前该功能尚未接入 Fuyao fetcher、capture bridge 或持久化审计流程。故 204-A04-03 及生产审计接线状态仍为 **OPEN**；此 PR 不证明真实采集、持久可追溯性、数据授权、全 A 股范围或完整历史已验收，迭代204整体仍未完成。

## OpenData PR #56：财报归档读取器分页与并发边界（2026-10-28）

[OpenData PR #56](https://github.com/cloudQuant/opendata/pull/56) 已 squash 合入 `dev`（`ec256076bb76e4514253a7796b199234caacce7c`）。最终 **33 项 synthetic 隔离测试通过**，statement+branch 综合覆盖率 **98.49%**。早期一轮 **16 项通过**，但覆盖率 **89.45%**，低于门槛；该轮未达标结果保留，不作为验收依据。源码与测试 SHA-256 分别为 `a034a13e0b3dfe57c6aafcb1abcdf0d8926b147ec19c200e0d82bbca55fcf397`、`6815c9c570a12b7eb0edb843ced49d8fa0ad87802acf50d0ae9cf3f09d51054f`。日志及隔离收据见 OpenData 本机私有目录 [`2026-10-28-financial-archive-reader`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-financial-archive-reader/>)。

一次性合成 **MySQL 8.4** 场景仅应用空归档上的 `migration_0001`，随后以两个 `REPEATABLE READ` 连接读取 **6 行、每页 2 行**。在事务快照期间并发插入/更新未改变该快照的分页结果；事务结束后，旧游标被拒绝。另验证小数、`NULL` 和 UTC datetime 微秒保真。已通过 pidfd 确认 `mysqld` 与 SQL worker 退出。验收记录同时保留组件加载信息、空 root 密码与自签 CA 提示。EXPLAIN 摘要对两个查询记录 `using_filesort=false`，但该值可能来自 runner 在字段缺失时采用的默认值，因此不能确认实际执行计划是否使用 filesort；不同键范围中的 2,500 条 filler 数据也不证明性能。

该读取器尚未接入 REST。并发一致性依赖调用方在事务开始前设置 `REPEATABLE READ`；本次合成结果不验证 PIT/修订语义、全 A 股范围、生产数据或生产性能，也不代表财报完整历史和迭代204整体已验收。

## OpenData PR #57：Fuyao fetch result 的本地成功尝试轨迹（2026-10-28）

[OpenData PR #57](https://github.com/cloudQuant/opendata/pull/57) 已 squash 合入 `dev`（`f7800938e57a2d6a52f6bbe0252235dd09e87f0d`）。`FinancialObservationFetchResult` 现在可携带 Fuyao transport 返回的本地 attempt trace；旧调用方未传该字段时仍得到空 tuple。`transport_request_id`、`attempt_id`、HTTP status 与 response envelope 中的 `source_request_id` 分字段保存，并只做本地格式和一致性校验：它们不构成上游回执，也不证明来源收到或处理了请求。源码 `opendata/data/providers/ths/models/financial_observation_fetcher.py` SHA-256 为 `a68578f9a375c16738815de6972c767d3fedad10514ef480df978e653656f181`；测试 `tests/test_ths_financial_observation_fetcher.py` SHA-256 为 `774412ff26df3cfa8bd7deff656415c9b4621bb2556d2aec22bf70134c4d8551`。

最终定向验证为 **152 项 synthetic 隔离测试通过**，branch-inclusive 覆盖率 **97%**；首次运行 **148 项通过、4 项失败**，失败集中在 fetch-result 元数据拒绝用例的校验顺序，首轮日志予以保留。既有 capture bridge 回归另有 **32 项通过**，但该测试没有使用或验证新增的 attempt trace，因此不能据此声称 trace 已与 archive/prepare 流程联调。证据保存在 OpenData 本机私有目录 [`2026-10-28-fuyao-fetcher-attempt-trace`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-fetcher-attempt-trace>)。对最终源码、测试和收据的独立检查确认：终态 transport 错误不会返回带轨迹的 fetch result，旧构造方式保留空 tuple，成功结果仅承载本地记录；不把这一切片解释为持久审计。

attempt trace 只有成功 fetch result 可携带；终止网络失败或响应后校验失败不会返回该结果，故无法从调用方结果读取其最终尝试轨迹。空 tuple 也不证明请求未发送。此切片没有新增持久化审计或来源授权核验，不能证明失败请求最终状态、全 A 股采集、完整历史或 PIT/修订历史；204-A04-03 与生产接线仍保持开放，迭代204整体仍未完成。

## OpenData PR #58：capture bridge 本地 trace 一致性校验（2026-10-28）

[OpenData PR #58](https://github.com/cloudQuant/opendata/pull/58) 已 squash 合入 `dev`（`f6638cf33fb0f5c1d01c84a631fbc41c76ea073c`）。当 fetch result 带有非空 attempt trace 时，capture bridge 会在写入文件前将 trace 字段与调用方声明的本地字段比对；旧调用方提供空 trace 时仍兼容。缺失的 source ID 保持 unavailable，不据此补造标识。源码、单元测试和集成测试 SHA-256 分别为 `97a51bfa8c9ac941219c854c5748c20fa6975b0ec40f0261d25191b7a5d07720`、`60b161e2590882aa04ba50bc8b0306ec2bc86879177726c7bfe4cea0bdf43f2a`、`f9891c3e9aaf921327f7e80248e8559530f63f212154fc4c3651d54ee8d35670`。合成隔离测试 **47 项通过**，目标模块 branch-inclusive 覆盖率 **98%**。另有一项本地集成测试使用临时 SQLite source-attempt gate、`MockTransport` 和 fetcher→bridge 路径；r1/r2 因 `source_attempts=4` 超过 gate 上限 `3` 失败，r3/r4 对同一测试项重跑通过。验证收据保存在 OpenData 本机私有目录 [`2026-10-28-fuyao-bridge-local-trace`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-bridge-local-trace>)。

trace 与声明字段的匹配仅是本地一致性检查，不独立认证来源、上游接收或处理，也不将 trace 持久化为审计记录。该合入不代表生产数据库落库或调度完成，也不证明全 A 股覆盖、财报完整历史、PIT/修订历史或数据完整性；迭代204整体仍未完成。

## OpenData PR #59：receipt Unicode opaque label 合同修复（2026-10-28）

[OpenData PR #59](https://github.com/cloudQuant/opendata/pull/59) 已 squash 合入 `dev`（`68d0bca401af2905866d2f7bee2f99b7b55150fc`），修复 producer 与接收端对 Unicode opaque label 的兼容。原始 event bytes、对应 hash 与 producer 身份认证状态均保持不变；该修复不认证 producer。SQLite 的字符长度约束保持不变；MySQL migration `0009` 改用 `CHAR_LENGTH`。降级前会对超出目标 byte 限制的标签 fail closed，因此降级需要先协调停写及兼容性检查。

最终 **89 项离线合成测试通过**，包含 SQLite fixtures 与 MySQL DDL/stub；该数字不代表 89 项均在 SQLite 上实测。writer、schema 与 migration 的 branch-inclusive 覆盖率分别为 **98% / 100% / 90%**。另在隔离合成 **MySQL 8.4** 上从 synthetic `0007` marker 开始执行 `0008 → 0009 → 0008`，覆盖 ASCII hash、128/64 Unicode label 与 replay、downgrade preflight，以及确定性并发冲突（errno `3819`）后数据、约束和 revision 保持成功。验证收据位于 OpenData 本机私有目录 [`2026-10-28-receipt-unicode-contract`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-receipt-unicode-contract>)。早期失败报告的根因分别是 harness SQL 空白匹配错误，以及 hook 实际未注入后的误判；原失败记录保留，不作为最终失败或成功证据。

该验收从 synthetic marker 开始，不覆盖完整迁移链或生产数据库，也不独立认证 producer、上游来源或 receipt 内容。上线顺序应先完成目标数据库的迁移与兼容性检查，再启用依赖新 Unicode opaque label 合同的 writer；降级前须按前述限制协调停写。跨服务 relay、真实生产接线、全 A 股覆盖、完整历史及 PIT/修订历史仍未验收；迭代204整体仍未完成。

## OpenData PR #61：财报归档 REST 读取切片（2026-10-28）

[OpenData PR #61](https://github.com/cloudQuant/opendata/pull/61) 已合入 OpenData `dev`（squash commit `e1867004192432c528c826ba5ccf1e6a4ad8c29c`），新增有界的 `/api/v2/data/financial-statements/archive` 读取端点，使用单独配置的财报归档连接读取指定来源、证券、报表类型、周期与日期范围；单次返回记录数与响应体均有预算限制，并保留 `report_period`、披露日期和观察时间的不同语义。端点把完整性标记为未知、PIT 重建标记为不可用，不推断数据完整或可用于历史时点回放。

定向离线 fake-engine/ASGI 测试 **45 项通过**，目标模块 statement+branch 综合覆盖率 **98%**；另有 **2 项隔离 OpenAPI 测试通过**。临时隔离 **MySQL 8.4** 合成数据与只读账户验收通过，验证了该切片的读取与响应边界。该 MySQL harness 用测试认证依赖覆盖，并把应用配置的 TCP 连接映射到私有 Unix socket；因此没有验证真实 JWT/API key 认证，也没有验证生产 TCP 路径、真实财报数据、PIT、全历史或部署。结果不代表真实来源授权、数据语义、全市场覆盖或生产服务可用。

现有 capture-candidates 路由保持硬关闭，访问返回 **404**。其 OpenAPI 声明将参数标为可选，但若将路由启用，handler 仍要求这些参数；该契约不一致仍待单独修正和验收。本 PR 不启用该旧路由。迭代204整体仍未完成。

## 2026-10-28 AFI PR #116 与 OpenData PR #62–#63 局部进展

以下记录只覆盖三个 PR 明确交付的代码切片，不改变迭代控制任务数量或完成状态。迭代204整体仍未完成。

| PR | 已合入的限定范围 | 验收边界与未完成事项 |
| --- | --- | --- |
| [AFI PR #116](https://github.com/cloudQuant/ai-for-investor/pull/116) | 已 squash 合入 `dev`（`36628e5f05671f6c135b1487584582f14477f710`）。新增默认关闭的股票分析 OpenData 路径，消费 OpenData raw-only 数据；定向 **60 项 MockTransport 与旧 collector 测试**。 | 该路径采用降级决策；数据仍是非 PIT，指标映射也未验收。真实 OpenData 端点尚未验收，因此不表示已切换线上消费、已具备生产可用性或完成股票分析迁移。 |
| [OpenData PR #62](https://github.com/cloudQuant/opendata/pull/62) | 已 squash 合入 `dev`（`8419820ce04bac0214058e39cbb8449537495a6e`），新增 SQLite 合成测试与说明，验证既有的数据库失败回滚及重试流程；共 **4 项 synthetic SQLite** 场景。 | PR 未增加运行时代码。验证范围限于合成 SQLite 场景；不证明真实 job 接线、真实数据库方言行为或生产运行与恢复已验收。 |
| [OpenData PR #63](https://github.com/cloudQuant/opendata/pull/63) | 已 squash 合入 `dev`（`af383d52b11f28d23c9fc87ad304923cfc3e2f42`），增加 codec/sidecar 的局部支持；定向 **144 项 synthetic 测试**，branch-inclusive 覆盖率记录为 **91.59% / 98.89%**。 | codec/sidecar 尚未接入实际财报 job，也没有 production 验收；sidecar 改动带有类兼容风险，需在后续接线与调用方审查中继续核对。该合入不证明生产采集已启用。 |

这些 PR 不改变全 A 股及退市证券全集、完整历史 head/interior/tail、财报修订/PIT、来源授权核验、生产调度与自然周期验收等开放范围，也不修改控制任务计数。

## 2026-10-28 OpenData PR #64–#66 局部进展

以下仅记录三个已合入切片的代码范围和隔离验证证据；不改变迭代控制任务数量或完成状态，迭代204整体仍未完成。

| PR | 已合入的限定范围 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #64](https://github.com/cloudQuant/opendata/pull/64) | 已 squash 合入 `dev`（`1c086ce67e099dae058375b565a75bf02ea4b046`），增加 Fuyao 财报 bundle 配置加载和结构校验。最终 **46 项 synthetic 测试通过**，`fuyao_financial_bundle.py` branch-inclusive 覆盖率 **92.94%**。 | bundle 中的证券范围、registry 与单位 profile 均依赖调用方/操作员声明；配置 pin 与映射摘要不证明来源授权、真实计量单位或生命周期声明。该切片不创建 grant、不发真实请求、不访问生产数据或数据库；真实 Fuyao 财报任务、来源授权与单位语义仍待验收。离线证据见 OpenData 本机私有目录 [`2026-10-28-fuyao-financial-bundle`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-financial-bundle>)。 |
| [OpenData PR #65](https://github.com/cloudQuant/opendata/pull/65) | 已 squash 合入 `dev`（`049b0e26b10dc000e134eca82db37e9a3a9d54d4`），为 `RunService` 增加在 SQL 提交事务开启前校验/解码财报 payload 的固定 decoder seam。隔离套件 **151 项 synthetic 测试通过**，`run_service.py` statement+branch 综合覆盖率 **91.37%**。 | decoder seam 不等于真实财报 job 已注册或运行；raw 文件与数据库事务仍非原子，且没有持久化 intent、跨进程恢复队列或崩溃自动对账。本次没有生产数据库、真实供应商响应或生产运行验收。 |
| [OpenData PR #66](https://github.com/cloudQuant/opendata/pull/66) | 已 squash 合入 `dev`（`cf561b8ed025da385ab428a28173654642c00c94`），新增 Eastmoney-shaped 沪深日线 source-native 字段解析；raw evidence 校验限定为本地 body/manifest hash 与请求摘要的一致性，原文本 token 按字段保留。**66 项 synthetic 测试通过**，模块 branch-inclusive 覆盖率 **99.08%**。 | parser 尚未接入真实 `stock_daily` job 或采集执行路径。合约尚未通过真实 Eastmoney 响应验收；caller-declared 元数据不认证上游，测试不证明真实来源行为或授权。价格复权含义、数值单位/NULL 语义及历史保留边界仍未知；未验收上市至今及内部缺口覆盖，也未接入生产数据库、REST 或调度。 |

上述切片均不改变控制任务计数，也不证明全 A 股及退市证券全集、全历史 head/interior/tail 覆盖、财报 PIT/修订语义、来源授权、生产调度或自然周期已验收。

## OpenData PR #67–#69：恢复设计、财报回放与单标的任务切片

以下记录三个已合入 OpenData `dev` 的限定范围，不增加迭代控制任务的完成数，也不代表迭代204整体完成。

| PR | 已合入的限定范围 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #67](https://github.com/cloudQuant/opendata/pull/67) | 仅交付历史采集崩溃恢复设计。 | 这是设计交付，不包含已验收的恢复执行、生产装配或可运行恢复 worker；真实恢复流程仍未验收。 |
| [OpenData PR #68](https://github.com/cloudQuant/opendata/pull/68) | 对依据捕获响应结构改写的固定 synthetic Fuyao 财报样本进行 **81 项隔离回放**。收据保存在 OpenData 本机私有目录 [`2026-10-29-fuyao-sanitized-replay`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-fuyao-sanitized-replay>)。 | 回放只说明这些固定样本在隔离环境中的解析/合同路径；不认证上游来源，不证明响应覆盖完整、来源保留边界、全 A 股范围或全历史完整性。 |
| [OpenData PR #69](https://github.com/cloudQuant/opendata/pull/69) | 增加默认禁用的单标的 Fuyao 财报 reviewed-job 切片；**#69 专用隔离套件 238 项 synthetic 测试通过**，三个目标模块 branch-inclusive 覆盖率分别为 **95.00% / 91.23% / 94.22%**，定向 Ruff、format、Bandit、Gitleaks 与 mypy 检查通过。收据见 OpenData 本机私有目录 [`2026-10-28-fuyao-reviewed-job-r6-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-28-fuyao-reviewed-job-r6-final>)。 | 测试中的成功采集路径使用进程内 handler 替换与 `MockTransport`，未证明真实子进程成功请求 Fuyao。任务尚未生产装配或启用；生产数据库、调度、崩溃恢复、真实来源数据、全 A 股及全历史均未验收。目标静态检查不等于 canonical A2；canonical A2 与整仓 `make gate` 均未执行，canonical A2 所需历史 evidence 仍缺失。 |

以上合并不改变控制任务完成统计。真实成功子进程、生产任务装配、恢复执行与全 A 股/全历史验收仍开放；不得把合成回放或单标的离线测试解释为这些工作已完成。

## OpenData PR #70–#71：日线补数预算与历史缺口对账候选

以下仅记录规划与对账代码切片的定向隔离验收，不改变迭代任务完成统计；迭代204整体仍未完成。

| PR | 已合入的限定范围与测试结果 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #70](https://github.com/cloudQuant/opendata/pull/70) | 为日线历史补数规划增加资源预算约束；预算耗尽不会掩盖非法证券代码及北交所路由 blocker。定向 **27 项通过**，`stock_daily_backfill_plan.py` 语句与分支合计覆盖率 **94.58%**；报告的定向 Ruff lint/format、mypy、Bandit 与 Gitleaks 检查通过。证据见 OpenData 本机私有目录 [`2026-10-29-stock-daily-plan-budget-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-stock-daily-plan-budget-final>)。 | 规划结果仍是依据输入证据生成的候选请求，不执行派发、抓取或落库；预算测试不证明来源权限、真实数据覆盖或任何证券的历史完整性。完整 A2 未运行，不能据此宣称整仓或生产验收通过。 |
| [OpenData PR #71](https://github.com/cloudQuant/opendata/pull/71) | 增加离线、review-only 的日线历史缺口诊断与候选对账，按精确证券/来源及调用方提供的日历、publication、预期观测、生命周期、保留边界和 alias-pinned 计划证据判断可报告的缺口。定向 **92 项通过**，`stock_daily_reconcile.py` 语句与分支合计覆盖率 **96.61%**。Ruff lint/format、Bandit、Gitleaks 与目标文件限定 `--follow-imports=silent` 的 mypy 检查通过。证据见 OpenData 本机私有目录 [`2026-10-29-stock-daily-reconcile-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-stock-daily-reconcile-final>)。 | 只输出供人工复核的诊断和候选，不执行补数；未连接真实来源、数据库、API、调度器或生产规模数据，候选也不证明证券或日期区间已经完整。模块固定将 `all_a_universe_complete` 与 `universe_census_attested` 置为 false。目标文件限定 mypy 通过不代表导入模块全仓通过；较宽的检查因四个其他并行修改模块中的 11 个错误退出非零。完整 canonical A2 未运行，所需 immutable 历史 classification evidence 缺失。 |

这两项不证明全 A 股证券分母、北交所/退市生命周期、真实来源保留边界或逐证券 head/interior/tail 已核实；不增加任务完成数，也不构成生产数据采集或全历史恢复验收。

## OpenData PR #72–#74：来源门禁与 Fuyao 预检/合成联调

以下记录三项限定范围及其隔离证据，不改变控制任务完成统计。完整 A2 未运行，迭代204整体仍未完成。

| PR | 已合入的限定范围与测试结果 | 验收边界与未完成事项 |
| --- | --- | --- |
| [OpenData PR #72](https://github.com/cloudQuant/opendata/pull/72) | 来源尝试门禁 v2 与迁移切片的定向隔离套件 **153 项通过**；`source_attempt_gate.py` 语句+分支覆盖率 **90.7393%**，迁移包覆盖率 **86.4865%**。定向 Ruff、mypy、Bandit 与 Gitleaks 检查通过。验收收据见 OpenData 本机私有目录 [`2026-10-29-source-gate-v2-r7-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-source-gate-v2-r7-final>)。 | 测试有 9 条 Alembic deprecation warning 和一条迁移脚本未导入的 coverage warning。隔离验证未访问真实数据库或网络；SQLite 路径竞态、门禁数据库与 warehouse 共置时的检测，以及真实数据库迁移行为仍未验证。完整 A2 未运行。 |
| [OpenData PR #73](https://github.com/cloudQuant/opendata/pull/73) | 增加默认禁用的 Fuyao 单标的手工组装预检。专用隔离套件 **24 项通过**，目标模块语句与分支覆盖率 **100%**；定向静态检查通过。证据见 OpenData 本机私有目录 [`2026-10-29-fuyao-manual-composition-r4-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-fuyao-manual-composition-r4-final>)。 | **在 PR #73 当时的实现中**，预检报告将 `gate_grant_status` 标为 `not_checked`：该版本不查询/验证持久化 source-attempt gate grant 状态，仅检查传入 grant ID/revision 的结构或格式。它会另行读取并检查本地 operator policy 的声明、条件及有效期；这些检查不等于验证供应商授权，也不代表持久化 gate grant 已获授权。预检不 reserve attempt、不派发/执行，不启动 worker 或 scheduler，也不发 Fuyao 请求。真实授权、来源响应和生产装配未验收；完整 A2 未运行，较宽依赖检查另报告 3 个错误。 |
| [OpenData PR #74](https://github.com/cloudQuant/opendata/pull/74) | 增加显式 opt-in 的跨仓 synthetic wire 合同用例，**1 项通过**，只覆盖一条 `income/annual` synthetic 观察路径；其余五个 statement/cadence scope 为空。隔离证据见 OpenData 本机私有目录 [`fuyao-wire-isolated-r5-2026-10-28`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-wire-isolated-r5-2026-10-28>)。 | 测试将 MySQL archive reader 替换为临时 SQLite fixture，将 principal 替换为 synthetic principal，并将 process executor 替换为进程内 synthetic child；HTTP 使用 MockTransport。因此不证明真实子进程、真实 MySQL、真实 Fuyao 数据或来源授权，也不证明单位、PIT/修订历史、全 A 股或全历史完整性。该单节点结果不等于仓库联合回归或生产验收。 |

以上 PR 不增加任务完成数。完整 canonical A2 未运行；来源门禁的 SQLite 路径竞态与共置检测、Fuyao grant 验证、真实子进程/供应商请求、生产装配，以及全 A 股与逐证券全历史验收仍保持开放。

## 2026-10-29 OpenData PR #75：股票 publication selector

[OpenData PR #75](https://github.com/cloudQuant/opendata/pull/75) 已合入 `dev`，增加内部股票 publication 的 market/symbol selector 与对应身份和迁移处理。专用隔离套件 **326 项通过**；在一次性 **MySQL 8.4** 实例上，以合成 `0018` 状态执行至 `0019`，并注入部分 DDL 后的客户端中断场景。详细收据见 OpenData 本机私有证据 [`2026-10-29-stock-selector-v2-final-326-mysql/EVIDENCE.md`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-stock-selector-v2-final-326-mysql/EVIDENCE.md>)。

selector 能力保持 **hard off**；本 PR 不启用对外 REST selector 参数或股票筛选接口，不能据此认为 ai-for-investor 可通过 REST 按 market/symbol 查询。测试与合成迁移不等于完整 canonical A2、生产迁移或生产规模查询性能验收。旧 publication 中 selector 为空的记录不会因同键重发自动补齐；历史记录处置/重建方案仍待审查。未使用真实股票数据验证证券身份、来源语义或覆盖范围。上述 A2、生产性能与迁移、旧 NULL 记录处理及真实数据验收均尚未通过；本 PR 只关闭其明确的隔离代码范围，不改变迭代204整体未完成状态。


## 2026-10-29 OpenData PR #76：只读 grant 检查

[OpenData PR #76](https://github.com/cloudQuant/opendata/pull/76) 已合入 `dev`，增加只读的 source-attempt grant 检查接口。专用 synthetic SQLite 隔离套件 **185 项通过**；来源门禁模块语句与分支合计覆盖率 **90.1567%**，迁移包覆盖率 **86.4865%**。本次结果包含 **9 条 Alembic 弃用警告**；完整 canonical A2 未运行。验收证据见 OpenData 本机私有目录 [`2026-10-29-grant-inspection-final/README.md`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-grant-inspection-final/README.md>)。

在 PR #76 合入时，该检查仅提供 advisory 信息，不构成来源授权，也不创建、批准或执行 grant；当时尚未接入 Fuyao 手工预检，也未查询或验证真实生产 grant 状态，亦未执行 Fuyao 请求或数据采集。测试查询的是测试自有临时 SQLite 中的合成 grant 记录，不能据此推断生产库或共置数据库上的行为。实现仍存在同一 OS 用户可在检查期间替换目标文件的 TOCTOU 风险；SQLite/WAL 检查也可能产生文件系统副作用。完整 A2、生产授权及部署验收仍未完成，迭代204整体保持开放。后续 Fuyao 手工预检接线的当前范围见 OpenData PR #77。

## 2026-10-29 OpenData PR #77：Fuyao 手工预检的本地 grant advisory 接线

[OpenData PR #77](https://github.com/cloudQuant/opendata/pull/77) 已合入 `dev`，增加了显式 opt-in 的本地 grant advisory 检查，并将其接入 Fuyao 手工预检。默认关闭此检查；默认结果仍为 `gate_grant_status=not_checked`，并且不执行 gate 检查或 gate I/O，`dispatch=false`。启用时的检查只提供 advisory 状态，不代替供应商授权核验，也不创建或批准 grant。

专用 stub 隔离套件 **33 项通过**；`fuyao_manual_composition.py` 的 statement+branch 组合覆盖率为 **97.18%**，不是 pipeline 整体覆盖率。**在 PR #77 当时**，这些测试没有联合验证真实 SourceAttemptGate 与预检，也没有发出真实 Fuyao 请求或验证全量数据；完整 canonical A2 未运行。证据见 OpenData 本机私有目录 [`2026-10-29-fuyao-manual-inspection-r5-final`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-fuyao-manual-inspection-r5-final/README.md>)。真实生产 grant/数据库行为、真实来源请求、证券全集及完整历史数据仍保持开放，迭代204整体未完成。

## 2026-10-29 OpenData PR #78：Fuyao 手工预检与来源门禁联合切片

[OpenData PR #78](https://github.com/cloudQuant/opendata/pull/78) 已合入 `dev`。在合成 SQLite 与 MockTransport 的隔离环境中，真实 `SourceAttemptGate` 与 Fuyao preflight 完成 **7 项联合测试**，包括 grant 匹配后被撤销时，实际传输 gate 拒绝请求。测试手建 v2 schema，并使用 stub policy/bundle；没有访问真实网络、生产 grant 或真实数据。

本切片未验证部署，也未执行完整迁移链；完整 canonical A2 未运行。证据见 OpenData 本机私有目录 [`2026-10-29-fuyao-gate-integration-v1-final/acceptance-summary.json`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-fuyao-gate-integration-v1-final/acceptance-summary.json>)。真实生产 grant/数据库、部署与完整迁移、Fuyao 来源数据、证券全集及完整历史仍未验收，迭代204整体未完成。

## 2026-10-29 OpenData PR #79：股票日线版本化归一化证据

[OpenData PR #79](https://github.com/cloudQuant/opendata/pull/79) 已合入 `dev`，为股票日线归一化增加版本化 evidence，并由定向 RunService 测试验证其写入内部 publication provenance。专用隔离套件 **112 项通过**；目标模块 statement+branch 覆盖率为 **553/608（90.95%）**。证据见 OpenData 本机私有目录 [`2026-10-29-stock-normalization-evidence-final/README.md`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-stock-normalization-evidence-final/README.md>)。

本次隔离运行使用的 pytest、pytest-asyncio 与 pytest-cov 版本不同于 `requirements.txt` 固定版本；完整 canonical A2 未运行。内部 quality 摘要保持 **warning**，股票 market REST selector 继续关闭。独立的 vertical-flow 测试确认公开 REST 返回 **404**，且未调用 `create_snapshot` 或 `read_page`；这不代表 REST 股票筛选已开放。

测试使用 synthetic fixtures，不证明真实上游来源、来源授权与留存/分发权利、数据质量或逐证券历史完整性。真实来源、rights、全 A 股范围及 head/interior/tail 历史覆盖仍为 **UNKNOWN/未验收**；本 PR 只关闭其限定的内部归一化证据代码范围，迭代204整体仍未完成。

## 2026-10-29 OpenData PR #80：一次性 claim/service/worker primitive

[OpenData PR #80](https://github.com/cloudQuant/opendata/pull/80) 已 squash 合入 `dev`，提交为 `5bf309dbca29a039307972bb93858d687b568a85`。交付范围包括内部一次性 claim、service/worker primitive 与迁移 `0020`。专用隔离套件 **325 项通过**；该隔离运行的 pytest、pytest-asyncio、pytest-cov 均与项目固定版本不同。coverage ledger、service、worker 的 statement+branch 覆盖率分别为 **91.27% / 90.49% / 91.27%**。迁移另在隔离 MySQL 8.4 场景获得部分验证；该结果不代表完整迁移链或生产数据库验收。

定向 Ruff、Bandit 与 Gitleaks 检查通过；mypy 仍报告 **3 项基线错误**，完整 canonical A2 未运行。该 primitive 尚未接入生产 CLI，没有发起 Fuyao 请求或真实采集。全市场证券范围、来源授权及逐证券 head/interior/tail 历史覆盖仍未验收；本 PR 只关闭其限定的内部代码范围，迭代204整体仍未完成。

## OpenData PR #82：one-shot job contract 与受限 dispatcher/runtime role

[OpenData PR #82](https://github.com/cloudQuant/opendata/pull/82) 已 squash 合入 `dev`，提交为 `ce74c25399ead699f4af8fcf63dc1cdf098c9ddc`。本切片增加 `one_shot_only` job contract，并为手工 dispatcher 与 runtime role 增加封闭式范围检查。最终专用隔离套件 **401 项通过**；五个目标模块按验收收据顺序的 statement+branch 覆盖率为 **91.27% / 90.21% / 91.27% / 95.17% / 94.87%**，无排除项。早期 v9 运行 **400 项通过、1 项失败**的记录保留，不作为最终验收结果。定向静态检查通过；mypy 仍报告 **3 项基线错误**。本轮 pytest/pytest-asyncio/pytest-cov 依赖版本与项目固定版本有偏差，完整 canonical A2 未运行。

该切片不等于生产 CLI 已接通或真实 Fuyao 请求/采集已完成；也未验证旧 worker fleet 已停止、升级并完成兼容性核验。真实来源授权、生产部署、全 A 股范围以及逐证券 head/interior/tail 完整历史仍未验收；本 PR 仅关闭其受限 job contract 与 dispatcher/runtime role 代码范围，不增加迭代控制任务完成数，迭代204整体仍未完成。

## OpenData PR #83：受控 one-shot CLI 与 runtime role 接线

[OpenData PR #83](https://github.com/cloudQuant/opendata/pull/83) 已 squash 合入 `dev`，提交为 `cc4836f7445d505fc6acf050dddb7cf26b4bd3fb`。本切片为专用 submitter/executor runtime roles 增加受控 CLI 注入路径，显式绑定 run key，并提供 dry-run 与 `not_claimed` / `uncertain` 结果边界。该 CLI 能力是受限代码路径，不表示生产凭证、来源授权或真实来源调用已完成。

最终 v12 专用隔离套件 **532 项通过、2 条 warning、0 项排除**；CLI、runtime_roles、reviewed_runtime 的 statement+branch 覆盖率分别为 **92.36% / 94.44% / 94.95%**。定向 Ruff、Bandit、Gitleaks 检查通过；mypy 仍报告 **3 项基线错误**，完整 canonical A2 未运行。测试 pytest 相关版本与项目固定 pins 有差异。隔离验收证据位于 OpenData 本机私有目录 [`od204-cli-runtime-v11-v12-static-20261029`](</home/yun/Documents/opendata/var/reports/afi204/od204-cli-runtime-v11-v12-static-20261029>)。

未验收事项仍包括真实 Fuyao 请求与数据采集、生产来源授权及生产 composition、旧 worker fleet 停止/升级后的兼容核验，以及全 A 股范围和逐证券 head/interior/tail 历史完整性。PR #83 只关闭受控 CLI/runtime role 接线的限定代码范围，不改变迭代控制任务完成数；迭代204整体仍未完成。

## OpenData PR #84：单机 SQLite self-declared grant provisioning 与不确定状态对账

[OpenData PR #84](https://github.com/cloudQuant/opendata/pull/84) 已 squash 合入 `dev`，提交为 `5bb7a17117628c1f5e673a65adb6ddc9ef580212`。本切片增加单机 SQLite 上的 self-declared grant provisioning 事务与 sealed event，并补充提交/清理处于不确定状态时的对账流程。专用隔离套件 **115 项通过、0 项排除**，目标覆盖率 **98.49%**；定向 pinned 静态检查通过。早期多轮失败及曾误报的记录均保留在证据目录，没有用最终结果覆盖或改写。pytest 相关依赖版本与项目固定版本存在偏差，完整 canonical A2 未运行。证据见 OpenData 本机私有目录 [`source-grant-v6-static-20261029`](</home/yun/Documents/opendata/var/reports/afi204/source-grant-v6-static-20261029>) 与 [`source-grant-v1-v5-20261029`](</home/yun/Documents/opendata/var/reports/afi204/source-grant-v1-v5-20261029>)。

该实现面向单机 SQLite，grant 授权声明由本地操作者提供；验收没有独立证明 Fuyao 凭证有效，也没有证明供应商合同或产品权限范围。没有创建生产 grant，没有发起真实 Fuyao 请求或执行真实采集；本次 scope 也未包含具体证券及日期范围。旧 worker fleet 停止/升级兼容性、Fuyao 生产接线、全 A 股范围与逐证券 head/interior/tail 历史仍未验收。该 PR 只关闭其本地 provisioning 与不确定状态对账的限定代码范围，不增加迭代控制任务完成数，迭代204整体仍未完成。

## OpenData PR #85：Fuyao fetcher 最大请求尝试次数上限

[OpenData PR #85](https://github.com/cloudQuant/opendata/pull/85) 已合入 `dev`，提交为 `50babc5378588e134f1dede5d082beb46fdebf05`。Fuyao fetcher 现在显式接受 `max_attempts`，范围为 **1–3**，默认值为 **3**。专用隔离套件 **170 项通过、0 项排除**，目标模块 statement+branch 覆盖率 **97%**；定向 pinned 静态检查通过。pytest 相关依赖版本与项目固定版本存在差异，完整 canonical A2 未运行。验收证据见 OpenData 本机私有目录 [`fuyao-attempt-cap-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-attempt-cap-20261029>)。

现有 `process` 默认尝试次数为 3，尚未接入生产 one-shot 路径。该限制不防御恶意同进程篡改；本次未发起真实 Fuyao 请求，也未验收全 A 股或逐证券 head/interior/tail 历史完整性。该 PR 只关闭 fetcher 尝试次数上限的限定代码范围，不增加迭代控制任务完成数，迭代204整体仍未完成。

## 2026-10-29 AFI 股票信号 `benchmark_status` 展示状态

股票信号页已为 benchmark 状态补充展示映射：历史无记录显示 `unknown`，有效值显示 `available`，非有限值显示为 `null`；状态展示不改变信号计算结果或 outcome。定向隔离验证为后端 **43 passed**、前端 **4 passed**，证据目录为 [`/tmp/afi204-benchmark-status.D8bt77/out`](/tmp/afi204-benchmark-status.D8bt77/out)。

这组结果只验收状态映射与展示边界，不证明真实数据来源或其授权已经验证，也不代表全 A 股数据或历史覆盖已经验收。旧 `partial` 数据重新评分时可能覆盖既有评分的风险仍待修复；AFI 中旧的直连 AKShare 路径仍然存在。本项不调整迭代任务矩阵完成数，迭代204整体仍未完成。

## 2026-10-29 OpenData PR #86：Fuyao 尝试次数上限的子进程部署绑定

[OpenData PR #86](https://github.com/cloudQuant/opendata/pull/86) 已合入 `dev`，合并提交为 `e39f64b74a629bda55e2279ba9dd084fc987d462`。父进程部署绑定兼容 v1（缺省尝试次数为 3），并通过 v2 显式传递配置的 `transport_max_attempts`；子进程据此构造 Fuyao fetcher，结果校验要求返回值与父端绑定一致。专用隔离套件 **292 项通过、0 项排除**，三个目标文件的 statement+branch 覆盖率分别为 **93.75% / 90.67% / 93.63%**。证据见 OpenData 本机私有目录 [`fuyao-binding-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-binding-acceptance-20261029>)。

隔离运行的 pytest 相关依赖版本与项目固定版本有差异；mypy 的 **3 项错误为已记录基线错误**，canonical A2 因缺少所需历史 evidence 未执行。专用子进程 `HOME`/`USER` 配置不是操作系统安全隔离。本 PR 仍未接入实际 one-shot 生产路径，未发起真实 Fuyao 请求或采集真实来源数据，也未验收全 A 股证券全集及逐证券 head/interior/tail 历史完整性。本项只关闭尝试次数沿部署绑定传递的限定代码范围，不增加迭代控制任务完成数，迭代204整体仍未完成。

本次仅保留 tracked source tar 的 SHA 收据；验收归档及原始 evidence 均未保留 tar 文件本体，因此无法从当前归档直接重算并独立核对该 tar 哈希。

## 2026-10-29 OpenData PR #87：Fuyao 非执行声明契约

[OpenData PR #87](https://github.com/cloudQuant/opendata/pull/87) 已合入 `dev`，合并提交为 `7b6cdfdc98202d098d000f552a1067e129b59064`。本切片为 Fuyao one-shot 增加仅表达调用方声明、不会自行执行请求的契约。专用合成隔离测试 **86 项通过**；`fuyao_one_shot_contract.py` statement+branch 综合覆盖率为 **273/275（99.27%），0 行排除**。证据见 OpenData 本机私有目录 [`fuyao-contract-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-contract-acceptance-20261029/README.md>)，最终运行材料位于其 [`run-86-passed-99_27pct`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-contract-acceptance-20261029/run-86-passed-99_27pct>) 子目录。

测试采用 `opendata.pipeline` namespace-package 快照，刻意绕过正常包初始化；正常 initializer 会导入 runner/ORM，并加载 settings、构造 SQLAlchemy engine。因此这组结果不验证应用正常导入、启动或 provider composition。调用方声明自身不能证明供应商权利、授权范围、请求是否发送或被上游接收。本次没有真实 Fuyao 请求、生产 grant、数据库、服务或 provider 执行。隔离运行的 pytest/pytest-cov/coverage 为 **8.3.4 / 6.2.1 / 7.9.2**，与项目固定的 pytest **8.3.3**、pytest-cov **6.0.0** 不同。本次归档没有 mypy 运行记录，不能据此说明本次或当前 mypy 错误数；此前 PR #86 的独立记录报告过 3 项基线错误，该数字不代表本次复测结果。canonical A2 未运行，因缺少 `docs/evidence/C100/quality-scope-audit/immutable-wave9-exact5055/classification.json`。本 PR 仅关闭非执行声明契约的限定代码范围，不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #88：股票 universe 超限拒绝与截断保护

[OpenData PR #88](https://github.com/cloudQuant/opendata/pull/88) 已合入 `dev`，合并提交为 `04495b2f5294a5db313a40039022bfd95e289602`。`derive_universe` 对调用方配置的 `limit` 多读取一条记录作为超限证据；默认 `limit` 为 **5000**，调用方可指定更大的值。超过所配置上限时会在 catalog/provider/pipeline 执行前 fail closed，避免静默截断。非空显式 `symbols` 仍按既有设计绕过派生集合上限。定向隔离验证 **78 项通过、15 条 warning**；`jobs.py` statement+branch 综合覆盖率为 **428/441（97.05%），0 行排除**。证据见 OpenData 本机私有目录 [`universe-truncation-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/universe-truncation-acceptance-20261029/README.md>)，成功运行材料位于其 [`success`](</home/yun/Documents/opendata/var/reports/afi204/universe-truncation-acceptance-20261029/success>) 子目录。

这组测试以 OpenData `dev` 的 `e39f64b74a629bda55e2279ba9dd084fc987d462` 为 base，早于 PR #87 合并。静态对比认为 #87 与本次测试目标没有调用关系，但没有在 #87 合并后重跑，因此不能据此断言合并后的结果已复验或必然不受影响。运行使用 pytest/pytest-asyncio/pytest-cov **8.3.4 / 1.0.0 / 6.2.1**，与项目固定的 **8.3.3 / 0.24.0 / 6.0.0** 不同。本次归档没有 mypy 运行记录，不能据此说明本次或当前 mypy 错误数；此前 PR #86 的独立记录报告过 3 项基线错误，该数字不代表本次复测结果。canonical A2 未运行，缺少 `docs/evidence/C100/quality-scope-audit/immutable-wave9-exact5055/classification.json`。

超限保护只约束从 `dwd_stock_daily` 观察到的证券代码集合；该 DWD 集合不能证明全 A 股证券主数据、北交所范围、上市/退市边界或逐证券完整历史。超过所配置的 `limit` 会停止；默认值是 5000，调用方可传入更大上限，显式名单也可绕过派生集合限制。当前查询失败会被 `symbol_universe` 转为空集合，后续虽会拒绝执行，操作员可能只看到“universe 为空”而看不到原始查询错误；调度层重试与错误根因保留仍待处理。此 PR 不证明真实行情采集、供应商授权、全 A 股覆盖或 head/interior/tail 完整性，也不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #89：股票 universe 容量上限与兼容性

[OpenData PR #89](https://github.com/cloudQuant/opendata/pull/89) 已合入 `dev`，提交为 `cf47f06a22c254591899face3b1956305d729406`。最终隔离套件 **103 passed、15 warnings**；`jobs.py` statement+branch 综合覆盖率 **97.12%，0 项排除**。同一目标模块的 API 覆盖率 **54.44%**、schema 覆盖率 **82.11%**，是聚焦测量，不等同于 jobs.py 门槛或全链路覆盖。初次运行 **101 passed、2 failed**（`InvalidURL`），该失败记录予以保留。证据见 OpenData 本机私有目录 [`universe-capacity-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/universe-capacity-acceptance-20261029>)。

该改动把定时/builtin 增量 job 从 DWD 派生 universe 的默认上限提高到 **10,000**；这只适用于此前省略 `limit` 的相应任务，显式设置的 **5,000** 保持不变。手动 REST 请求仍默认 **200**、最大 **10,000**；增量 cron 可显式传入 **1–50,000** 的上限。测试覆盖 **10,000 个 symbols 的 ASGI 请求范围**，但这不是实际 HTTP client、反向代理或部署链路能够完整接收该请求的证明；部署前仍需核验 query string / URL 长度限制和端到端传输边界，并盘点省略 `limit` 的定时/builtin 增量任务及实际规模。

隔离运行的 pytest 相关依赖版本与项目固定版本有差异；mypy 留有 **4 项基线错误**，canonical A2 因缺少所需历史 evidence 未执行。主归档静态日志记录的两个测试文件 SHA 早于最终测试文件版本，而三个生产源码文件 SHA 与最终版一致；最终测试版的独立静态检查记录见 [`/tmp/od204-final-api-doc-static.kuudhy`](</tmp/od204-final-api-doc-static.kuudhy>) 和 [`/tmp/od204-universe-test-static.vkYILM`](</tmp/od204-universe-test-static.vkYILM>)。因此主归档静态日志不能作为最终两个测试文件的静态检查证据。support 文件校验受同一操作系统用户可并发替换文件的 TOCTOU 限制，不能作为对抗同用户恶意改写的安全边界。该 PR 未证明真实行情采集、权威全 A 股证券全集、北交所/上市退市边界，或逐证券 head/interior/tail 完整历史；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #90：universe 查询错误的安全呈现

[OpenData PR #90](https://github.com/cloudQuant/opendata/pull/90) 已合入 `dev`，合并提交为 `ad62ffc010191a517e98ebb9e7f385e3b17b2d41`。DWD universe 查询遇到受支持数据库错误时返回固定安全消息，并避免保留底层异常上下文；“无可用 universe”与容量超限继续使用 `ValueError` 子类。calendar fallback 行为保持原样，同时清理了相关日志输出。专用隔离套件 **132 项通过、21 条 warning**；`jobs.py`、calendar 与错误类相关目标的 statement+branch 覆盖率分别为 **94.15% / 97.41% / 100%**，综合 **0 项排除**。定向 Ruff、Bandit、Gitleaks 检查通过。验收证据见 OpenData 本机私有目录 [`universe-errors-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/universe-errors-acceptance-20261029>)。

隔离运行所用 pytest 相关依赖与项目固定版本有差异；mypy 仍报告已记录的 **4 项基线错误**。canonical A2 未运行，缺少所需 `classification.json`。本次只清理了所覆盖代码路径的日志，不表示其他路径均已安全脱敏；查询错误仍未区分缺表与其他数据库故障，scheduler 重试策略也未改变。没有连接真实 provider、生产数据库或全 A 股历史数据，因此本 PR 不证明真实采集、全 A 股证券全集或逐证券 head/interior/tail 完整性；不增加迭代控制任务完成数，迭代204整体仍未完成。

## 2026-10-29 OpenData PR #91：universe 确定性错误停止重试

[OpenData PR #91](https://github.com/cloudQuant/opendata/pull/91) 已合入 `dev`，合并提交为 `dc293dd339de96304b1caa97e3ec0dcde8c08607`。pipeline 遇到证券 universe 为空或超过上限这两类确定性错误时，记录失败并结束本次执行，不再按调度策略重试；失败通知标记为最终失败。数据库查询错误及其他异常保留原有重试行为。专用隔离套件 **37 项通过**，`scheduler.py` statement+branch 综合覆盖率 **60.59%，0 项排除**。证据见 OpenData 本机私有目录 [`scheduler-universe-retry-acceptance-20261029/README.md`](</home/yun/Documents/opendata/var/reports/afi204/scheduler-universe-retry-acceptance-20261029/README.md>)。

新确定性失败路径中的失败状态更新与提交由 mock 断言；同套件其他既有 SQLite 回归覆盖成功、撤权后失败及普通异常/超时场景的 `TaskExecution` 持久化，但没有验证这两类新确定性错误对应的失败记录实际持久化。临时 SQLite 测试另验证 scheduler task state 可在重启后加载。隔离测试运行的 pytest 相关版本与仓库固定版本不同。定向 Ruff 与 Gitleaks 检查通过；Bandit 未发现 scheduler 问题，但对测试断言报告 19 项 LOW B101；mypy 当前与基线相同，仍有 4 项既存错误且没有 scheduler 诊断。canonical A2 因缺少所需分类 evidence 未获验收，不能据此宣称全仓或全局静态检查通过。

本 PR 不验收真实调度服务、provider、生产数据库或网络，也不证明真实行情采集、全 A 股证券全集或逐证券 head/interior/tail 历史完整性；不增加迭代控制任务完成数，迭代204整体仍未完成。

## 2026-10-29 OpenData PR #92：离线证券 identity 集合差异工具

[OpenData PR #92](https://github.com/cloudQuant/opendata/pull/92) 已合入 `dev`，提交为 `0e1ec526d2f64c184f42bf679d74cec7f1a1a5fe`。新增纯离线工具，对两份调用方提供的证券 identity 集合做差异诊断：校验显式 SH/SZ/BJ 身份与六位代码，并稳定排序后呈现集合差异及跨交易所重复裸代码诊断。专用合成测试 **20 项通过**，目标模块 statement+branch 综合覆盖率 **93.51%，0 项排除**。定向 Ruff、单文件生产 mypy、生产 Bandit 与 Gitleaks 检查通过。证据见 OpenData 本机私有目录 [`current-instrument-census-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/current-instrument-census-acceptance-20261029/README.md>)。

该工具只比较调用方提供的两份集合，不判断两组数据是否可比，也不证明证券全集的权威性、真实性或完整性；不检查分页、数据时效、上市/退市边界或逐证券历史。它不连接 provider、采集任务、数据库或 API。测试运行时 CPython/pytest/pytest-asyncio/pytest-cov/coverage 与仓库 pins 有差异；标准库未纳入完整哈希，测试可写入 evidence 目录，不能据此宣称证据具备防恶意篡改能力。测试文件的 Bandit 报告包含 **32 项 LOW B101**；全包 mypy 仍有 **9 项既存诊断**，与基线一致。canonical A2 未验收。该 PR 只关闭离线集合差异诊断的限定代码范围，不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #93：离线证券身份时间区间解析

[OpenData PR #93](https://github.com/cloudQuant/opendata/pull/93) 已合入 `dev`，squash 提交为 `8417fe727bebfe06b169dee1d73284bb7a37da14`。新增纯离线 temporal identity resolver，以显式交易所代码和证券代码组成 identity，并按半开时间区间解析身份对应关系；未知 pair 或时间间隙返回 `UNKNOWN`；pair 映射区间重叠，或同一 instrument 在请求窗口内同时映射多个 pair（时间重叠）时拒绝解析，按顺序更名、时间不重叠的多个 pair 合法。允许不同交易所出现相同裸代码。专用合成测试 **23 项通过**，statement+branch 综合覆盖率 **100%，0 项排除**。首次测试 **17 项通过、2 项失败，覆盖率 88.22%**；修复后复测通过。证据见 OpenData 本机归档 [`temporal-instrument-identity-acceptance-20261029/README.md`](</home/yun/Documents/opendata/var/reports/afi204/temporal-instrument-identity-acceptance-20261029/README.md>)。

mypy 对测试文件报告 **5 项显式诊断**；该结果不能外推到生产模块或仓库常规类型检查。测试使用的 pytest 相关版本与项目固定版本存在差异；canonical A2 未运行，缺少所需分类 evidence。此实现没有生产数据源接入、持久化、API 或规范化 registry digest；`source_sha256` 是调用方提供的声明，不能证明身份全集权威、全 A 覆盖、来源真实性或历史完整性。本 PR 仅完成离线时间区间解析的限定范围，不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 北交所目录 endpoint 受控探测记录

北交所目录 endpoint 的调用参数来源于 vendored AkShare 脚本 `src/backend/app/data_fetch/scripts/stocks/weekly/stock_info_bj_name_code.py`。2026-10-29 的两次受控、非凭证 POST 单页探测均返回 **HTTP 307、164 字节**；第二次响应的 `Location` 指向相同 URL。请求没有跟随重定向，响应中没有目录数据。这一有限探测结果不构成接口故障判断、证券目录完整性结论或真实数据采集证明。

探测的脱敏响应材料与边界说明归档于 OpenData 本机私有目录 [`bse-directory-probe-20261029`](</home/yun/Documents/opendata/var/reports/afi204/bse-directory-probe-20261029/README.md>)。证据仅保存第二次响应的 headers；首次 307 及两次 POST 的事实依据为执行记录和 README，未留存首次 headers 或逐次完整请求回执。后续仍需取得可核验的上游原始样本，并在明确边界和限额后谨慎实现受控 POST 与解析验证；本次探测没有完成这些工作。权威全 A 股目录、北交所及退市证券生命周期仍未验收，相关控制任务保持开放，本记录不改变迭代任务计数。

## 2026-10-29 OpenData PR #94：时间身份快照规范 JSON codec

[OpenData PR #94](https://github.com/cloudQuant/opendata/pull/94) 已合入 `dev`（`edb9cfa73fc95ed9f469bed8415d864afca9e8a0`）。本切片新增时间身份快照的规范 JSON 编码/解码：固定规范字节及内嵌内容 SHA-256、要求显式 `snapshot_type`、限制文档大小与嵌套深度、拒绝重复 JSON 键，并在往返编码/解码中保留半开时间区间语义。专用合成隔离测试 **41 项通过**，statement+branch 综合覆盖率 **98.07%，0 行排除**。验收收据见 OpenData 本机私有目录 [`temporal-identity-snapshot-codec-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/temporal-identity-snapshot-codec-acceptance-20261029/README.md>)。

候选迭代记录为：R1 因 builder 预检未找到精确 pin 文件而退出、未运行 pytest；R2 为 **19 项通过、1 项失败**，综合覆盖率 **86.19%**；修正候选后 R3 才得到上述结果。定向 Ruff、生产模块 mypy、Bandit 与 Gitleaks 检查通过；全包 mypy 仍有 **9 项既存诊断**，与本切片无关。测试使用的 pytest/pytest-asyncio/pytest-cov 版本与仓库 pins 不同；canonical A2 未运行，所需历史分类 evidence 缺失。因此这些定向结果不代表整仓 A2 或全局质量门禁通过。

内嵌 SHA-256 只能检查文档内容与同一文档所带摘要自洽；若内容和摘要一并被改写，仍可得到匹配值，只有与可信外部摘要比对才可发现对应字节变动。该 codec 不证明快照来源真实性、供应商授权或证券全集权威性，也未增加持久化、REST/API 或真实主数据接入。它不证明全 A 股覆盖或逐证券历史完整性，不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #95：时间身份版本化分块存储

[OpenData PR #95](https://github.com/cloudQuant/opendata/pull/95) 已合入 `dev`，squash 提交为 `2897a878ed4b63b86ee39a8b5f8e700887602948`。该切片新增 Alembic `0021` 和显式注入数据库 engine 的版本化、分块时间身份快照存储；提交前校验外部提供的完整快照 SHA-256，并在版本冲突时 fail closed。专用 R2 合成隔离测试 **141 项通过**，statement+branch 综合覆盖率 **95.27%，0 行排除**。验收材料归档于 OpenData 本机私有目录 [`temporal-identity-store-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/temporal-identity-store-acceptance-20261029/README.md>)。

R1 曾出现 **140 项通过、1 项失败**，原因是 SQLite TEXT/BLOB 表示处理，修正后 R2 通过。并发双 worker 和连接池大小为 2 的合成测试不能证明底层 DBAPI 实际取得了两条独立连接；MySQL 仅做模拟，未连接真实 MySQL。实现只存储显式提交的完整版本，不做 delta 合并；不会自动建表或执行迁移，尚未接入 REST/API 或采集任务。持久化本身不认证调用方、身份命名空间权威性、供应商授权或主数据来源；此前 codec 摘要没有覆盖 namespace authority/registry，因此该存储不能补足来源认证。测试 pytest 版本与仓库 pins 不一致，canonical A2 未运行；全包 mypy 有 **15 项既存诊断**。本 PR 仅完成限定的持久化切片，不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 AkShare/Eastmoney 单票手工 pilot

本机 `capture.json` 将一次受限手工 pilot 记录为底层 Eastmoney 日线 endpoint **HTTP 200**、`attempts_used=1`，范围为 **1 只证券的短日期窗口**。这些状态和尝试次数是本机 manifest 的声明；原始 body 本身不能独立证明 HTTP 状态、实际发送次数，也不能证明执行前后没有其他请求或提供上游签名。保存的 body 为 **1,048 字节**，SHA-256 为 `2d707ecd928e70a8d7695b621ee437aa90644036600b5c5e9ed19f302f32c509`，与 `capture.json` 中记录的长度和摘要匹配。body 含 **10 条**记录，观察日期范围为 **2026-10-12 至 2026-10-23**；本地 wire 与 source-native 解析对 11 个字段的逐行结果一致。证据位于 OpenData 本机私有目录 [`capture.json`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-akshare-live.2JIE6I1L/capture/capture.json>) 与 [`raw-response.bin`](</home/yun/Documents/opendata/var/reports/afi204/2026-10-29-akshare-live.2JIE6I1L/capture/raw-response.bin>)；本文不记录证券代码或行情值。

本次只记录该单票短窗口的 body 及本地解析观察，不证明 HTTP 状态、实际发送次数、字段单位、复权语义、来源法律身份、Eastmoney 合同或其数据授权已核验、生产采集授权、全 A 股覆盖或逐证券完整历史。解析走 body-only 路径，不等同于经 `RawResponseArtifactWriter` 验证的 capture，也不证明内容寻址 artifact 全链路已验收。capture manifest 的 `state` 仍记为 `attempt_reserved_before_transport`，与其中记录的 HTTP 200 和已有响应 body 不一致；应通过后续独立改动修复状态生成逻辑并保留这份历史证据原样，不回写或重写本次 artifact。仓内 source-rights 记录的是用户对 AkShare 与 Fuyao 可使用的部署方声明；这不扩大为 Eastmoney 合同或具体 endpoint 权利已独立核验。本次观察不增加迭代控制任务完成数；迭代204整体仍未完成。

## 2026-10-29 OpenData PR #97：离线 stock_daily 时态身份 mapper

[OpenData PR #97](https://github.com/cloudQuant/opendata/pull/97) 已合入 `dev`，合并提交为 `9d388174914b4896bb82e127942991b836d65110`。该切片新增纯离线 mapper，把通过本地 native 合同校验的 AkShare/Eastmoney 日线响应逐行绑定到指定时态身份，保留原始 source tokens，并显式将结果标记为 `identity_bound_candidate`。专用合成隔离测试 **32 项通过**；`stock_daily_mapper.py` 语句与分支合计覆盖率为 **97.58%（242/248，0 项排除）**。最终验收记录见 OpenData 本机私有目录 [`ACCEPTANCE_ADDENDUM.md`](</home/yun/Documents/opendata/var/reports/afi204/stock-daily-mapper-acceptance-20261029/final-run-4iiwbEpA/ACCEPTANCE_ADDENDUM.md>)。

mapper 只在调用方提供的 operator pin registry 与身份 registry 满足绑定关系、且完整身份快照规范字节的 SHA-256 与 pin 相符时产出候选；可信 pin registry 必须来自已校验的 operator-owned runtime 或等价的受审边界。mapper 本身不认证 pin 发布者、调用方、来源权限或数据完整性，也不抓取、落库、发布或补造记录。当前验收仅覆盖离线合成输入，不证明真实 provider 行为、单位/复权含义、市场范围、逐证券历史完整性或生产接线；全 A 股及 head/interior/tail 完整性仍未验收，迭代204整体仍未完成。

## 2026-10-29 OpenData PR #98：时间身份只读 REST API 与 runtime

[OpenData PR #98](https://github.com/cloudQuant/opendata/pull/98) 已合入 `dev`，合并提交为 `1ee7be9c07af6b5eb5aa271de9bc4bb2fd054e98`。该切片接通 `POST /api/v2/identity/resolve` 只读解析接口、operator pin 校验 runtime 与应用 lifespan 配置。`TEMPORAL_IDENTITY_ENABLED` 默认关闭；启用时要求 operator-owned pin 文件及独立配置的 SHA-256（可信发布流程尚未验收），并通过受限只读 store 查询，不在应用启动时自动迁移数据库。最终隔离运行 **359 项通过**，五个改动模块语句与分支合计覆盖率 **96.25%（1,410/1,465，0 项排除）**。验收使用真实 FastAPI lifespan、临时 SQLite 上的 Alembic `0021`、合成身份行与本地 ASGI 请求；不是生产数据库或服务验证。验收记录见 OpenData 本机私有目录 [`temporal-identity-lifespan-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/temporal-identity-lifespan-acceptance-20261029/final-run/README.md>)。

本次不证明真实 MySQL/InnoDB 行为、实际 `GRANT` 权限、生产凭证与 pin 配置、部署上线、真实市场身份或全 A 股市场覆盖；逐证券上市至今及 head/interior/tail 历史也未验收。该隔离测试使用 CPython 3.13.5 和本机测试依赖版本，项目最低支持版本的干净安装及 canonical A2 未验收。因此 API/runtime 目前保持默认关闭；生产启用须先完成独立的 MySQL 只读授权与部署核验、可信 pin 发布流程及市场/历史覆盖证据。以上 PR 只关闭各自限定代码范围，不代表迭代204整体验收或全量历史恢复完成。

## 2026-10-29 OpenData PR #99–#101 与 AFI PR #151–#152：native 日线和时间身份离线切片

以下提交均已合入各自仓库的 `dev`，只关闭明确列出的代码切片，不增加迭代控制任务完成数。它们形成离线候选、身份 pin staging/import、AFI client 与 synthetic wire 合同的验证链，不表示全 A 股真实数据已采集或生产服务已上线。

| PR | 合并提交与定向结果 | 范围和验收边界 |
| --- | --- | --- |
| [OpenData PR #99](https://github.com/cloudQuant/opendata/pull/99) | `388afc2724cb7611c80a8111b5cd23198813f1f6`。冻结候选上的 **19 项 synthetic 测试通过**；`stock_daily_native_mapping.py` statement+branch 综合覆盖率 **99.06%（210/212，0 项排除）**。 | 将本地提供的 native 日线 evidence 映射为候选，不执行 provider 抓取、持久化或发布。验收运行在合入前冻结的 OpenData `1ee7be9c07af6b5eb5aa271de9bc4bb2fd054e98` 基线上；目标源码哈希与 #99 合并提交中的源码相同。输入是合成 raw evidence 和注入的身份 runtime，source authenticity 为 unverified、history coverage 为 unknown、结果 not persisted/not published。证据见 OpenData 本机私有目录 [`acceptance.md`](</home/yun/Documents/opendata/var/reports/afi204/stock-daily-native-mapping-acceptance-20261029/acceptance.md>)。 |
| [OpenData PR #100](https://github.com/cloudQuant/opendata/pull/100) | `1be9cb1e2c422c295b05d15a1f40cdefad18a0f2`。**385 项通过**；`temporal_identity_staging.py` **92.25%**、`temporal_identity_pins.py` **93.87%**、identity API **88.41%**、runtime **97.50%**；相关模块均为 statement+branch 综合口径，0 项排除。 | 新增离线 pin staging。验收覆盖 synthetic 数据、真实 FastAPI/本地 ASGI 及临时 SQLite 路径；不证明生产 MySQL/InnoDB 或 grant 行为。该次验收未使用真实身份源，也未核验用户已声明授权与具体端点/合同边界的对应关系；没有发布 operator pin，也没有全 A 股/逐证券全历史证据。证据见 [`temporal-identity-staging-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/temporal-identity-staging-acceptance-20261029/README.md>)。 |
| [OpenData PR #101](https://github.com/cloudQuant/opendata/pull/101) | `261a23e36e7dde2fc512ad1bb9b0ac21d406867d`。**422 项通过**；staging **92.37%**、store **95.33%**、importer **93.75%**、pins **93.87%**、identity API **88.41%**、runtime **97.50%**；statement+branch 综合口径，0 项排除。 | 新增身份快照候选导入。输入身份及信任材料为 synthetic，数据库集成使用临时 SQLite；本次未导入真实身份源快照，也未核验用户已声明授权与具体端点/合同边界的对应关系；未发布 operator pin。MySQL/InnoDB、生产 grants、真实全 A 股全集及从上市起点到当前的逐证券覆盖均未验收。证据见 [`temporal-identity-import-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/temporal-identity-import-acceptance-20261029/README.md>)。 |
| [AFI PR #151](https://github.com/cloudQuant/ai-for-investor/pull/151) | `8f7b1581febabc899c9046ca38c355aa83772bde`。定向 **68 项通过**，branch-inclusive coverage **89.08%（465/522，0 项排除）**。 | 增加严格的时间身份 client，但尚未接入 AFI 现有业务读路径。验收使用 HTTPX MockTransport 和隔离兼容层，不访问实际 OpenData 服务、真实市场来源或生产数据库；不验收部署配置、授权、全 A 股范围或全历史。验收证据见 [`ACCEPTANCE.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/temporal-identity-client-acceptance-20261029/ACCEPTANCE.md>)。 |
| [AFI PR #152](https://github.com/cloudQuant/ai-for-investor/pull/152) | `3eb658058068a752dd4abad7a285102c57422951`。**5 项通过，9.42 秒**；本次没有采集 coverage，故无覆盖率结论。 | synthetic 跨仓 wire 用例在固定 AFI #151 (`8f7b1581febabc899c9046ca38c355aa83772bde`) 与 OpenData #101 (`261a23e36e7dde2fc512ad1bb9b0ac21d406867d`) 上运行，经受限进程内 transport 调用真实 FastAPI ASGI route；迁移 `0021` 仅应用于临时 SQLite，API keys、grants、pins 和 snapshot rows 均为 synthetic。此结果只验证协议路径，不证明生产 MySQL/TLS/grants、部署上线、供应商授权或数据完整性，也不表示 AFI 现有业务已切换到该 client。证据见 [`temporal-identity-wire-acceptance-20261029`](</home/yun/Documents/ai-for-investor/var/reports/afi204/temporal-identity-wire-acceptance-20261029/README.md>)。 |

以上合成测试和本地 SQLite 结果均不证明权威全 A 股证券全集（含北交所及退市证券）、来源授权、真实行情或身份数据质量、全历史 head/interior/tail 覆盖、生产 MySQL 权限与运行、可信 pin 发布或 AFI 业务路径迁移。迭代204整体仍未完成，生产启用及完整历史恢复保持开放。

## 2026-10-29 OpenData PR #102–#103 与 Fuyao 单次试采

[OpenData PR #102](https://github.com/cloudQuant/opendata/pull/102) 与 [PR #103](https://github.com/cloudQuant/opendata/pull/103) 均已合入 `dev`。各自隔离验收分别为 **196 项通过、95.84% statement+branch 综合覆盖率、0 项排除**，以及 **67 项通过、86% statement+branch 综合覆盖率、0 项排除**。这些数字仅代表各 PR 的限定测试与覆盖范围，不表示全市场数据治理或生产链路已经验收。相关收据均保存在 OpenData 本机私有 `var/reports/afi204` 目录下：#102 [`fuyao-bounded-stream-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-bounded-stream-acceptance-20261029>)，#103 [`fuyao-stock-daily-pilot-acceptance-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-stock-daily-pilot-acceptance-20261029>)。

另完成 Fuyao 单次受限试采：标的 `600519.SH`，日期范围 `2026-10-19` 至 `2026-10-23`，本机观测到 **HTTP 200、5 条记录**，请求预算为 **1**。这是本地运行记录，不是供应商签名的收据，也不独立证明执行期间全局只有一次请求。证据首选长期归档于 OpenData 本机私有目录 [`fuyao-stock-daily-live-20261029`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-stock-daily-live-20261029>)；原始 cache evidence 仍保留在 [`evidence`](</home/yun/.cache/od204-fuyao-live-wD1cBDHW9Z/evidence>)。

同一五日窗口的 Fuyao 与 AkShare 双源对照中，价格和成交额逐日吻合；成交量约相差 **100 倍**，单位尚未通过供应商契约核实，不能据此认定量纲一致或直接混用。该对照只覆盖这五个交易日，不构成更长区间或其他证券的交叉验证。

该单票短窗口结果不证明全 A 股覆盖、逐证券从上市至今的历史完整性、复权语义或单位，也未验收生产调度、存储、REST 服务或 AFI 业务调用链。全市场历史 head/interior/tail 对账与生产接线仍保持开放，迭代204整体尚未完成。

## 2026-10-30 OpenData PR #104、AFI PR #155 与 Fuyao MySQL 竖向验收

OpenData [PR #104](https://github.com/cloudQuant/opendata/pull/104) 已合入 `dev`（`a3ae9d5642b2dd60ffafe5842c239058b1f5813a`）；离线转换专项 **45 项测试通过**，statement+branch 综合覆盖率 **98.08%，0 项排除**。验收摘要见 OpenData 本机私有证据 [`SCOPE.md`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-stock-daily-observations-acceptance-20261030/final-r3/SCOPE.md>)。

AFI [PR #155](https://github.com/cloudQuant/ai-for-investor/pull/155) 已合入 `dev`（`a3bf64d498453136acbdc05123b2c4fff83b50bb`）；handler→provider 接线专项 **5 项测试通过，0 项 skip**。测试使用 synthetic capability/auth/storage 与 MockTransport，未调用 ASGI route，未测试 API-key 认证、生产 API key 或生产数据库。验收摘要见 AFI 本机私有证据 [`summary.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/opendata-unadjusted-query-acceptance-20261030/final-r6/summary.md>)。以上结果仅覆盖各自限定代码路径。

另以此前受限试采留存的 Fuyao 样本（本次未重新认证来源真实性），完成一次新的隔离 MySQL 8.4 ODS/DWD 幂等写入与真实 ASGI route 联合验证。ODS 与 DWD 各对 **5 行**执行两次写入，重放后行数仍各为 **5**。数据库域权限使用 synthetic override：有权限请求返回 **200**，无权限请求返回 **403**；route 返回的 **5 行**与存储值一致。principal override 为 synthetic；未测试 API-key 认证，也未使用生产 key。MySQL 临时实例禁用网络，验收结束后子进程正常退出，owned datadir 已确认移除。验收证据已归档于 OpenData 本机私有目录 [`acceptance-summary.json`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-stock-daily-mysql-vertical-20261030/acceptance-summary.json>)。运行日志有两条 `MY-010338` (`errmsg.sys` 缺失) 警告；实例随后进入 ready 状态，验收和 shutdown 均正常，但这不构成 MySQL 完整配置健康的证明。

此结果使用非生产临时数据库，不访问生产数据库；只验证既有样本上的指定写入、幂等和读取路径，不验收全历史覆盖、北交所范围、成交量单位或 QFQ 复权语义，也不代表生产部署与权限已验收。迭代204整体仍未完成。

## 2026-10-30 AFI→OpenData 双仓隔离 MySQL 桥接验收

在同一轮隔离验收中，以 **5 条合成数据**完成 AFI Python `query_market_data` handler → 实际 `OpendataProvider` → `httpx.ASGITransport` → OpenData 实际 `GET /api/v1/data/equity/stock_daily` route 的跨仓查询。请求将 `unadjusted` 映射为 `none`，单次查询使用 `[2026-10-19, 2026-10-24)` 半开窗口（OpenData route 对应含首尾的 2026-10-19 至 2026-10-23），发出 **1 个**内部请求；返回 **5 行**，逐行与合成预期及数据库值相符，业务键唯一，窗口和字段合同校验通过。该链路经过 AFI Python handler，但**未经过 AFI HTTP 入口**。

实际本机临时 **MySQL 8.4.0** 上，合成样本分别写入 ODS 与 DWD，各执行两次幂等写入；两次写入计数均为 5，重放后两表仍各有 5 行且值一致。实例仅使用 Unix socket 并启用 `skip-networking`，本次外网请求数为 **0**。验收结束后 mysqld 子进程正常退出，受本次验收管理的实例目录已移除。脱敏摘要和归档清单位于 OpenData 本机私有证据目录 [`afi-opendata-mysql-bridge-20261030`](</home/yun/Documents/opendata/var/reports/afi204/afi-opendata-mysql-bridge-20261030>)；归档未包含原始日志、行情明细、运行器或凭据。

认证边界仍为合成环境：AFI auth/resolver/store 与 OpenData principal 均由 synthetic 依赖提供；只检查合成 key header 的传递和匹配，没有测试真实 API-key 认证或真实 key。样本与数据库行均为合成数据，未验证来源真实性或授权；价格/成交量等原生单位、调整因子语义、权威证券身份、北交所与退市生命周期、任何标的从上市至今的全历史 head/interior/tail 完整性均未验收。运行时依赖未由锁文件固定，因此结果不能代表其他环境的依赖组合，也不构成生产部署、权限或服务验收。

MySQL 启动日志中有 `MY-010338`/`errmsg.sys` 配置诊断 2 行、`utf8mb3` 弃用提示 4 行、自签 CA/证书提示 1 行及临时实例 root 空密码初始化提示 1 行。脱敏分类计数和原始日志 SHA-256 见 [warning-review.md](</home/yun/Documents/opendata/var/reports/afi204/afi-opendata-mysql-bridge-20261030/mysql-warning-review/warning-review.md>)；原始日志未复制或摘录。这些提示仅来自本次使用私有 Unix socket、禁网的临时实例，不构成部署建议或生产安全结论。

AFI #157 的时间身份 v2 是方案；OpenData #105 已合入 `dev`（`ea0642e14565bf76f6011300aad12a3b8088fed2`），I0 DTO 的定向隔离验收为 **12 项通过**、statement+branch 综合覆盖率 **95.33%**、**0 项排除**；范围说明见 OpenData 本机私有证据 [`SCOPE.md`](</home/yun/Documents/opendata/var/reports/afi204/identity-bound-stock-v2-contract-acceptance-20261030/SCOPE.md>)。这些合成测试验证了 identity-bound stock v2 DTO 合同；尚未用真实 provider 响应生成或验证 candidate，也未接入 API 或 persistence。真实身份、BSE、QFQ 和全历史均未验收。canonicalizer 必须针对固定快照重新解析身份，不得信任候选 DTO。

## 2026-10-30 OpenData PR #106–#107：pipeline 延迟初始化与 identity-bound 日线 candidate

OpenData [PR #106](https://github.com/cloudQuant/opendata/pull/106) 已合入 `dev`（`7f3254ca865727f55bff55ac72dc3a39c9b10fec`）。它把 pipeline 包的 runner/config/engine 初始化延迟到实际访问时；定向隔离验收 **2 项通过**，`opendata/pipeline/__init__.py` statement+branch 综合覆盖率 **94.12%（32/34，0 项排除）**。证据见 OpenData 本机私有目录 [`SCOPE_NOTES.txt`](</home/yun/Documents/opendata/var/reports/afi204/pipeline-lazy-exports-acceptance-20261030/SCOPE_NOTES.txt>)。本次只覆盖延迟导出目标；完整 pipeline 包覆盖率为 **20.19%**，不代表包级通过。部分 DDL 等依赖仍会加载；测试采用隔离 stub，没有执行真实 runner、采集、数据库或 provider 请求。

OpenData [PR #107](https://github.com/cloudQuant/opendata/pull/107) 已合入 `dev`（`2dadb7e367acc64af12198c9ee13afdb63c5cf9b`）。它新增离线组合流程：读取已捕获的 raw response artifact，校验调用方提供的 pin 文档与完整身份快照的哈希及关联一致性，再将逐日观测映射为 identity-bound raw candidate；该校验不认证 pin 发布者。定向隔离验收 **49 项通过**；目标 `identity_bound_stock_candidate_v2.py` statement+branch 综合覆盖率 **94.59%**、**0 项排除**。完整 pipeline 覆盖率为 **2.42%**，不作为此目标的验收结论。范围与收据见 OpenData 本机私有证据 [`SCOPE.md`](</home/yun/Documents/opendata/var/reports/afi204/identity-v2-native-candidate-acceptance-20261030/SCOPE.md>)。

#107 只消费离线 synthetic/local artifacts，不发网络请求、不写数据库或发布 candidate；未知身份区间保持 unknown，不补造日期。`request_binding_status=caller_declared_summary_hash_only` 明确表示请求摘要由调用方声明，不证明实际 HTTP query bytes；source adapter version、历史覆盖、native units、调整语义及代码 provenance 中的 rights 状态仍记为 unknown。用户已声明 AkShare 与 Fuyao 可用于本项目；本次离线验收不独立核对具体供应商合同或 endpoint 条款，这不构成对该授权声明的否定。虽然对外错误文本使用固定脱敏代码，异常的 `__context__` 仍可能暴露原异常，需在后续边界处理中解决。目标文件的 scoped mypy 检查通过；import-follow 另外报告 **7 条已有依赖诊断**，不应据此宣称全仓 mypy 通过。真实身份与来源、北交所及退市生命周期、逐证券上市至今的 head/interior/tail 全历史、生产 API/数据库行为仍未验收，迭代204整体未完成。

## 2026-10-30 OpenData PR #108：证券来源分页观察与普查判定

OpenData [PR #108](https://github.com/cloudQuant/opendata/pull/108) 已合入 `dev`（`816e7f03cbd156a11c10ab6311096344d3e9b082`）。该切片新增离线数据结构，用于保留证券来源字段观察、调用方声明的请求/响应哈希及分页字段，并评估所提交的分页链是否自洽；哈希仅作格式检查，未校验对应字节。专用合成离线测试 **40 项通过**；目标模块 statement+branch 综合覆盖率 **93.49%（632/676，0 项排除）**。验收范围见 OpenData 本机私有证据 [`scope.json`](</home/yun/Documents/opendata/var/reports/afi204/instrument-source-census-acceptance-20261030/scope.json>)。

分页回执和页链信息由调用方声明；内部自洽不验证原生页码连续性或来源真实性，也不证明任何市场证券全集及历史生命周期完整。本切片没有接入 API、数据库或真实采集；北交所覆盖缺口仍未验收。全 A 股权威目录、退市生命周期及逐证券上市至今的历史完整性继续开放，迭代204整体未完成。

## 2026-10-30 OpenData PR #109：Fuyao 证券普查候选解析

OpenData [PR #109](https://github.com/cloudQuant/opendata/pull/109) 已合入 `dev`（`34f19355d90654a92652dd81b68d55f9a3c5b75e`）。该切片从调用方提供的 Fuyao 普查响应结构生成证券候选，并保留来源字段观察及未验证状态；专用 synthetic offline suite **110 项通过**，目标文件 `fuyao_instrument_census.py` statement+branch 覆盖率 **557/559（99.6422%），0 项排除**。隔离收据位于 OpenData 本机私有目录 [`fuyao-instrument-census-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-instrument-census-acceptance-20261030>)，其 `SHA256SUMS` 中所列文件均已核对匹配。

另有 AkShare 真实本地样本的 R5 离线解析结果，由集成者执行并提供结果，归档者未独立重跑；记录在 OpenData 私有证据 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/identity-v2-real-sample-acceptance-20261030/README.md>)：解析 **10 行、110 个原生来源 token**，源 token 与候选 token 的摘要相同；其中 **1 行身份为调用方声明且未验证，9 行身份未知**。原响应字节由 SHA-256 标识并作为原始来源记录保留；JSON 解码进入浮点数时仍可能产生数值舍入，因此不能把解码候选视为逐字节等价的响应副本。归档 wrapper 的时间是本地重包时间，原 `retrieved_at` 是未签名的调用方声明值。

该 R5 结果只证明既有本地捕获样本在离线流程中的解析观察。请求绑定仍是调用方声明的摘要，不能证明实际 wire 请求；来源分页、市场范围、证券身份、退市生命周期及历史完整性仍未知。#109 与该样本结果均未接入定时采集、数据库持久化或 REST API，也未验证真实 Fuyao 普查链路。全 A 股权威全集与逐证券上市至今的 head/interior/tail 对账仍开放，迭代204整体未完成。

## 2026-10-30 OpenData PR #110：Fuyao 有界原始 HTTP 交换

[OpenData PR #110](https://github.com/cloudQuant/opendata/pull/110) 已合入 `dev`，提交为 `ea4c6f7f664a7ba33c3e1dc2fae37adb8f40f5c4`。隔离验收运行 **165 项 mock/offline tests**；目标 `opendata/data/providers/ths/transport/http_client.py` 的 statement+branch 综合覆盖率为 **781/845（92.4260%），0 行排除**。归档收据位于 OpenData 本机私有目录 [`fuyao-raw-exchange-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-raw-exchange-acceptance-20261030>)；归档 `SHA256SUMS` 所列 **10 个文件均已核对匹配**。归档说明本次只用 mock 和临时测试 fixture，并排除了 `.env`、数据库文件及原始供应商响应。

本次没有发起真实 Fuyao 请求，没有验证数据库写入或生产服务，也没有接入或运行定时调度；结果不证明数据单位、历史覆盖或生产运行行为。Fuyao 原始响应、错误和日志可能回显凭据；调用方必须在归档前检查并脱敏这些输出。当前验收归档声明其 allowlist 文件已按常见 Fuyao/API-key、Bearer 与 secret-like 模式扫描且未发现匹配，但这不是通用秘密扫描器，也不替代归档者逐项检查。已有 mypy 诊断仍未解决，本收据不构成 mypy 通过结论。权威全 A 股底册（含退市及北交所生命周期）和逐证券从实际上市起点至今的 head/interior/tail 全历史对账仍未完成；迭代204整体继续开放。

## 2026-10-30 OpenData PR #111：Fuyao A 股当前目录有界采集器

[OpenData PR #111](https://github.com/cloudQuant/opendata/pull/111) 已合入 `dev`，提交为 `4fb0ba2826fcff09afe5429d6c3c3ffd42868727`。本切片增加一次性、最多读取两页的当前证券目录采集器，并对有限的凭据编码回显样例及本机同用户 nonce 范围进行检查。合成离线专项 **59 项测试通过**；目标模块语句与分支合计覆盖 **744/815（91.2883%）**，排除 **0**。收据范围及限制见 OpenData 本机私有证据 [`SCOPE.md`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-a-share-catalog-capture-acceptance-20261030/SCOPE.md>)；该目录 `SHA256SUMS` 所列文件均已核对匹配。

本次没有发起真实 Fuyao 或 AkShare 请求，也未验证这些上游端点的行为、具体端点权限或字段语义；没有访问生产数据库或 API，也没有接入或运行定时调度。有限编码样例不构成全面凭据泄漏审计；同用户本机 nonce 检查不证明跨用户、跨进程重启或跨主机的全局唯一性。最多两页的当前目录结果也不证明权威全 A 股证券全集、北交所及退市生命周期，或逐证券从上市至今的 head/interior/tail 全历史覆盖。生产接线与完整历史验收仍开放，迭代204整体未完成。

## 2026-10-30 Fuyao A 股当前目录真实单页受限采样

根代理在 OpenData HEAD `4fb0ba2826fcff09afe5429d6c3c3ffd42868727` 上运行受审查的 launcher，运行记录报告 **1 页、HTTP 200、5,579 行、1,124,308 字节**。本次详情只保存在 OpenData 本机私有摘要 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/fuyao-catalog-live-summary-20261030/README.md>)；已核对其 `SHA256SUMS`，README SHA-256 为 `fce9560ed00562c1e0bd29950ede2583b9a80783fc86e57907fd26c5e4b2ff70`。摘要报告的 launcher SHA-256 为 `78b273f2a257ef639d4fce7ad7e20bc08157a8b1f6fb9a96b41012dcb52cb3b5`；这是运行记录中的值，不是签名证明。

该观察只覆盖一次当前目录单页：分页是否完整未知，当前列表不含退市证券，市场全集（包括北交所及退市生命周期）、历史生命周期和来源真实性均未证明。回执没有把 nonce 摘要与源码哈希绑定；根代理的运行记录不是签名的执行证明。执行环境没有操作系统级网络隔离，项目完整 `.env` 被加载到进程内存，运行时依赖也没有按哈希锁定。本次没有生产数据库写入、REST API 发布/调用或定时任务执行；不能据此宣称目录已入库、已对外提供或已具备周期更新能力。全 A 股权威全集与逐证券从实际上市起点至今的 head/interior/tail 对账仍开放，迭代204整体未完成。

## 2026-10-30 Fuyao 当前目录样本的离线 profile

根代理对一次真实采集样本进行离线聚合，隔离进程读取了原始响应；归档者只根据根代理提供的结果撰写摘要，没有读取原始响应、环境文件、数据库或凭证。摘要报告一页 **5,579** 行，provider `thscode` 为 **5,579** 个非空字符串且互异，重复及冲突均为 **0**；原始交易所 token 统计为 `SH` **2,319**、`SZ` **2,905**、`BJ` **355**；`list_date` **5,579** 条全部为 null。该[私有摘要](</home/yun/Documents/opendata/var/reports/afi204/fuyao-catalog-profile-20261030/README.md>)已在归档目录内按 `SHA256SUMS` 核对，SHA-256 为 `48e9c5f219f4205dce36a8cae183d6891db0f944dd1bfcf14b946cc2ea77b8eb`。这些数字是摘要自报的观察，不是签名执行证明，也不验证 provider 代码、来源真实性或安全主数据身份；运行时的部分只读挂载没有逐文件哈希固定。

样本只有一页，分页是否完整、来源真实性及全市场覆盖均未知；其中不含或未能证明退市证券，`list_date` 全空也不能推断证券实际上市起点。该 profile 不构成权威全 A 股目录、北交所及退市生命周期或逐证券上市至今 head/interior/tail 历史完整性的验收。相关工作与迭代204整体仍未完成。

## 2026-10-30 OpenData PR #112：上交所证券普查离线解析

OpenData [PR #112](https://github.com/cloudQuant/opendata/pull/112) 已合入 `dev`，提交为 `c109c1d829b4c5cc189a2a132c0704c1819be9b1`。离线 synthetic 专项 **134 项测试通过**；目标 `opendata/pipeline/sse_instrument_census.py` 的 statement+branch 综合覆盖率为 **649/663（97.8884%），0 行排除**。验收归档位于 OpenData 本机私有目录 [`sse-instrument-census-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/sse-instrument-census-acceptance-20261030>)，其中 `SHA256SUMS` 所列文件已逐项校验匹配。

覆盖率使用 pipeline 目录作为采集 selector，再从覆盖率 JSON 读取精确目标模块的 statement/branch 计数。该 selector 是集成者基于当前运行环境作出的技术决定：此前 dotted module selector 出现包预导入/模块移除风险。reviewer 曾提出优先直接选择精确模块的意见；复核未发现仓库规则强制要求该 selector，因此本次按归档中记录的目录 selector 与精确目标统计验收。完整 pipeline 覆盖率不作为本模块的验收结论。

本切片只验证 synthetic 离线解析和普查结构，不证明来源页面的真实性或分页完整性，也不证明任何企业/证券的权威身份、上市或退市日期、真实上交所行为或全 A 股全集。未调用真实 SSE、未访问数据库或 REST API，也未运行定时任务；逐证券上市至今的全历史 head/interior/tail 覆盖仍未验收。迭代204整体继续开放。

## 2026-10-30 OpenData PR #113：深交所生命周期 XLSX 离线解析

OpenData [PR #113](https://github.com/cloudQuant/opendata/pull/113) 已合入 `dev`，提交为 `805b3e6e31708138fbc42db3870e5c0fc3a921f9`。离线 synthetic 专项 **64 项测试通过**；目标 `opendata/pipeline/szse_lifecycle_xlsx_adapter.py` 的 statement+branch 综合覆盖率为 **792/817（96.9400%），0 行排除**。验收证据位于 OpenData 本机私有目录 [`szse-lifecycle-xlsx-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/szse-lifecycle-xlsx-acceptance-20261030>)；已逐项核对其 `SHA256SUMS` 所列文件，全部匹配。

本切片使用 synthetic 工作簿表头进行离线解析验收；没有验证真实深交所 XLSX 的表格格式、字段及日期/生命周期语义，也没有证明普查和历史数据完整性。未验证数据库写入、REST API 或定时调度。权威全 A 股证券全集（含北交所及退市生命周期）和逐证券从实际上市起点至今的 head/interior/tail 全历史对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #114：上交所生命周期采集工具隔离验收

OpenData [PR #114](https://github.com/cloudQuant/opendata/pull/114) 已合入 `dev`（`490a1cd09ebc10381b1b68337f51eb3c51723937`）。synthetic 隔离测试 **39 项通过**；目标采集脚本 statement+branch 综合覆盖率 **453/457 = 99.1247%**，**0 项排除**。证据归档位于 [`sse-lifecycle-capture-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/sse-lifecycle-capture-acceptance-20261030>)；`SHA256SUMS.sha256` 对 `SHA256SUMS` 的校验通过，且清单中全部归档文件均匹配。`acceptance.json` 记录的源脚本 SHA-256 为 `ee866efda1c7afca0bdb88200e482d36fa072ef356614bf6b5c3a8dbc0c9de6a`、测试文件为 `642c881d1dc1d381ebe55f08fefd67d3d15ba80d73f6d383210d276343c71d45`；runner SHA-256 为 `755e1f7bdc74bee716a412510062f1743bf15d836db117893375cceeb1307ff1`，source snapshot manifest SHA-256 为 `5d42c95a03d853dd0cb5c29e7b24a12ee56d65c78152ce1109e40b93178b172c`。这些源哈希由已校验的验收记录保存；本次未重新构建或执行采集器。

本 PR 没有发起真实 SSE 请求，也未验收真实字段、分页、市场范围或生命周期语义；数据库、REST API、scheduler 和全历史覆盖均未验收。中断的 reservation 与 page receipt 之间的结果仍为 **UNKNOWN**，raw receipts 也没有 commit record。该离线工具验收不代表上交所目录、采集完成或任何股票历史完整。

## 2026-10-30 OpenData PR #115：深交所生命周期采集工具隔离验收

OpenData [PR #115](https://github.com/cloudQuant/opendata/pull/115) 已合入 `dev`（`0c1fb8f324c49baa2f0204fe537815db5508ec9a`）。synthetic 隔离测试 **37 项通过**；目标采集脚本 statement+branch 综合覆盖率 **389/408 = 95.3431%**，**0 项排除**。证据归档位于 [`szse-lifecycle-capture-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/szse-lifecycle-capture-acceptance-20261030>)；`SHA256SUMS` 中全部归档文件均匹配。`source-hashes.json` 记录的源脚本 SHA-256 为 `c5b03b8726b7d6aecd4ea339cfde2d9058ea0617924c0a3ec29dd18c28d7de6f`、测试文件为 `4b035e0534c6a4bda087bfe3e380d7b008f21d7be9cce1f4e26f267274024e88`；source snapshot manifest SHA-256 `8ae8d14071749e400b203571acab154e65c998cdaa7b5e78536e0d688840e2bc` 同时由 `result.json` 与 `run-spec.json` 声明。底层 source snapshot manifest 未包含在归档中，因此该 manifest hash 不能从归档内独立重算。

本 PR 的 XLSX parser 使用 synthetic headers 进行离线验收，没有发起真实 SZSE 请求，也未验收真实文件字段、分页、市场范围或生命周期语义；数据库、REST API、scheduler 和全历史覆盖均未验收。该结果不证明深交所证券生命周期数据的权威性、完整性或可用于生产。

## 2026-10-30 OpenData PR #116：深交所采集限速等待修复

OpenData [PR #116](https://github.com/cloudQuant/opendata/pull/116) 已合入 `dev`（`c9a8e05ecc8ee30299cbd7ee87c76c19baf32b80`），修复深交所多 selector 采集时受每秒限速影响、后续请求可能在本地被拒绝的问题。synthetic 离线专项 **38 项测试通过**；目标采集脚本 statement+branch 合计覆盖 **390/409 = 95.3545%**，**0 项排除**。验收摘要位于 OpenData 本机私有证据 [`szse-lifecycle-rate-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/szse-lifecycle-rate-acceptance-20261030>)。

该修复尚未通过真实深交所来源运行验收，不能证明真实工作簿格式、字段、分页、市场范围或生命周期语义；数据库、REST API、scheduler 与全历史覆盖也未验收。上交所 status=3 采集路径与供应商接口路径存在差异，正在修复并待独立验收。权威全 A 股证券全集（含北交所及退市生命周期）和逐证券从实际上市起点至今的 head/interior/tail 全历史对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #117：真实交易所目录受限采样

OpenData [PR #117](https://github.com/cloudQuant/opendata/pull/117) 已合入 `dev`，提交为 `90a4825f5e462f3553acf85eed5a7180b411600c`。离线隔离专项 **39 项测试通过**；目标采集器 statement+branch 覆盖 **458/462 = 99.1342%**。以下真实来源观察用于验证受限传输和原始响应留存，不代表证券目录或历史数据已完整。

上交所采样共发起 **5 次请求并收到 5 页 HTTP 200**：当前主板 A 候选返回 **1,700 行**，科创板候选 **618 行**，status=3 主板候选 **145 行**、科创板候选 **3 行**。这里的数字只表示接口响应中的行数；status=3 是查询条件标签，尚未验证其退市/生命周期语义。分页是否完整、证券身份、来源真实性、市场覆盖和历史覆盖均为 **UNKNOWN**，没有据此发布或入库。匿名收据和摘要归档于 OpenData 本机私有目录 [`sse-live-canary-20261030-90a4825`](</home/yun/Documents/opendata/var/reports/afi204/sse-live-canary-20261030-90a4825>)。

深交所采样于 **2026-10-29** 发起 **3 次 GET**，均为 HTTP 200；累计响应 **559,707 字节**，3 份原始来源文件均已私有保存。现有解析器按 synthetic sheet/header 契约处理真实文件时以 `sheet_unsupported` 失败，解析 **0 行**；真实文件格式尚未适配。采集器配置为 **45 秒协作式任务期限**；执行者通过外层 **90 秒 timeout** 启动，但匿名收据未记录外层期限，因此该期限不能由收据独立证明。记录只证明有界请求和原始响应留存，不代表完整目录、完整生命周期数据或已解析数据。匿名收据和摘要归档于 OpenData 本机私有目录 [`szse-lifecycle-live-20261029T211056Z-752c1a37e64836fa`](</home/yun/Documents/opendata/var/reports/afi204/szse-lifecycle-live-20261029T211056Z-752c1a37e64836fa>)。

两次采样均未证明分页完整、证券身份映射、全市场覆盖或逐证券全历史 head/interior/tail；也未完成数据库、REST API、定时调度或生产接线验收。真实采样不能关闭全 A 股权威证券全集与完整历史恢复事项，迭代204整体继续开放。

## 2026-10-30 OpenData PR #118：深交所真实表头解析器离线验收

OpenData [PR #118](https://github.com/cloudQuant/opendata/pull/118) 已合入 `dev`（`56837681ef9a6dfd44370c0fa3bc3432dcd5422d`）。本次隔离验收共 **117 项 synthetic 测试通过**；采集器 statement+branch 覆盖率 **430/462 = 93.0736%**，解析器覆盖率 **877/916 = 95.7424%**，两项均 **0 项排除**。验收证据归档于 OpenData 本机私有目录 [`szse-real-header-combined-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/szse-real-header-combined-acceptance-20261030>)；此前 r6 失败证据保留。

深交所真实文件回放仍在准备中；本次结果不表示真实文件已成功解析，也未证明真实字段、证券身份、分页、市场范围或生命周期语义。数据库、REST API、scheduler、生产接线和逐证券全历史覆盖均未验收，迭代204整体继续开放。

## 2026-10-30 深交所真实文件离线回放补记

在 PR #118 合入后，对此前真实深交所采样保存的三份工作簿进行离线回放。此前 live capture 使用旧解析器时因真实工作表/表头不匹配而失败，未能解析；本次是对已保存文件用新解析器离线处理，不是再次访问深交所。`current_a`、`suspended`、`terminated` 三个 selector 的结果 `count` 分别为 **2,905、0、212**，均表示对应工作表表头后的 XML `row` 元素计数，不表示证券数、非证券数、有效业务记录数或解析记录数。`suspended=0` 只表示本次文件对应工作表没有表头后的 XML `row` 元素，不能证明不存在停牌证券。结果文件位于 OpenData 本机私有目录 [`results.json`](</home/yun/Documents/opendata/var/reports/afi204/szse-offline-real-replay-56837681-20261030/results.json>)。

同目录的 [`EXECUTION.md`](</home/yun/Documents/opendata/var/reports/afi204/szse-offline-real-replay-56837681-20261030/EXECUTION.md>) 记录了 pins 和实际执行命令，但该记录未签名，且 `results.json` 未内嵌 pins，因此无法独立证明执行者、命令、固定源码与结果之间的绑定。三个 selector 的来源身份、生命周期语义、市场范围与来源完整性均为 **UNKNOWN**。这些 XML 行元素计数不能证明权威目录、分页/市场完整性、有效证券总数或全 A 股生命周期覆盖。此次离线回放未写数据库、发布 REST API 或运行 scheduler；逐证券从实际上市起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #119：有界表单 POST HTTP 客户端

OpenData [PR #119](https://github.com/cloudQuant/opendata/pull/119) 已合入 `dev`，提交为 `7abec32939175541700b932f13d819f0e0d00723`。本切片支持受限的单次表单 POST 传输路径；冻结源码上的离线 synthetic 专项 **216 项测试通过**，目标 `opendata/data/http_client.py` statement+branch 综合覆盖为 **1,259/1,393（90.3805%）**，排除 **0 行、0 个分支**。验收摘要位于 OpenData 本机私有证据 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/bounded-form-post-acceptance-20261030/README.md>)；摘要 SHA-256 为 `ece1d2ec81cc04e8286529063fd0e978f1b2c9244df2b3ed8056083aaaed0dee`。

验收过程中的失败证据均保留：r1 有 **140 项通过、13 项失败**，原因是 Fetcher scope 与请求 source 不一致；r2 有 **153 项通过**，但目标模块覆盖仅 **1,179/1,389（84.8812%）**，未达到 90% 门槛。修正覆盖统计选择器后，r3 才达到上述接受结果；r2 对全仓宽范围产生的 **1.9954%** 聚合值不作为目标模块覆盖结论。

本次只验收离线传输合同和回归，不曾真实请求北交所（BSE）来源，也未证明 BSE 市场目录、证券身份、生命周期、数据质量或历史完整性。生产数据库、部署、生产运维、REST API 和定时任务未验收；全 A 股权威全集及逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #120：北交所单页目录采集器离线验收

OpenData [PR #120](https://github.com/cloudQuant/opendata/pull/120) 已合入 `dev`（`3b18e1f4221c40254be0233b85600ea5a4d3ce85`）。synthetic 离线专项 **20 项测试通过**；目标采集脚本 statement+branch 综合覆盖率为 **249/275 = 90.5455%**，排除 **0 行、0 个分支**。验收证据位于 OpenData 本机私有目录 [`bse-single-page-capture-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/bse-single-page-capture-acceptance-20261030>)。

随后启动一次 BSE POST canary。本机未签名匿名回执报告一次本地 attempt 预留，`http_status=null`、`request_failed_or_outcome_unknown`；这不能证明请求实际发出或抵达源站。没有保存原始响应，响应未解析，且没有重试。回执归档位于 OpenData 本机私有目录 [`bse-live-canary-3b18e1f4-once`](</home/yun/Documents/opendata/var/reports/afi204/bse-live-canary-3b18e1f4-once>)。该结果不能用于断定来源故障。市场完整性、分页、证券身份、字段语义及历史覆盖均未建立；数据库写入、发布、定时采集也均未执行。北交所目录与生命周期仍未验收，全 A 股权威全集及逐证券从实际起点至今的 head/interior/tail 对账仍开放，迭代204整体继续开放。

## 2026-10-30 OpenData PR #121：北交所单页重定向诊断

OpenData [PR #121](https://github.com/cloudQuant/opendata/pull/121) 已合入 `dev`（`8638f40ee4c22e8110884a285336d8c7fe520bf2`）。synthetic 离线专项 **27 项测试通过**；目标采集脚本 statement+branch 综合覆盖率 **296/326 = 90.7975%**，排除 **0 行、0 个分支**。证据位于 OpenData 本机私有目录 [`bse-capture-diagnostics-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/bse-capture-diagnostics-acceptance-20261030>)。

随后一次 BSE 单页诊断的本机 receipt 记录 HTTP **307**，分类为重定向；客户端没有跟随重定向，也没有保存原始响应正文，未取得或解析北交所股票名录。receipt 位于 [`bse-live-canary-8638f40e-diagnostics-once`](</home/yun/Documents/opendata/var/reports/afi204/bse-live-canary-8638f40e-diagnostics-once>)。reviewer 事后报告核对了 receipt、stdout 与 request 摘要的一致性，以及一次 reservation/attempt 和发送上限为 1；但来源端点身份和响应来源未独立认证。reviewer 事后报告静态复核了 SHA 前缀为 `bdd0abff` 的 launcher，并称其与此前 SHA 前缀 `54349` 的审查版本只有三处静态审计 metadata 差异、请求行为未变；这项差异归因来自事后审查报告，旧审查版本和独立审查 artifact 未归档，本文无法独立复验该比较。reviewer 报告相关证据归档存在且校验通过，但运行 receipt 的 launcher SHA 仍来自 sidecar 自行声明；没有签名或独立执行证明可将该值与实际运行文件绑定，因此运行版本关联仍未获独立证明。

该次 307 诊断不能证明来源返回了可用目录，也不能据此判断来源故障。市场范围、分页、证券身份及上市/退市生命周期仍未知，逐证券从实际起点至今的 head/interior/tail 历史完整性未验收。数据库、REST 发布与定时采集也未由此验收；全 A 股权威全集和迭代204整体仍开放。

## 2026-10-30 AFI PR #177：Sina FZB raw-only reader 与跨仓桥接

AFI [PR #177](https://github.com/cloudQuant/ai-for-investor/pull/177) 已合入 `dev`，提交为 `ed507135d45c2d4bba2073e6d8813687a87deea0`。本切片固定 publication 与 capture 的单一 SH/SZ Sina FZB raw-only reader。离线专项测试报告 **67 项通过**；跨仓验收执行者报告称，通过真实 `published_data` router 的 `ASGITransport` 路径，使用合成 SQLite 数据和 synthetic principal，以 **2 页、31 条记录**完成桥接。该桥接使用 OpenData 基线 `8638f40ee4c22e8110884a285336d8c7fe520bf2`，并覆盖当时 worktree 中 SHA-256 为 `16f645a883f955fddd1063f09535a46ae78a741b7ba13ec760c7de70013e893b` 的 `published_data` router；该 router 后续随 OpenData [PR #122](https://github.com/cloudQuant/opendata/pull/122) 合入 `dev`，提交为 `75bb3d49`。证据摘要位于 AFI 本机私有目录 [`README.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/sina-reader-bridge-acceptance-20261030/README.md>)。

以上运行结果由执行者报告；完整 stdout、bridge result、stderr、JUnit 和退出码未留存，因而不能从持久日志独立复核。桥接使用 synthetic 数据和 principal，未验证真实 API key、生产数据库或部署。reader 尚未接入业务消费、自动发现或定时调度；北交所未覆盖，三表全历史恢复仍未完成。OpenData API hardening 已随 PR #122 合入，但全 OpenAPI gate 在同一环境仍有既有失败，不能记作通过。全 A 股权威证券全集及逐证券从实际起点至今的 head/interior/tail 对账继续开放，迭代204整体仍未完成。

## 2026-10-30 OpenData PR #122：Sina FZB 发布 API 合同加固

OpenData [PR #122](https://github.com/cloudQuant/opendata/pull/122) 已合入 `dev`，合并提交为 `75bb3d49fd101b9e48c698f63242deb6f250de81`。本切片将 Sina FZB 固定到数据集 `sina_fzb_report_observations`，要求调用方指定 publication、六位证券代码和 capture；证券选择器只接受 `NNNNNN.SH` 或 `NNNNNN.SZ`，不包含北交所。AFI 单次 capture 读取合同先向 `POST /api/v2/snapshots` 提交精确的 dataset/publication/instrument/capture 选择，再以固定 `snapshot_id` 和 cursor 从 `/api/v2/datasets/{dataset_id}/records` 分页读取；返回的是 OpenData source-native 投影，不执行数值转换。自动 capture discovery endpoint `/api/v2/datasets/{dataset_id}/capture-candidates` 保持硬关闭，当前请求会在授权和 store 查询前返回 404；没有“latest”自动发现回退。

冻结的离线 R3 专项结果为 **129 passed、1 failed**；目标 `opendata/api/published_data.py` 的 statement+branch 覆盖为 **1,030/1,164（88.488%），0 项排除**。该模块数字是目标覆盖率；API 目录合计覆盖为 37.066%，不作为此模块结果。唯一失败是 OpenAPI contract gate，诊断涉及 v1 pipeline 参数合同值变化及 v2 对 `#/$defs/Exchange` 的不支持引用。相同冻结环境在 base-dev 上复现了同一 OpenAPI gate failure；完整测试套件没有通过。按用户要求，CI/OpenAPI 问题暂缓处理，但此结果不记为 CI 或完整套件通过。验收使用临时 SQLite 和离线测试环境；Python 3.13.5、pytest 8.3.4，运行依赖未完全锁定。证据见 OpenData 私有归档 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/sina-published-api-hardening-acceptance-20261030/README.md>)。

该 PR 只验收上述 API 代码切片及定向离线回归；未验证真实 API key、真实供应商响应、生产数据库、部署或自动调度。capture discovery 仍关闭，Sina FZB reader 尚未接入业务消费；SH/SZ 选择器不意味着全 A 股范围，北交所、权威证券全集及逐证券从实际起点至今的 head/interior/tail 覆盖仍未验收。迭代204整体继续开放。

## 2026-10-30 AFI PR #179：Sina 显式 selector 业务接入

AFI [PR #179](https://github.com/cloudQuant/ai-for-investor/pull/179) 已合入 `dev`，提交为 `2879e17eeaeea8bc0e90b0ec00e31be9f483f34a`。Sina snapshot/provenance 接入默认关闭，消费路径要求显式 selector；原始行不进入 score、LLM 或报告输入。开关启用时，缺少 selector 的旧 A 股请求会得到空的财务输入，不回退到旧来源。已登录用户可在 stock-analysis task 请求中提交固定数据集 selector 创建任务；AFI 没有额外的角色授权或 dataset 授权检查，OpenData 侧的真实授权也未验收。

执行者报告的 **102 项 mock 测试**没有保留完整日志，故不作为可独立复核的验收结果。归档日志记录两个测试文件共 **13 项通过**，其中 **1 项**覆盖 HTTP/SQLite/login/owner roundtrip；pytest 日志和快照清单见 AFI 本机私有证据 [`README.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/sina-manual-business-acceptance-20261030/README.md>)。manifest pins 表明 **5 个生产文件未变**；哈希比对显示 route test 文件仅有末尾两个 LF 的差异。执行者报告称这两个 LF 在运行后被删除；该时序来自未签名的本机记录，不能作为签名执行证明。

这组测试没有使用真实 OpenData key、真实服务或生产环境；AFI 提交任务的能力不证明 OpenData 真实授权配置或生产访问控制已验收。自动 capture 清单、北交所、Sina 三表接入及逐证券从实际起点至今的全历史仍未验收；完整生产部署和迭代204整体继续开放。

## 2026-10-30 OpenData PR #123：Sina LRB 单页原始采集与受限来源采样

OpenData [PR #123](https://github.com/cloudQuant/opendata/pull/123) 已合入 `dev`，提交为 `0766b658693df6d9c1177bcc6d6cfe5a303b9670`。本切片新增固定 `600519.SH` 的新浪 LRB（利润表）单页原始采集器，只保存来源响应原始字节；未解析、清洗、入库或发布利润表数据。冻结采集器的离线专项 **17 项测试通过**，目标覆盖率 **87.17%**，**0 项排除**。

随后针对 `600519.SH` 执行了一次真实来源采样，收到 HTTP **200**，响应大小 **2,002,959 字节**。采样回执位于 OpenData 本机私有目录 [`receipt.json`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-live-600519.SH-20261030T002422Z-3143030/receipt.json>)。该单次响应尚未证明来源真实性、报表身份、分页完整性或历史覆盖；固定单证券、单页采样不能证明全 A 股覆盖，也不能代表全市场或完整历史采集。

在 PR #123 合入及上述采样时，LRB 解析、数据质量校验、数据库存储、REST API 发布、定时任务及 AFI 消费接线尚未实现或验收；后续 parser 与单样本离线重放进展见下节。Sina 资产负债表（FZB）与利润表（LRB）的合同和解析不能互相替代。权威全 A 股证券全集（含北交所及退市生命周期）及逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #124：Sina LRB 原始结构解析器与样本离线重放

OpenData [PR #124](https://github.com/cloudQuant/opendata/pull/124) 已合入 `dev`，提交为 `97cc9e8a37db2027c81a295a16ce284022978294`。本切片新增独立的 Sina LRB 原始结构 parser，不复用 FZB 解析合同。冻结代码的隔离专项 **19 项测试通过**；目标覆盖率为 **280/298（93.96%）**，**0 项排除**。验收证据位于 OpenData 本机私有目录 [`sina-lrb-parser-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-parser-acceptance-20261030>)。

对 PR #123 保存的 `600519.SH` 单股票、单页真实响应进行了离线重放，parser 输出 **103 条报表、7,931 项数据**；重放结果位于 [`replay.json`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-parser-replay-acceptance-20261030/output/replay.json>)。这只证明该样本在当前 parser 下可解析，不证明来源真实性、报表身份、财务字段与数值语义、分页或数据完整性，也不能外推为全市场或全历史覆盖。parser 的内存上限不是进程 RSS 上限，运行环境依赖也未以哈希锁定。

本 PR 未验收财务语义及质量规则，未接入数据库写入、REST API 发布、定时调度或 AFI 消费。权威全 A 股证券全集（含北交所及退市生命周期）和逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 AFI PR #183：Sina FZB 快照失败的安全提示

AFI [PR #183](https://github.com/cloudQuant/ai-for-investor/pull/183) 已合入 `dev`，合并提交为 `f6194d4c826b71a7a0021d96baad946a96c09345`。显式选择 Sina FZB OpenData snapshot 后，若读取不可用，任务的数据质量说明会给出固定错误码及安全提示；未知错误会映射到通用提示，不把异常内容、凭据、URL 或响应正文带入任务结果。显式 selector 失败不会回退到 AkShare。隔离 mock 专项 **18 项测试通过**；验收摘要位于 AFI 本机私有证据 [`README.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/sina-error-visibility-acceptance-20261030/README.md>)。归档 pytest 日志已脱敏；测试依赖未锁定，记录保留了原始临时日志哈希，但归档副本无法重建其原始字节。

该结果只证明 mock 下的错误显示与脱敏行为；没有验收真实 OpenData API key、实际授权、生产连接或部署行为。自动 discovery 仍关闭，真实 FZB 数据质量、数据库发布、调度运行、全 A 股及逐证券全历史覆盖仍未验收，迭代204整体继续开放。

## 2026-10-30 OpenData PR #125：上交所与扶摇证券候选目录对账

OpenData [PR #125](https://github.com/cloudQuant/opendata/pull/125) 已合入 `dev`，提交为 `fc8a88f18d8762f52324e3476445a33a8d92aeec`。本切片为 SSE 与 Fuyao 候选来源增加目录对账逻辑，显式保留来源间重复冲突并限制对比计算量；当来源分页情况未知时，不将记录缺席解释为证券不存在，也不将已取得的候选记录称为完整目录。synthetic 隔离专项 **125 项测试通过**；目标代码覆盖率为 **1,074/1,078（99.63%）**，**0 项排除**。验收证据归档于 OpenData 本机私有目录 [`instrument-catalog-reconciliation-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/instrument-catalog-reconciliation-acceptance-20261030>)。

该结果只验收 synthetic 输入下的对账行为；未包含 SZSE 或 BSE，未融合真实来源响应，也未证明权威证券全集、市场/生命周期完整性或分页完整性。尚未接入运行调度。验收环境的 Anaconda 依赖未完全 pin。全 A 股权威证券全集（含北交所及退市生命周期）及逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #126：运行时、静态目录与迁移候选对账

OpenData [PR #126](https://github.com/cloudQuant/opendata/pull/126) 已合入 `dev`，提交为 `1afef33f515db8fa9a14dd346e24c98a3b01e687`。本切片对既有运行时 inventory 与静态脚本/provider catalog 做离线候选对账，并保留证据不完整、来源未知及部分匹配等状态，避免把静态发现直接当作已验证的运行时任务或可迁移结论。隔离 synthetic 专项 **84 项测试通过**；目标模块 statement+branch 覆盖为 **743/779（95.3787%）**，**0 项排除**。验收证据位于 OpenData 本机私有目录 [`migration-host-reconciliation-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/migration-host-reconciliation-acceptance-20261030>)。

此验收使用合成清单与固定源码快照；没有刷新真实运行时 inventory，也没有验证生产 writer、真实数据库行为或切换 scheduler。运行依赖虽记录了 Python/pytest 等版本，但未以哈希锁定。候选归属及来源证据仍有 **UNKNOWN/PARTIAL** 项，迁移计划仍为 **BOUNDED/BLOCKED**；此切片没有解除运行时来源、当前配置和生产写入验证等阻塞，也不证明任何任务已迁移或切换到 OpenData。全 A 股权威证券全集、北交所与退市生命周期，以及逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #127：Sina LRB source-native publication 与受限 snapshot API

OpenData [PR #127](https://github.com/cloudQuant/opendata/pull/127) 已合入 `dev`，提交为 `1a605ce623802451ab4390b70fbe5dbb32739d8a`。本切片为 Sina LRB 增加独立于 FZB 的 source-native publication 合同、受限单标的处理 process/job，以及基于固定 capture 的 snapshot REST API；API 桥接以合成临时 SQLite 和 synthetic principal 经真实 publisher/router 完成分页读取。R12 冻结验收输出保存在 OpenData 本机 [`output`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-publication-api-process-acceptance-20261030-r12-final/output>) 目录：隔离专项共 **248 项通过**（28 项 capture API、1 项 bridge、74 项 published-data API、145 项 LRB parser/publication/process/job）；五个目标模块的 statement+branch 覆盖率分别为 API **89.06%**、parser **93.96%**、process **98.30%**、publication **95.76%**、job **98.77%**，排除 **0 项**。其中一项既有 OpenAPI success/error payload gate 被明确 deselect，不计入通过数，也不宣称 OpenAPI gate 或全仓 CI 通过。新增 3 个模块的定向 mypy 检查通过；完整依赖跟随检查仍报告 4 项既有诊断。验收摘要及文件校验见 OpenData 私有归档 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-vertical-acceptance-20261030/README.md>)。

该 job 当前保持 **disabled、unreviewed、unscheduled、unregistered**，未触发真实来源请求或持久化任务注册。此次桥接仅使用合成数据、临时 SQLite 与 synthetic principal；真实 API key/授权、生产数据库、生产部署、持久化原始数据、实际排程、AFI 对接、北交所、全市场证券全集及逐证券完整历史均未验收。分页 snapshot API 的存在和这组离线覆盖率不能证明上述生产能力或数据完整性；迭代204整体仍未完成。

## 2026-10-30 AFI PR #188：Sina LRB snapshot 消费接线

AFI [PR #188](https://github.com/cloudQuant/ai-for-investor/pull/188) 已合入 `dev`，合并提交为 `751712297f8ac850a593e3785637d07a2b71b0f8`。本切片增加默认关闭的 Sina LRB snapshot 消费路径，沿用 OpenData 固定 publication/capture 选择及 source-native 记录；reader 对每条记录的哈希进行独立重算和核验。R18 隔离验收为 **107 项离线测试及 2 项 API route 测试通过**。离线组覆盖 LRB reader/integration 与 FZB、collector 回归；route 组使用临时 SQLite 和测试身份，拦截 worker 执行，不调用真实来源。验收证据及运行边界见 AFI 本机私有归档 [`README.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/sina-lrb-consumer-acceptance-20261030/README.md>)。

OpenData 返回值不包含计算 `content_sha256` 所需的 `access_scope`，因此 AFI 无法独立重算并验证内容根；该值仅能作为服务端回显，不能记为客户端验证通过。此次未使用真实凭证或 OpenData 授权，也未验收全历史完整性、细粒度用户证券 ACL、真实服务或生产部署。功能保持默认关闭；全 A 股权威证券全集、逐证券从实际起点至今的 head/interior/tail 对账及迭代204整体仍未完成。

## 2026-10-30 OpenData PR #128：Sina LRB raw capture 接入发布流程

OpenData [PR #128](https://github.com/cloudQuant/opendata/pull/128) 已合入 `dev`，合并提交为 `529ec06b0efe9df9d9e5c53c8ad60c1a5852ec18`。R17 冻结验收专项 **295 项测试通过**；一项既有 OpenAPI gate 被明确跳过，不计入通过数，也不表示该 gate 或全仓 CI 通过。raw capture 目标覆盖率为 **99.13%**。验收证据归档于 OpenData 本机私有目录 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-raw-integrated-r17-acceptance-20261030/README.md>)。

该 job 仍为 **disabled、unreviewed、unscheduled**，没有生产任务注册。来源授权状态来自用户声明，未在本次验收中独立核验供应商合同或技术授权。实现尚无持久化 capture journal、崩溃恢复或跨运行 quota 控制；查询摘要覆盖固定的五个查询参数，不是完整 HTTP 请求指纹。该切片验收不构成真实全市场或全历史数据覆盖证明：全 A 股权威证券全集、北交所及生命周期范围，以及逐证券从实际起点至今的 head/interior/tail 对账仍未完成，迭代204整体继续开放。

## 2026-10-30 OpenData PR #129：CSI500 指数单次手工回补

OpenData [PR #129](https://github.com/cloudQuant/opendata/pull/129) 已合入 `dev`，合并提交为 `775045ac5e408157235fee57bb9224bcfff4e8b2`。本切片针对 `000905.SH`（CSI500 价格指数），提供单次手工回补入口，单次请求跨度最长 **3,650 天**。任务在事务中核对 grant 与 expected reference 后才允许请求；来源授权依据仍为用户声明，未独立验证。重复的 V1 scope 不保存授权 reference，因此不能据此授权重发；V2 遇到非空 reference 会拒绝执行。

R11 冻结验收为 **949 passed、7 个 e2e deselected、7 warnings**。八个变更的 data/pipeline 模块合并 statement+branch 覆盖率为 **92.18%**，均达到 ≥90%，排除 **0**。Ruff 与 Bandit 检查通过；完整 follow mypy 报告 **3 个既有错误**。验收证据位于 OpenData 本机私有归档 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/csi500-manual-backfill-acceptance-r11-20261030/README.md>)。该隔离验收未访问真实网络或供应商。

单次最长窗口不代表指数全部历史；来源最早可用日期和实际历史覆盖仍未知。该入口未注册生产调度。跨运行的累计请求量及并发控制状态也未知，因此不能据此认定全历史回补已完成或任务已具备长期自动运行条件。

## 2026-10-30 OpenData PR #130：深交所生命周期工作簿离线聚合

OpenData [PR #130](https://github.com/cloudQuant/opendata/pull/130) 已合入 `dev`，合并提交为 `ed2f6f5005e2b69487cdc574c66cd669f9913bd9`。本切片仅实现三类离线工作簿聚合，不连接真实来源。R3 冻结验收的 synthetic XLSX 专项 **125 项测试通过**；生产适配器分支覆盖率为 **90.79%**，排除 **0 行、0 个分支**。Ruff、Bandit 与 strict mypy skip 检查通过；完整 follow mypy 仍有 **4 项既有相关依赖诊断**。验收证据见 OpenData 本机私有归档 [`ACCEPTANCE.md`](</home/yun/Documents/opendata/var/reports/afi204/szse-lifecycle-census-acceptance-r3-20261030/ACCEPTANCE.md>)。

这只是合成 XLSX 下的离线结构验收；来源身份、生命周期语义、分页、市场全集与历史覆盖均为 **UNKNOWN**，未验证真实授权、工作簿完整性或生命周期正确性。该结果不能视为全 A 股市场目录或历史数据完成，迭代204整体仍开放。

## 2026-10-30 OpenData PR #131：Sina LRB 财报字段与报告期映射

OpenData [PR #131](https://github.com/cloudQuant/opendata/pull/131) 已合入 `dev`，合并提交为 `4f0aa7c7c29fcf176eb25fdf6bdc01a626fac4af`。此切片增加保守的字段/期间映射评估：字段只按精确来源键与标题匹配，不做单位或数值换算；报告期只接受显式、带时效的映射声明，并只报告符合条件的精确期间观测。R4 隔离验收专项 **59 项测试通过**；目标映射模块 statement+branch 综合覆盖率 **96.09%**，排除 **0 行、0 个分支**。Ruff、针对性 mypy 与 Bandit 检查通过。验收使用禁网隔离环境、合成输入和 testing 配置，没有访问真实数据源或生产数据库。证据见 OpenData 本机私有归档 [`README.md`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-financial-mapping-acceptance-r4-20261030/README.md>)。

字段映射、期间语义、证券身份 crosswalk、证据引用及隔离状态均由 caller 提供，验收只检查形状、冲突和时点规则，未独立核对其事实或来源。评估会排除晚于 `as_of` 的映射证据；晚于 `as_of` 的报告期按 `Asia/Shanghai` 日期判为不可评估，留在 unknown 计数中。该时点规则由合成测试验证，不构成对真实历史数据无未来信息污染的证明。映射声明不证明财报项目语义、报告完整性、公告时点、修订版本链或 point-in-time 可用性；本切片不提供完整历史覆盖结论，也未接入生产调度或生产消费。迭代204仍开放。

## 2026-10-30 AFI PR #193：snapshot 授权策略

AFI [PR #193](https://github.com/cloudQuant/ai-for-investor/pull/193) 已合入 `dev`，合并提交为 `0fba790a4c7b0d02448056475eae1bc2908173c8`。R2 冻结专项 **69 项测试通过**，Ruff 与格式检查通过；证据见 AFI 本机私有归档 [`manifest.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/snapshot-authorization-policy-acceptance-r2-20261030/manifest.md>)。此次仅实现纯授权策略，限定 SH/SZ 并拒绝 BJ；尚未接入真实用户 grant 与来源 registry 信任、MAC、数据库签发/撤销、route/task 运行或保存后重验，因此不构成真实数据授权或生产访问控制验收。**2026-10-31 更正**：持久化存储已由 AFI #201 合入（仍不含可信 adapter、route/task 或真实授权），见下文 #201 条目。

## 2026-10-30 OpenData PR #132：Sina LRB raw capture 签名恢复日志

OpenData [PR #132](https://github.com/cloudQuant/opendata/pull/132) 已合入 `dev`，合并提交为 `1bbc85bd4559634bb24ba2a6894f339efa136b97`。R5 冻结验收共 **487 项通过**（384 + 28 + 1 + 74），其中 **1 项既有 OpenAPI 检查明确 deselect**，不计为通过；各目标模块覆盖率为 **92%–97.41%**，目标模块合并覆盖率 **93.28%**，API 覆盖率 **89.06%**，排除 **0 项**。完整 follow mypy 仍有 **3 条既有诊断未通过**，不记为通过。验收记录和失败尝试证据保存在 OpenData 本机私有目录 [`sina-lrb-recovery-r5-acceptance-20261030`](</home/yun/Documents/opendata/var/reports/afi204/sina-lrb-recovery-r5-acceptance-20261030>)；R2、R3、R4 失败记录均保留，最终验收结论仅对应 R5。

该切片增加签名事件验证和私有持久化恢复日志，但任务仍为 **disabled、unregistered**，没有 scheduler；账本和进程内任务依赖可信运行环境，尚未验证生产部署，也没有生产签名器、密钥生命周期或真实来源/历史完整性验收。日志不能自动恢复所有孤儿状态，ledger 提交与日志发布之间也没有原子链接。因此该实现不证明生产环境可自动恢复、全 A 股数据已采集，或逐证券全历史完整。

## 配额 V3 未合入：保留位置与切换阻断

OpenData 配额 V3 尚未合入 `dev`，也未通过生产验收。未提交实现的完整私有备份保存在 [`/home/yun/.local/share/opendata-v3-quota-full-backup-20261030-fv5ljr3d`](</home/yun/.local/share/opendata-v3-quota-full-backup-20261030-fv5ljr3d>)，已独立校验；30 个文件已从 OpenData 主工作区清除。该备份不含密钥。R2–R4 失败记录与配额 V3 是不同工作项；前者的失败证据分别保留在 OpenData 的 R2、R3、R4 本机归档中。

配额 V3 暂缓合入的主要原因是混跑切换尚未被安全证明：迁移后仍可能有 V2 worker 或已提交 permit 绕过 V3 lease/每日额度；目前没有可信控制面证据证明旧 worker 与在途 permit 已停止或排空，也没有针对旧进程网络或凭证的可信 fence。人工声明不足以作为切换门槛，必须有可验证的停机/排空证明，并确保 V3 在没有可信 verifier 时默认不可启用，同时保留既有 V2 工作路径。另有 THS HTTP 客户端绕过 gate 的风险需要在请求发送前 fail closed，lease 释放持久化也需专项验收。上述问题解决并完成隔离测试、独立审查前，配额 V3 不进入 `dev` 或生产启用。

## 2026-10-30 OpenData PR #133：CSI500 历史覆盖对账

OpenData [PR #133](https://github.com/cloudQuant/opendata/pull/133) 已合入 `dev`，提交为 `cc79654171bd00b00d9909f7973547a10790a945`。R4 冻结隔离验收 **68 项测试通过**；目标模块 statement+branch 综合覆盖率为 **96.77%**，排除 **0 行、0 个分支**；Ruff、mypy 与 Bandit 检查通过。R3 的 coverage gate 失败记录仍保留在独立归档中，不以 R4 结果覆盖。验收证据位于 OpenData 本机私有目录 [`RUN_STATUS.md`](</home/yun/Documents/opendata/var/reports/afi204/csi500-history-reconciliation-r4-runner-pass-20261030/RUN_STATUS.md>)。

对账模型将有独立证据的证券起始边界与来源当前最早观测分开记录，并且只评估到本次请求的 `request_end`。日历、来源权限及来源保留范围是调用方提交的输入声明，未在本次验收中认证。测试使用合成数据，不证明真实 CSI500 来源真实性、实际全历史完整性、交易日历正确性、来源分页或保留范围；该功能也未接入生产调度或生产数据库。因此本 PR 不构成真实历史已从起点补齐的证明，迭代204整体仍开放。

## 2026-10-30 Asia/Shanghai 主机采集状态只读快照

本节记录本次只读主机清点的时间快照，不代表当前实时状态。将 2026-10-26 的脚本 CSV 与本机现存文件比较，在 `data_fetch` 子树范围内得到 **1,066 行**：**1,057 个文件仍存在、1,013 个哈希相同、44 个内容已变更、9 个文件缺失、0 个新增文件**。这只是指定子树与该份 CSV 的文件比对，不是全量运行任务清单，也不能据此判断数据覆盖或任务迁移完整性。数据库 registry 本次未读取；**1,103** 仍是历史快照数字，不是当前数据库实测结果。

本次观察到 **6 个用户级 timer 处于 active/waiting 状态，但关联 service 均为 failed**。`full-history-recovery` 每分钟触发并以 exit 2 结束，原因是预期的 `run_full_history_recovery_worker.py` 不存在；`policy-expiry-watchdog` 以 exit 2 结束，预期脚本缺失。`dce-browser`、`dce-option`、`stock-tail` 处于 203 EXEC 状态，目标脚本缺失。`stock-amount` 以 exit 2 结束且目标缺失，但现有证据不足以确认完整因果。后端和 4 个 ETF 回补服务显示 active 只说明进程状态，不证明采集完整、历史无缺口或结果已发布。

清点期间未停止或重启服务。迁移前不能猜测替代脚本目标，也不能启用新的采集任务；应先核实现行任务定义、目标入口及其授权，再安排受控迁移和数据对账。

## 2026-10-30 至 2026-10-31 OpenData PR #134–#149：一次性来源门禁、离线对账与受门禁的日线读取

以下条目截至 2026-10-31（Asia/Shanghai），按两仓 `dev` 的实际合入提交整理，不包含任一工作树的未提交改动。OpenData 本批全部提交只证明各自声明的代码/离线范围：没有真实 THS/Fuyao 请求、生产调度、自然周期或全历史覆盖证据。除特别注明外，提交信息与仓库文档均未记录本次运行的测试通过数或覆盖率，本节不补造这些数字；本文件更新时也未运行测试或采集。

### OpenData PR #134–#143：durable one-shot gate 与 CSI500 隔离准备

- [PR #134](https://github.com/cloudQuant/opendata/pull/134)（`50078e7a549d78ba8e804e76069c0314c36e6758`）：仅新增一次性样本门禁设计文档，无运行代码。
- [PR #135](https://github.com/cloudQuant/opendata/pull/135)（`cf535ef84ecb45872819488106b38b3df29e9122`）：source attempt 绑定 v3 请求 scope，新增 `sg0003` 迁移。
- [PR #136](https://github.com/cloudQuant/opendata/pull/136)（`ea3cb1c46824df3203f59d80c98ef9af48636d34`）：durable one-shot gate 与 `sg0004` 迁移；证据限于隔离测试，未验证生产数据库或跨主机并发。
- [PR #137](https://github.com/cloudQuant/opendata/pull/137)（`83d39f2cd9dc11c4943db39cacaf8d8e47d7a7dd`）、[#138](https://github.com/cloudQuant/opendata/pull/138)（`92f462c8615a25d269096ce5de15366d54e1f2bf`）、[#139](https://github.com/cloudQuant/opendata/pull/139)（`30de20cc3a497f93f3271bfbcb914c6c1b650456`）：THS 请求/transport 绑定 v3 scope，reservation 必须持有已锁定的 one-shot gate，并加入一次性 transport 边界。它们没有发送真实请求，也没有创建生产授权。
- [PR #140](https://github.com/cloudQuant/opendata/pull/140)（`03945282522139708aa8639a794b5bc19c4c82f0`）：一次性 source quota provisioning；证据限于隔离测试，不是跨运行持久额度或供应商配额证明。
- [PR #141](https://github.com/cloudQuant/opendata/pull/141)（`d9e776bf542f603a7f05234992383d8bef1651f4`）、[#142](https://github.com/cloudQuant/opendata/pull/142)（`87cf9d2d0e29c756414a5fdd5b4bebe4b00ca08f`）：仅新增离线 CSI500 请求预览，并将 CSI500 单日样本绑定到 one-shot gate；不执行候选、不请求 Fuyao。
- [PR #143](https://github.com/cloudQuant/opendata/pull/143)（内容提交 `be6b87b77c4d85629a4654b3d8be72a4589ab78f`，合并 `942eb6440626192eee41b6eb0d2921223302aa0a`）：允许初始化空的独立 source-gate schema；仍要求空库前置条件，不代表 warehouse 迁移或采集完成。

### OpenData PR #144：隔离的 CSI500 source-gate 样本准备

[PR #144](https://github.com/cloudQuant/opendata/pull/144) 已合入 `dev`，提交为 `1108a26aeaeb6f00e1af6e2306b4f92a835aeb71`。新增 `opendata/pipeline/ths_csi500_sample_composition.py`、`scripts/ops/run_csi500_one_shot_sample.py` 与运维文档。CLI 仅提供 `init`、`migrate`、`authorize`、`prepare`、`preview`：只操作程序新建的隔离 SQLite target，只应用 source-gate schema 并显式保持 `warehouse_schema_status=NOT_APPLIED`；本地 grant 标记为 `USER_DECLARED_UNVERIFIED`，候选固定为 `000905.SH` 单个交易日、transport/attempt 上限均为 1，manifest 中的 `CANDIDATE_NOT_LOCKED` 不是 gate receipt。

该 PR 不提供 preflight、submit、execute、verify 或 cleanup，不读取 `.env`/API key、不请求 Fuyao、不锁定 scope、不排队、不启动 worker。新增 6 个测试文件，但提交与文档未记录测试通过数或覆盖率。**非声明**：本地自我声明授权不等于供应商授权或保留范围证据；未产生真实样本、行情数据或全历史结论。

### OpenData PR #145：离线股票日线缺口对账（可作为补采规划输入）

[PR #145](https://github.com/cloudQuant/opendata/pull/145) 已合入 `dev`，提交为 `2ca3e5afdb1d4112a5b3c1476485a34a8770d667`。新增 `stock_daily_gap_evidence_bundle.py`、`scripts/ops/reconcile_stock_daily_history.py` 及运维文档：从调用方显式准备的本地证据目录读取 manifest 与 artifact，复用 head/interior/tail 缺口核验并输出确定性 JSON。CLI 只读文件，不访问数据库、`.env`、供应商、网络或系统时钟，不写业务数据、不派发任务、不生成自动修复动作；输入有大小/数量上限并拒绝符号链接。

报告中的 SHA-256 只证明输入字节与 manifest pin 一致，不是签名，也不证明来源、审核人、授权或历史可回溯性；publication 身份是调用方 envelope 的声明，且报告始终将 `all_a_universe_complete` 与 `universe_census_attested` 标为 `false`。新增 4 个测试文件，测试计数未记录。**非声明**：该报告可作为后续补采规划的输入证据，但工具本身不创建补采计划、不执行补采，也不是任一标的或全 A 股覆盖完整性的证明。

### OpenData PR #146：受硬门禁保护的股票日线 v2 读取路由

[PR #146](https://github.com/cloudQuant/opendata/pull/146) 已合入 `dev`，提交为 `2b616245d3fc3b38abc1389a3ee1917245b52ec2`。新增 `opendata/api/stock_daily_publication.py` 并挂载 `/api/v2/stock-daily/records`：按显式 `publication_id` 和半开日期窗口返回固定 publication 的分页 records，使用 snapshot ID 与 opaque cursor 固定同一 publication/窗口/选择/grant scope，校验 schema、单位、币种、`adjustment_basis=raw` 及 publication/sequence 一致性；coverage 保持 `unknown`。

路由带 `_require_stock_daily_api_disabled` 依赖，当前**始终返回 404** 且 `include_in_schema=False`；测试明确断言门禁路径不会读取 publication store。新增 2 个测试文件，测试计数未记录。**非声明**：路由已实现但硬禁用，不等于容量验收、生产启用、真实授权或真实跨仓读取；不得据此声称股票日线 v2 已可供 AFI 业务使用。

### OpenData PR #147：向 THS 股票 job 传递请求预算

[PR #147](https://github.com/cloudQuant/opendata/pull/147) 已合入 `dev`，提交为 `b5957ad32862d7e20bd33a753a4aaba117b668e2`。`make_fetch_symbol_async` 与 `run_incremental_job` 增加可选 `request_budget`：仅接受单源 THS `stock_daily`，要求 fetcher 声明精确 canonical model；同一 job 内多个 symbol 共享同一线程安全计数器，每个 symbol 使用独立 `FetchContext` 的超时/取消生命周期。双源或其他 domain/source 显式拒绝。

该参数必须由可信应用代码提供，本身不创建 grant 或网络权限；预算是进程内 scope，不协调其他 job 或 worker 进程，也未接入调度/配额控制面。新增 1 个测试文件，测试计数未记录。**非声明**：不证明跨进程限流、生产预算执行或真实请求已受控。

### OpenData PR #148：反射后的时态身份 CHECK 校验

[PR #148](https://github.com/cloudQuant/opendata/pull/148) 已合入 `dev`，提交为 `97aaa59e1df97e9a2c5ed803ac076cb12a9d62a2`。修改 `alembic_data/versions/20261029-0021_temporal_identity_snapshot.py`，新增受限 CHECK 表达式解析器，使 MySQL 反射后的冗余括号、`LENGTH`/`CHAR_LENGTH` 别名及 `BETWEEN`/比较组合仍能按已审阅语法校验，并拒绝不完整或未知语法；同时新增纯函数测试与一个 opt-in MySQL publication acceptance 测试文件（需专用空 schema 和显式环境变量）。

提交与文档未记录该 opt-in MySQL 测试是否实际运行及通过数。**非声明**：纯解析器测试不等于真实 MySQL 迁移已执行；也不证明时态身份、publication 或来源数据正确。

### OpenData PR #149：DWD diff 标记口径修正与 THS MySQL 竖向验收夹具

[PR #149](https://github.com/cloudQuant/opendata/pull/149) 已合入 `dev`，提交为 `7cc613bfc15fc3e35da9213d204955e269ae1b83`。修正 `DwdMergeService`：`affected_keys` 只用于扩展源读取/重算范围，不再作为 `extra_diff_keys` 强行打标；行是否差异由 `merge_source_frames` 按源值比较决定（同值修订重算保持 `_diff_flag=0`）。新增 `docs/operations-dwd-diff-flag-correction.md`，记录当前 `_diff_flag`、`dq_diff_report` 与历史 C48/C52 矛盾记载的边界，并明确存量错误标记不会自动修复，需另行有界双源重算核对。

同时新增 opt-in `tests/test_ths_stock_mysql_vertical_acceptance.py`：在专用临时 MySQL 8 实例上走 THS→ODS/DWD→v1 REST 竖向链路，THS HTTP 仅由 `httpx.MockTransport` 提供，要求操作者显式确认实例/空 schema 隔离，不请求真实凭据。提交与文档未记录该 e2e 是否实际运行、通过数或覆盖率。**非声明**：这是模拟 THS 的隔离验收夹具，不是真实 THS 请求、生产 MySQL、AFI 消费或自然周期证据；也不表示历史 `_diff_flag` 已纠正。

## 2026-10-31 AFI PR #201–#203：授权存储、固定日线读取与迁移计划

以下 AFI 提交同样只覆盖代码/离线或文档范围；提交信息与仓库文档未记录测试通过数，本节不补造数字。

### AFI PR #201：精确 snapshot grant 存储

[PR #201](https://github.com/cloudQuant/ai-for-investor/pull/201) 已合入 `dev`，提交为 `1af1366cccbdeef57d7c84c15820d556124c8cf8`。新增 `stock_snapshot_user_read_grants`、`stock_snapshot_source_research_grants`、`stock_snapshot_grant_audits` 三个 ORM 模型及 Alembic 迁移 `20261030_stock_analysis_snapshot_grants`（`down_revision=20261017_legacy_paper_import_cutover`），以标量列和不可变 scope、issue/revocation audit、精确 ASCII 标识及检查约束保存授权事实；ORM 事件拒绝普通对象变更。

该存储**默认为空**，不签发权限、不认证签发人，也不强制完整的 issue/revoke 审计链；bulk ORM/SQL 可绕过 ORM 监听，数据库级 UPDATE/DELETE 保护属于另行部署的控制。该合入提交未包含可信 adapter、OpenData registry 信任、route/task、后台执行/读取/保存前复核，迁移在真实 MySQL/生产库的运行也未记录。**更正**：#193 条目中“授权持久模型/迁移仍在本地开发中”的表述已过时；#201 只把持久化基础合入，仍不能关闭 AC09/AC18，也不构成可信 grant registry 或可用授权功能。新增 1 个测试文件（使用内存 SQLite），测试计数未记录；未记录 MySQL/PostgreSQL 运行。

### AFI PR #202：固定股票日线 publication 的 AFI 读取器

[PR #202](https://github.com/cloudQuant/ai-for-investor/pull/202) 已合入 `dev`，提交为 `076caa979498f0e930f5454bf7b48b766e3d29e1`。`OpendataProvider` 新增 `fetch_published_stock_daily_snapshot`：只读一个显式 pin 的 stock-daily publication，首屏要求 `publication_id` 与半开窗口，后续页只使用返回的 snapshot ID/opaque cursor，执行 deadline、页数/字节上限、重复 cursor 拒绝和 response 字节预算；`OpendataStockDailySnapshotReader` 独立校验请求身份、publication/sequence、snapshot 绑定、行字段/单位/币种/复权基准，coverage 原样保留 `unknown`。

该 reader 有意**未接入**股票业务任务、授权策略或 fallback provider，也没有业务调用点；它依赖的 OpenData 路由当前硬禁用（#146），因此本次只有离线/mock 合同验证，没有真实跨仓读取。新增 1 个测试文件（`httpx.MockTransport`），测试计数未记录。**非声明**：不构成 AFI 消费迁移、真实数据读取、生产授权或全历史覆盖。

### AFI PR #203：按可验证数据闭环排序的迁移计划

[PR #203](https://github.com/cloudQuant/ai-for-investor/pull/203) 已合入 `dev`，提交为 `733655f8a3dcf20bd37ee0fb72e1d147b54194a6`。仅新增 [PRACTICAL_MIGRATION_PLAN.md](PRACTICAL_MIGRATION_PLAN.md)，提出按“合同 → 写入/发布/API → AFI 消费 → 隔离端到端 → 有界真实影子 → 自然周期 → 单写者切换”排序的执行计划，并区分 `CODE/OFFLINE`、`REAL_SOURCE`、`DEPLOYMENT`、`NATURAL_CYCLE` 与历史覆盖口径。该文档是计划与停止条件，不是任何任务的完成证据。

### 本批共同边界

上述 PR 合计只推进了代码、离线工具、隔离夹具和计划文本。仍无真实 THS/Fuyao 来源请求、生产 MySQL 部署、AFI 业务接线、自然调度周期、单写者切换或逐标的全历史对账证据；没有证据表明这些新入口已注册为生产任务，v2 日线路由保持硬禁用。全 A 股（含北交所、退市证券）分母、来源授权/保留范围、BSE 目录和 MySQL/InnoDB 生产行为继续为 `UNKNOWN` 或 `NOT_RUN`。该结论限于 #134–#149 批次；#150 合入后改为默认关闭的容量门禁，默认配置下仍返回 404。

## 2026-10-31 Wave 13/14（已合入）：容量门禁、股票日线授权、回补执行器与真实捕获字节回放

本节记录 Wave 13/14 增量的**合入**状态：OpenData 部分随 #150 `a76b48580c2f71ac3dc6a045a05edafba1f896e5` 合入，AFI 部分随 #204 `b825f921476b6e698881e1be68993c8a4ac610e1` 合入。合入只表示这些代码与离线测试进入两仓 `dev`，**不表示已部署、已启用或已获生产接受**；上一节“按已合入 HEAD 核对”的结论仍分别适用于其自身批次。四个合入提交的汇总、证据边界与 CI 状态见下节“Wave 15：合入记录”。

### 1. OpenData：受 digest-pinned 容量证明保护的股票日线 v2 读取门禁

新增 `opendata/api/stock_daily_capacity.py`。路由仍保持 `include_in_schema=False`，但把原先无条件 404 的依赖替换为：`STOCK_DAILY_PUBLICATION_API_ENABLED=true`、`STOCK_DAILY_PUBLICATION_CAPACITY_FILE`、`STOCK_DAILY_PUBLICATION_CAPACITY_SHA256` 三项同时有效，且证明文件必须绑定 `dataset_id=cn-equity-stock-daily`、`source_id=akshare.daily`、`semantic_version=stock-daily-raw-v1`、contract SHA-256、窗口/页大小上限与有效期。任一缺失、过期、摘要不符或已解析 publication 与证明不匹配都返回统一 404。该门禁只证明部署配置与请求边界被显式声明，**不是**数据授权、来源权利、容量测量或真实数据证明。

验证：`tests/test_stock_daily_capacity_attestation.py`、`test_stock_daily_publication_api.py`、`test_stock_daily_publication_contract_edges.py` 合计 **40 passed**（本次重跑 4.03s）；Ruff 通过。新增运维说明 `docs/operations-stock-daily-publication-capacity.md`。

### 2. AFI：股票日线精确 grant 存储扩展与读取前授权 adapter

- `app/models/stock_analysis_snapshot_grant.py` 与纯策略 `opendata_snapshot_authorization.py` 的 dataset→source 映射新增 `cn-equity-stock-daily → akshare.daily`，CHECK 约束同步扩展；新增迁移 `20261031_stock_daily_snapshot_grants`（`down_revision=20261030_stock_analysis_snapshot_grants`）。股票日线没有源端 capture，grant 的 `capture_id` 明确定义为**平台 publication `content_sha256`**，不是来源 capture。
- 新增 `StockDailySnapshotAuthorizationAdapter`：从调用方异步 session 重新读取当前 principal、最大 revision 的 user/source grant 及其 ISSUED/REVOKED audit、`AssetDataSourceRegistry` 行，再调用既有纯策略；读取前授权、响应校验后再次复核。`OpendataStockDailySnapshotReader.read_authorized(...)` 为默认关闭的 opt-in 路径；原 `read()` 签名与行为保持不变。没有接入业务任务、调度或报告生成。

验证：adapter/storage/policy/reader 四文件合计 **138 passed**（本次重跑 62.38s；其中 adapter 14 项）。Ruff 通过。该切片仍不认证签发人，不提供生产 grant registry/签发 API，不证明真实数据或部署；receipt 仍是无密钥摘要。

### 3. 跨仓固定 publication wire 验收（合成数据）

新增 OpenData fixture server `tests/test_stock_daily_cross_repository_fixture_server.py` 与 AFI opt-in 测试 `test_opendata_stock_daily_publication_cross_repository_wire.py`：在隔离子进程中用 SQLite 合成 publication 挂载**真实** stock-daily 路由，AFI 用真实 `OpendataStockDailySnapshotReader` 经 IPv4 loopback 读取。验证 2 行、日期、publication/content hash、unknown coverage、仅 1 次 records 请求；错误 publication 失败关闭且无重试。本次重跑 **9 passed（3.64s）**；未加 opt-in 时 9 skipped。证据摘要见 `var/reports/afi204/stock-daily-publication-cross-repo-wire-20261031/`。

### 4. OpenData：可恢复的回补执行器与 CLI

新增 `opendata/pipeline/stock_daily_backfill_executor.py` 与 `scripts/ops/execute_stock_daily_backfill.py`：从 digest-pinned instrument snapshot 重建计划，校验 `plan_sha256`/chunk 幂等键/任务绑定，按计划顺序经现有 RunLedger/RunService/RunDispatcher 执行有界分片；已成功分片跳过，遇到 failed/cancelled/leased/uncertain 立即停止，不重试终态失败，不生成新 identity。新增 `execution_only` reviewed job 路径，使任务保持 disabled/无 schedule；dry-run 为默认，`--execute` 需要显式本地 SQLite、离线响应 fixture、artifact root 和授权 token。CLI 拒绝远程/非 SQLite URL、摘要不符、未知 target 与不安全路径。

验证：executor/CLI/plan/budget 四文件 **49 passed**（3.23s）；`run_service`/`run_dispatch`/one-shot/worker/stock_daily_job 共享回归 **345 passed**（18.59s）；Ruff 通过；scoped mypy（`--follow-imports=skip`）在修复新增 CLI 类型标注后无问题。完整 follow-mypy 仍有既有诊断，不能宣称整仓 mypy 通过。

### 5. 真实捕获字节回放（非实时）

使用 2026-10-29 已捕获的真实 Eastmoney 日线响应（10 行，body SHA-256 `2d707ecd...c509`），在隔离 SQLite 上走通：真实捕获 JSON → stock-daily job → publication → **真实** v2 路由 → AFI 真实 reader。最终验收 publication 为 `3485fb5f48b94c4e8cbfa3bded44a888`，scoped content SHA-256 `2dbde8e8...dd942`，10 行，日期 `2026-10-12..2026-10-23`，coverage=`unknown`，AFI 仅 1 次 records 请求、无重试。AFI opt-in 测试 **9 passed**（4.27s）；OpenData executor/plan/job 回归 **142 passed**。证据见 `var/reports/afi204/stock-daily-real-sample-replay-20261031/`。

授权开启模式另跑 **11 passed、1 skipped**（11.39s）：使用文件型隔离 SQLite 中的合成 user/role、精确 user/source grant、ISSUED audit 和 `AssetDataSourceRegistry` 行调用 `read_authorized`，成功读取同一真实捕获 publication 的 10 行；缺少 user grant 时在**任何 records 请求前**以 `stock_daily_user_grant_missing` 失败关闭；在 provider 返回后注入 REVOKED audit 时以 `user_grant_revoked` 失败关闭且不返回行。授权主体、grant、registry 和撤销均为测试注入，不是生产签发/撤销服务或真实用户授权。

**该回放的真实性边界**：body 是此前捕获的真实响应，但本次没有重新请求来源；它是离线回放，不是 `REAL_SOURCE` 实时请求或来源授权证明。publication ID 每次运行随机生成；样本自身记录 `completeness_assessment=not_evaluated`，不证明窗口完整、全历史、自然周期或生产部署。

### 6. 质量门禁与开放边界

- 新增/修改文件的 Ruff check/format 通过；scoped mypy 在修复后无新增问题；AFI 定向测试与 Ruff 通过。
- `make published-openapi-check` 的既有失败（`unsupported OpenAPI reference: #/$defs/Exchange`）来自 Wave 13/14 记录，本次未在 Wave 15 HEAD 重跑，不能写成通过；stock-daily 路由 `include_in_schema=False`，该失败不是本批路由改动引入的。
- `make a2-check` 本轮运行以 **30 个既有 finding** 结束（例如 `tests/test_ths_dwd_integration.py`、`tests/test_watermark.py` 等）；日志中未将 finding 归到本批新增的 stock-daily 文件，但这仍是全仓门禁失败，不能写成通过。
- 覆盖率因当前环境的 pytest-cov 提前导入触发既有 `Settings` 初始化错误而未采集，不能补造覆盖率数字。上述测试结果均为定向/隔离运行，不等于整仓 `make gate`、远端 CI 或 Python 3.10 runtime 通过。
- 本批证据摘要与文件哈希位于 [`wave13-14-20261031/SUMMARY.md`](</home/yun/Documents/ai-for-investor/var/reports/afi204/wave13-14-20261031/SUMMARY.md>) 与同目录 `SHA256SUMS`。
- 仍开放：实时 THS/Fuyao 有界请求与操作者批准、真实来源授权/保留证据、生产 MySQL/部署、AFI 业务接线、影子对账、单写者切换、自然周期、备份恢复、权威全 A（含 BSE/退市）分母与逐 `instrument_id × dataset_id` 全历史。Wave 13/14 只把股票日线切片推进到 `CODE/OFFLINE` + 真实捕获字节回放；不得据此宣称迭代204完成或生产可用。

### 7. 对任务矩阵的影响（不自动关闭父任务）

| 子任务 | 本次新增的可确认子范围 | 仍未完成 |
| --- | --- | --- |
| 204-A05-04 | v2 日线路由的默认关闭容量门禁、contract/source/窗口/页大小绑定，合成 wire 验收 | 真实部署容量/时钟/数据库、生产 grant、真实来源 |
| 204-B05-03 | 逐分片可恢复执行器、ledger 幂等/跳过/停止语义、离线 CLI 与真实捕获字节回放 | 真实全 A 分母、逐标的全历史、生产 MySQL、预算/worker 部署、自然周期 |
| 204-E03-04 | 股票日线精确 grant 存储扩展与读取前/响应后授权 adapter（默认关闭）；授权开启的真实捕获回放 11 passed（缺 grant 请求前拒绝、读取后撤销失败关闭） | 真实用户 grant registry、签发/撤销 API、业务任务接线、报告保存前复核；测试 grant/registry 为合成 |
| 204-E03-05 | 固定 publication/content hash 的 AFI reader 与回放证据 | 报告工件、publication/vector 长期保留、真实数据与 PIT 证据 |
| 204-E06-03 | 跨仓合成 wire + 真实捕获字节回放（离线） | 真实来源、生产部署、真实 grant、影子/自然周期 |
| 204-B02-04/05 | 真实 body 的离线回放与字段/单位通过 reader 验证 | 实时来源、真实授权、全历史与单位/复权独立校准 |

## 2026-10-31 Wave 15：合入记录

本节记录四个后续合入；两仓当前 HEAD 分别为 AFI `b825f921476b6e698881e1be68993c8a4ac610e1`（#204）、OpenData `373211d246ab3099ac8c551681c0f1703fcbd964`（#152）。合入只表示各 PR 声明的代码/离线与测试范围进入 `dev`，不改变上方 Wave 13/14 的证据边界，也不表示迭代204完成、已部署或已获生产接受。

| 仓库/PR | 合入提交 | 本次合入范围 |
| --- | --- | --- |
| OpenData [#150](https://github.com/cloudQuant/opendata/pull/150) | `a76b48580c2f71ac3dc6a045a05edafba1f896e5` | 股票日线 v2 路由的 digest-pinned 容量门禁（默认关闭）；仅执行模式的回补执行器与 CLI（计划摘要/分块幂等绑定、终态跳过、失败停止、dry-run 默认、`execution_only` 任务）；跨仓与真实捕获回放的 fixture server。门禁绑定 dataset/source/semantic version/contract SHA-256/publication/窗口/页大小/有效期，任一不符返回 404。 |
| OpenData [#151](https://github.com/cloudQuant/opendata/pull/151) | `56d4cb38869c0fb8114c917be78e720506f659de` | opt-in 的 Fuyao 六 scope（利润表/资产负债表/现金流量表 × annual/quarterly）真实样本回放测试：经 reviewed job、临时 SQLite archive、真实 archive route 与 AFI financial-archive reader，校验 manifest 与实体 hash，漂移时失败关闭。 |
| OpenData [#152](https://github.com/cloudQuant/opendata/pull/152) | `373211d246ab3099ac8c551681c0f1703fcbd964` | 离线当前 A 股 universe 候选模块、CLI、测试与文档：从捕获的 SSE/SZSE/BSE/Fuyao 目录构建确定性候选，保留市场限定身份，报告重复/冲突而不合并，completeness/pagination 保持显式 `UNKNOWN`；不发布到数据库或 API。 |
| AFI [#204](https://github.com/cloudQuant/ai-for-investor/pull/204) | `b825f921476b6e698881e1be68993c8a4ac610e1` | 股票日线精确 grant 扩展到 `cn-equity-stock-daily`/`akshare.daily`；默认关闭的读取前/响应后授权 adapter；迁移 `20261031_stock_daily_snapshot_grants`；跨仓合成 wire 与真实捕获字节回放测试及文档。 |

**证据**（均为定向/离线运行，不等于整仓 `make gate`、remote CI 或 Python 3.10 runtime）：

- 股票日线：OpenData 定向 **434 项通过**（容量 40、执行器/CLI/plan/budget 49、共享 ledger/worker/job 回归 345）；AFI 授权 **138 项通过**（storage/policy/reader/adapter，adapter 14 项）；合成跨仓 wire **9 项通过**；真实捕获字节回放 **9 项通过**；授权开启回放 **11 项通过、1 项跳过**（缺 grant 请求前拒绝、读取后撤销失败关闭）。
- Fuyao 六 scope：#151 opt-in 回放 **1 项通过**，覆盖 **52 项观察（13/13/7/7/6/6）**，六个 manifest 实体 hash 校验一致。回放的是此前捕获的真实字节，不是实时请求。
- Universe 候选：#152 synthetic **20 项通过、1 项跳过**；真实 SZSE opt-in **21 项通过**，得到 **2,905 条候选记录、0 冲突**；分页终止仍为 `UNKNOWN`，无退市生命周期，`universe_census_attested=false`；SSE/BSE/Fuyao 真实响应体为 `NOT_RUN`；新模块的 16 项 scoped mypy 诊断已由 #153 清零。
- `make published-openapi-check` 与 `make a2-check` 的 Wave 13/14 既有失败未在本节重跑，不能写成通过；AFI #204 迁移未在生产 MySQL 运行，测试中的 grant、principal、API key 均为合成。

**CI 状态：可归因项已修复，但仍非全绿。** 上述 PR 按用户要求在 CI 清理前合入；后续 #206–#209 已修复本批可归因问题：

- #206：两处授权迁移空库安全降级、Binance 行身份 MD5 的 `usedforsecurity=False`、文档链接检查器（angle-bracket/本地证据树）与 AFI11 历史证据包 allowlist。
- #207：全部迁移测试的当前 head 断言更新到 `20261031_stock_daily_snapshot_grants`。
- #208：修复既有 `20261016_legacy_paper_import` MySQL 触发器缺少右括号、账户 fence 触发器降级清理、lease 索引随表删除；在隔离 MySQL 8.4 上完成 upgrade→`alembic check`（无新操作）→downgrade 到 `20260911_market_data_semantic_record_keys`→upgrade head；资产研究迁移测试 **12 passed**，MySQL 合同测试 **1 passed/2 skipped**（本地版本常量改为 8.4）。
- #209：刷新 dev/prod 锁（brotli、certifi、dnspython、OpenTelemetry 1.45/0.66、Pillow 13、akshare Linux racer 依赖），`pip-audit` 从 **45 条公告降为 0**。

最新 `dev` 上 MySQL 9.4 Contract、Backend Security Scan、Deps Sync、Doc Links、No Generated Artifacts、Alembic、OpenAPI 等检查已不再出现在失败列表。仍失败的均为既有全仓债务或与本批无关：OpenData `quality gate`（A2 30 项均在既有测试/脚本，新 stock-daily/universe/Fuyao 文件不在其中）与 full-history secret scan；AFI Backend Lint（205 项 Ruff，均既有文件；新 adapter 模块 mypy 0 错误、新文件 Ruff 通过）、Mypy Ratchet（quote、utils+schemas）、Frontend Lint、Secret Scan 与 E2E Chromium。**CI 尚未全绿，不能写成通过**；上述修复收据与剩余失败分类保留在本节，供后续清理。

**共同非声明**：四个合入均没有实时来源请求、生产 MySQL/部署、自然周期、全历史/覆盖完整性或来源权利/PIT 证明；合成 grant/principal/API key 不代表生产授权；Fuyao/universe 原始样本仍保存在私有归档，未进入 Git。v2 日线路由在默认配置下仍返回 404，容量门禁不是数据授权，回补执行器不是调度器，universe 候选不是权威全 A 分母。**父任务保持开放**，逐子任务影响见 [SUBAGENT_TASKS.md](SUBAGENT_TASKS.md) 的 Wave 13/14/15 合入证据节。

## 2026-11-01 Wave 16：CI 债务清理（AFI #212–#216、OpenData #154）

本节记录 CI 债务清理，不属于迭代204的功能交付。它不改变上方任何证据边界，也不构成数据、来源或部署验收。

**关键事实（此前被误报）**：`Backend - Unit Tests` 自 2026-10-19 起是 `skipped` 而不是 `passed`——`backend-test` 依赖 `backend-lint`，而 lint 门禁自那次 snapshot 合入起一直为红，整仓后端测试因此从未在 CI 中运行。#212 合入后该作业恢复执行并通过。

| 仓库/PR | 合入提交 | 范围与验证 |
| --- | --- | --- |
| AFI [#212](https://github.com/cloudQuant/ai-for-investor/pull/212) | `34756425441c34ed93e7612df33c7131245599d1` | 清掉整仓 Ruff lint（206 项 → 0，ruff 0.16.2）：F401/F811/I001/UP035/C413/F541、3 处 `raise ... from None`、8 处未读取的局部绑定、`app.models.__all__` 补 3 个 LegacyPaper 模型、AFI08 optional-SDK 测试的 `# noqa: E402`。验证：30 个受影响测试文件在 `dev` 工作树与分支上给出**逐字节相同**的 17 项既有失败；OpenAPI `paths` 无差异。 |
| AFI [#213](https://github.com/cloudQuant/ai-for-investor/pull/213) | `afb94a8a6f80497c6178017dcf9e00b4b91f98e2` | 清零 `mypy app/utils app/schemas`（1 项）与 `mypy app/services/quote`（3 项）：`service_market.py` 的 `route` 变量复用导致二/三元组类型冲突、`curve_keys` 显式三元组、`portfolio_analytics_v1.py` 对 `Decimal.as_tuple().exponent` 的 `cast`（`is_finite()` 已排除哨兵值）。 |
| AFI [#214](https://github.com/cloudQuant/ai-for-investor/pull/214) | `7ba51f411177b93b9f48af04ca9c3402ec2fe757` | full-history 密钥扫描：逐行审阅 42 项 `generic-api-key` 命中（UUID 测试标识、测试口令、JWT 别名、SHA-1/SHA-256 内容摘要、跨行表达式片段），按 `commit:path:rule:line` 指纹登记；`unresolved_findings` 保持 0、`blocking_ready` 保持 true。gitleaks 8.30.1 全历史 **42 项 → no leaks found**。 |
| AFI [#215](https://github.com/cloudQuant/ai-for-investor/pull/215) | `72c35355a07c8d24928d2c02769e6c473f063d84` | 纯 `ruff format`（121 文件）。语义不变的证明是机械的：121/121 文件格式化前后 `ast.dump(ast.parse(...))` 完全一致；整仓 mypy 计数不变。 |
| AFI [#216](https://github.com/cloudQuant/ai-for-investor/pull/216) | `4d35da65b695e417b408da9577ae590b7d9b710d` | large-file 棘轮刷新：**16 个已登记文件超限增长**（最大 PortfolioPage.vue 1885→3572、useDataPage.ts 4167→4912、query_service.py 1603→1778）**+ 21 个 ≥1000 行但从未登记**（最大 service_read/deployment.py 1793）；登记为“只可缩小”，并写入 `decomposition_plan`（5 个波次、逐文件拆分目标与前置条件）。PR 正文列出每一处上限变更。 |
| OpenData [#154](https://github.com/cloudQuant/opendata/pull/154) | `e940fd7d68302e8da73b66577dae926978823063` | `make secret-check` 的 10 项命中（8 个 fixture 运行/配额字面量）以字面量枚举加入 `generic-api-key` allowlist，并按仓库既有标准补 `docs/evidence/C150/` 三臂反事实测量（去掉该正则 → 10 项全部回归；任一字符变体 → 仍报告；同槽位植入凭据 → 仍报告）。全历史 **10 项 → no leaks found**。 |

**CI 结果（合入后实测，非推断）**：AFI `dev` 上 `Security - Secret Scan`、`Backend - Unit Tests`、四个 Mypy Ratchet 分域作业（utils+schemas、quote、api subset、services subset）均为 success；OpenData `dev` 上 `secret scan (full history)` 为 success。**仍未全绿**：AFI `Backend - Lint & Type Check`（仅剩整仓 mypy 棘轮 0→329）、`Frontend - Lint & Type Check`（npm audit 生产依赖 high 0→5/critical 0→2）、E2E 四个浏览器作业；OpenData `quality gate`（A2 平面，本次未动）。以上均不得写成通过。

**边界**：本轮只改静态检查、测试门禁与依赖/基线声明，没有触碰任何数据事实、授权判定或发布语义；格式化与基线刷新都不构成对既有数据或来源证据的重新验收。

### Wave 16 补充（同日夜）：mypy 归零、前端依赖与 E2E 定因

用户决定“真实修掉 329 个 mypy 错误”后，按 5 个波次并行修复，全部以真实类型修复完成，**未新增任何 `# type: ignore`**（逐支测量）：

| 波次/PR | 合入提交 | 范围 | 分支上 `mypy app` |
| --- | --- | --- | --- |
| [#217](https://github.com/cloudQuant/ai-for-investor/pull/217) | `531a2b4a9` | `service_read` 全包（含 `contracts.py`） | 329 → 214 |
| [#218](https://github.com/cloudQuant/ai-for-investor/pull/218) | `4fc29e887` | api 层、data-fetch 适配器、db | 329 → 310 |
| [#219](https://github.com/cloudQuant/ai-for-investor/pull/219) | `77b5b4565` | risk-policy/budget/monitoring/approval-authority | 329 → 264 |
| [#221](https://github.com/cloudQuant/ai-for-investor/pull/221) | `0ae31915f` | portfolio analytics/composition/ledger | 329 → 269 |
| [#223](https://github.com/cloudQuant/ai-for-investor/pull/223) | `47e467dfd` | 其余 service 模块 + 4 个 legacy ORM 模型现代化 | 329 → 213（合并 dev 后 **0**） |
| [#224](https://github.com/cloudQuant/ai-for-investor/pull/224) | `979284848` | 吸收 typing 造成的 12 个文件 +286 行增长 | — |

**合入后 `dev` 实测**：`mypy app` → `Success: no issues found in 738 source files`（0 错误），`ruff check .` 与 `ruff format --check .` 干净，`large_file_ratchet` 通过（95 文件）。

两个只在**跨波次合并**时才显现的事实，已记录并修复：ORM 现代化把 4 个 legacy 模型改成 `Mapped`/`mapped_column` 后，其他波次为读同一批属性加的 4 处 `cast(str, ...)` 变成 `warn_redundant_casts` 错误（运行时无变化，已删除）；`contracts.py` 被两个波次以不同变量名改到同一处循环，按 `decimal_code` 解决。ORM 改动的等价性不是断言而是测量：两棵树的全量 metadata 对比 **168 张表、0 处 `CreateTable` DDL 差异、0 处索引差异**。

其余合入与结论：

- **前端 [#220](https://github.com/cloudQuant/ai-for-investor/pull/220)**（`3ced550ed`）：`vue-i18n` 9.14.5 → 11.4.16；`dompurify` override 3.4.16 → 3.4.17、`follow-redirects` 1.16.2。`npm audit --omit=dev` 由 **5 high / 2 critical → 0 / 0**。**monaco 未降级**——critical 链是 `monaco 0.56 → dompurify ≤3.4.16`，抬 override 即可清除，比原计划的 0.55.1 降级更小且已验证。代价是 `vue-i18n@11` 要求 `node >= 22`，因此 engines 从 `^20.19 || ^22.13 || ^24` 收紧为 **`^22.13 || ^24`**，CI/e2e/nightly、`.nvmrc`、3 个容器定义与部署脚本同步；**Node 20 不再受支持**属于部署面变更。验证：audit 0/0、eslint 0 warning、`vue-tsc` 通过、**vitest 170 文件 / 2,034 测试通过**、`npm run build` 与 node-engine 门禁通过；7 个 locale × 5,042 条消息在 9.14.5 与 11.4.16 下逐字节一致。
- **E2E [#222](https://github.com/cloudQuant/ai-for-investor/pull/222)**（`cce202873`）：四个浏览器作业自 2026-10-17 起全红的**第一个确定原因**，是 `e2e/tests/afi09-gateway-health.spec.ts` 需要 `AFI09_E2E_*`（只有专用 config 提供），却被通用 `playwright.config.ts` 收集，因此每个 project 都必然失败；通用配置排除该 spec 后收集数 90 → 89，专用 config 仍收集它。**第二个原因未修且不应猜**：`/trading/gateways` 在未配置 `SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON` 时按设计返回 503 `OPERATOR_NOT_CONFIGURED`，而 `product-domain-pages.spec.ts:155` 拒绝任何 5xx —— 这需要“E2E 部署是否提供合成 operator 配置”的产品/部署决定。
- **OpenData [#155](https://github.com/cloudQuant/opendata/pull/155)**（`5e75e9c27`）：`/api/v2/identity/resolve` 的 `openapi_extra` 嵌入了带相对 `$defs` 引用的 Pydantic schema，在 OpenAPI 3.1 下是**悬空 `$ref`**（客户端生成器同样会失败）；改为发布前内联（字段/类型/边界/描述不变），并据此把 v2 评审批次刷新为“+1 path、+2 个标准校验组件、0 删除、0 既有路径变更”。**v1 漂移未冻结**：`/api/pipeline/run` 的 `symbols` 增加 `maxItems:10000`、`limit` 上限 5000→10000，属容量决策，留给 owner。
- **OpenData [#156](https://github.com/cloudQuant/opendata/pull/156)**（`6b5116d75`）：A2 静态工具面 30 项 ruff + 7 个未格式化文件清零（`S603` 逐处 `noqa/nosec` 并注明 literal argv、`S608` 一处表名为模块常量、3 个仅注解导入移入 `TYPE_CHECKING`）。**A2 gate 仍未绿**：其 mypy 与 bandit 平面需要 CI 环境（bandit 与类型 stub 来自 `.[web,dev,providers]`），本轮未处理。

**未闭合项（不得写成完成）**：E2E 的 503 部署决策；OpenData `quality gate` 的 mypy/bandit 平面；`test_afi11_monitor_process_failure` 对 `monitoring_control.py` 的字节数指纹在本次改动前就已过期（35,973 vs 60,992），需要单独复核；Node 20 支持已在本轮移除，任何仍固定在 Node < 22.13 的环境会按设计被引擎门禁拒绝。

### Wave 16 追加：OpenData A2 全平面、前端干净检出与"重新可见"的单测债务

**OpenData A2 门禁整体通过。** [#156](https://github.com/cloudQuant/opendata/pull/156)、[#157](https://github.com/cloudQuant/opendata/pull/157)、[#158](https://github.com/cloudQuant/opendata/pull/158)（`6b5116d75`、`e739a8dc1`、`9f71cf9ae`）之后，用 CI 同构环境（Python 3.11 venv 从 `.[web,dev,providers]` 安装：ruff 0.15.20 + bandit + 类型 stub）实测：

```
PATH=/tmp/od-venv/bin:$PATH /tmp/od-venv/bin/python scripts/quality/a2_check.py
OK: A2 files meet the full A2 standard (ruff + format + mypy + bandit).
exit=0            # 920 个 mypy 目标，1,538 个 A2 文件
```

mypy 36 个失败目标 → 0；bandit 6 项**全部靠消除不安全构造**解决（`/tmp` 私有根改 0o700、表名走固定白名单、`subprocess` 用字面量 argv 且 `shell=False`），没有用 `nosec` 掩盖。**教训（已写入 PR）**：这个门禁只能用锁定 extra 跑——我第一次用了环境里的 ruff 0.14.11，得到的 30 项与"修法"在 0.15.20 下都不成立，反而制造了 16 条 unused-noqa。**仍红**：`quality gate` 作业还包含 `test-cov`、前端、`published-openapi-check` 等成员；后者因 **v1 契约漂移**（`/api/pipeline/run` 的 `symbols` 新增 `maxItems`、`limit` 上限 5000→10000）仍失败，那是 owner 的容量决策，本轮不冻结。

**前端干净检出问题（[#226](https://github.com/cloudQuant/ai-for-investor/pull/226)，`3fad48a28`）。** 49 条 eslint warning 清零；同时发现更严重的一处：`components.d.ts` 是构建产物且被 gitignore，而 CI 在**构建前**跑 `vue-tsc`，所以干净检出上一直有 50 个 `TS2558` 错误。新增 9 行 types-only 的 `element-plus/global` 引用修复，不含运行时代码。渲染等价性用 `@vue/compiler-sfc` 编译前后 AST 对比证明（2 个文件 9 个纯文本节点各多一个空格，HTML 折叠后无差异）。

**Backend - Unit Tests：从"假绿"到"真的可见"（[#228](https://github.com/cloudQuant/ai-for-investor/pull/228)，`af0856b26`）。** 该作业此前两周是 `skipped`（依赖 lint），恢复执行后立刻以 **pytest exit 2（收集错误）** 失败：19 个测试模块在模块级 import `zmq`/`bt_api_*`，而这些包不在任一条依赖路径里（`src/bt_api_*` 是无打包元数据的源码树，装不上）。按仓库既有约定（`test_afi08_owner_freeze_control_http.py` 的 `pytest.importorskip`）给其余模块加上同样的守卫：

```
before: 2030 collected, 14 errors, Interrupted
after : 9143 collected, 0 errors (24 deselected)
```

收集修好后整套**真的跑起来**：**183 failed / 8789 passed / 201 skipped**（34 分钟）。这些失败是"刚被看见"，不是"刚被引入"——先前的 `skipped` 让它们完全不可见。按错误类别分诊（供后续波次使用）：`DATASET_FILESYSTEM_CONFIGURATION_INVALID` 62、`'Depends' object has no attribute 'scalar'` 36、`dotenv reads are disabled by the service-read integration test` 30（测试隔离泄漏）、`No module named 'bt_api_execution'` 28、`assert False is True` 26、`no such table: users` 24、陈旧签名（`get_paper_order() missing ... 'response'` 等）20。**该作业仍红，不得写成通过**；修复正在按类别推进。

**报告证据 vector 首个增量（[#229](https://github.com/cloudQuant/ai-for-investor/pull/229)，`cbd4ca930`）。** 迭代计划的 E03-04/05、E06-03 要求"报告只可引用有持久证据的 vector"并在保存前重验。此前 `_build_and_save_report` 完全没有来源记录。本次加入：冻结的 `StockDailyReportEvidence`/`Vector`（严格校验 dataset/source/instrument/market/publication/sequence/content+contract hash/UTC 时间/principal/grant 版本/有效期/purpose，并拒绝重复与 receipt 不一致）、保存前逐条 `revalidate` 的闸门、`evidence_vector_json` 列与迁移 `20261101_stock_analysis_report_evidence_vector`（单一 head），22 项测试通过、仓库级 mypy 保持 0。**重要边界**：**尚无生产者接线**——没有任何真实任务会构造并提交该 vector，因此这道闸门在真实运行中不会被触发；它让要求"可实现且已测试"，**不是"已满足"**。

### Wave 16 追加二：E2E 第二个成因修复与单测债务的首轮收敛

- **E2E [#222](https://github.com/cloudQuant/ai-for-investor/pull/222) → [#234](https://github.com/cloudQuant/ai-for-investor/pull/234)**（`409e3d398`）：剩余那个 503 不是"测试太严"，而是**真实的集成缺陷**——面板只读 `data.detail.code`，而 API 错误中间件把 FastAPI 的 `detail` 重新包成了 **`details`**，所以"未配置 operator"的状态从未渲染，页面一直落到通用的"不可用"文案。修好读取（两个信封都接受）后，spec 的豁免被收得很窄：只有 **503 + 精确的两个 API 路径 + 报文里 `OPERATOR_NOT_CONFIGURED`** 才被排除，且随后必须断言 `[data-test="operator-list-error"]` 的"未配置"文案；其他 5xx/401/403 仍然失败。本地 Chromium：**89 run → 89 passed / 0 failed / 0 did not run**（此前 63/1/25）。**未验证**：Firefox/WebKit/Mobile 未本地运行、已配置(200)分支需要真实 deployment JSON、`CI=true` 重试未演练——所以证据是"成因已修"，不是"四个作业已绿"。
- **Backend 单测第一轮（[#233](https://github.com/cloudQuant/ai-for-investor/pull/233)，`97adc8017`）**：这批工作来自一个跑满回合上限的子代理，我把它的未提交工作树抢救到新分支、补跑 lint/format 并**逐项复验**后才合并（属于"审阅后抢救"，不是"代理自述"）。核心内容：陈旧 direct-order 测试重写到 managed-paper 合同（两条旧测试换成三条更强的新测试，含 operation-id 要求）、`get_simulation_portfolio_overview` 的真实缺陷修复、paper/portfolio API 测试改用依赖覆盖、AI research 部署 fixture、SDK 导入守卫。全量实测：**183 failed → 47 failed**（8934 passed / 215 skipped）。**作业仍红**，剩余 47 项已按文件聚类交给下一波。

### Wave 16 追加三：前端与 E2E 全绿、后端单测收敛到个位数、py3.10 收集修复

**AFI `dev` @ `1499efbf5` 实测**（GitHub check-runs）：除后端单测外全部转绿——`Backend - Lint & Type Check`、`Frontend - Lint / Unit / A11y / i18n`、**E2E 五个作业（Chromium/Firefox/WebKit/Mobile/Summary）**、Secret Scan、四个 Mypy Ratchet、迁移/OpenAPI/文档/依赖检查均 success。

- **前端 A11y（[#237](https://github.com/cloudQuant/ai-for-investor/pull/237)）**：并非无障碍缺陷——所有 axe 扫描通过；失败是**陈旧 fixture**：页面在 `6f6e0644f` 后要求 `capability_states` 普查，而 spec 只喂了 feature flags。补上普查后 15 passed / 0 axe violations。
- **前端 i18n（[#238](https://github.com/cloudQuant/ai-for-investor/pull/238)）**：CJK 违规 **59 → 0**，双语键各 +63（4846/侧，parity 0），zh-CN 文案逐字节不变；其中 10 处在 `PortfolioAnalyticsTaskPanel.vue`（原任务描述有误）。
- **后端单测**：[#233](https://github.com/cloudQuant/ai-for-investor/pull/233) 183 → 47，[#239](https://github.com/cloudQuant/ai-for-investor/pull/239) 把含这 47 项的 9 个文件降到 **6**（672 passed / 13 skipped）；#239 还修了一个真实缺陷：`build_subprocess_env` 补全的是 `launch_instance`，而发布后合并读的是启动前快照，导致解析出的运行时合约元数据从未落盘。
- **py3.10 收集（[#240](https://github.com/cloudQuant/ai-for-investor/pull/240)）**：`Backend - Unit Tests (py3.10)` 的 exit 2 是两个原因——7 个测试模块 `from datetime import UTC`（**3.10 不存在**，而项目声明 `requires-python >= 3.10`，属真实不兼容，已改 `timezone.utc`），以及 14 个模块经 `app`/`scripts` 间接依赖 `akshare`（它在 `requirements-dev.lock` 里但不在 `[dev,backtrader]` extra 里，已按 #228 约定加 `importorskip`）。py3.10 实测收集 **8992/20 errors → 9015/0**。

**仍未闭合**：三个单测矩阵腿在 `1499efbf5` 均为 failure（`--maxfail=5`），剩余为上述 6 项个例（catalog 迁移的 `CircularDependencyError`、`Depends` 当 session 用、路由 deprecated 断言、403/422 期望、缺 `users` 表 fixture、`KeyError: 'duplicate'`），正在逐项修复；因此**不能说作业已绿**。

**OpenData 剩余**：`zero-dep-check` 仍红。原因是本迭代新增运行时模块引入了 9 处上游名字符串引用（`api/stock_daily_capacity.py`、`pipeline/stock_daily_backfill_executor.py` 各一处 `"akshare.daily"`；akshare provider 层 6 处 `"akshare"`），且引用登记册有 13 个文件哈希因正常改动过期。我先尝试重签，发现 `--force-update` 会把 9 条新 finding **冻结进基线**，于是回滚：这是一个"哪些文件允许引用上游"的范围管控，重签需要逐条 `ast_exceptions` 复核，不能以放行换取绿灯。

**流程教训**：`dev` 只接受 `feature|fix|docs|refactor|test` 前缀，`feat/*` 会被治理门禁拒绝（我因此重开过一次 PR）；治理门禁若在作者自审提交前跑完会"假失败"，需要重新触发一次。




### Wave 17：MySQL 9.4 迁移回归的根因修复、单测真实边界与 OpenData gate 恢复运转

#### 1. #245 撤回之后：MySQL 9.4 恢复、catalog 测试重新失败

`#245`（`662c13ad7`）把 #243 的四个迁移守卫撤回后，`dev` 的 `Asset Research - MySQL 9.4 Contract` 恢复 **success**（`662c13ad7` 的 check-runs 实测）；代价是 `test_catalog_migration_accepts_current_startup_created_schema_at_iteration_196_baseline` 重新失败——`#245` 的 PR 正文已把这个后果写明。

#### 2. [AFI #246](https://github.com/cloudQuant/ai-for-investor/pull/246)（合入 `3f45d281c`）：从 #243 的 CI 日志拿到确切根因并修复

#243 的 PR CI 日志给出了 MySQL 9.4 上真正的失败点，而不是 #245 无法本地复现的那段：

```
pymysql.err.OperationalError: (1828, "Cannot drop column 'source_import_receipt_id':
needed in a foreign key constraint 'fk_legacy_paper_cutover_import_receipt'")
```

根因：#243 在 `20261017_legacy_paper_import_cutover` 的 downgrade 里删掉了显式 `drop_constraint("fk_legacy_paper_cutover_import_receipt", type_="foreignkey")`，假定"删列会连带删 FK"。MySQL 明确拒绝（1828）；SQLite 的 batch 重建把 FK 随列一起丢掉，所以 SQLite 测试一直是绿的。修复方式：

- 重新应用四个 adopt-or-reject 守卫；
- 两处 downgrade（cutover、approval authority sources）改为**先反射 schema 上真实的 FK 名并显式 drop，再删列**：迁移创建的 schema 反射到 `fk_legacy_paper_cutover_import_receipt` / `fk_strategy_target_source_version`，startup 创建的 ORM schema 则反射到模型自己的约束名；SQLite 不保留约束名，反射不到时仍交给 batch 重建；
- `tests/test_quote_service_market.py` 与 `tests/test_afi01_owner_scope_service_host_integration.py` 加 `pytest.importorskip`（`bt_api_base` / `bt_api_py` 不是本项目依赖）——这正是 `--maxfail=5` 一直掩盖的 **19 项**失败。

**证据**：SQLite `tests/market_data_platform/test_catalog.py` **17 passed**（含 196 基线正向往返）；本地 MySQL **8.0.46** 隔离实例完整跑 CI 序列 `upgrade head → alembic check（No new upgrade operations detected）→ downgrade 20260911_market_data_semantic_record_keys → upgrade head → current=head`（修复前同序列以 1828 失败）；**PR CI 的 `Asset Research - MySQL 9.4 Contract` = success**，即该修复在真实 9.4 服务容器上通过了整条链；clean worktree 全量 **5 failed / 8935 passed / 234 skipped**（5 项分别是 `test_ai_chat_service` 1 项、`test_ai_strategy_research_service` 2 项、`test_ensure_dual_stress_running_script` 2 项；三个文件隔离运行 **278 passed**，属顺序/并行相关，不涉及本 PR 改动的文件）；`ruff check` / `ruff format --check` 通过。**未声明**：5 项顺序相关失败仍未消除，单测矩阵腿在 PR CI 上的最终结论以其运行结果为准。

#### 3. OpenData `quality gate` 从"从未执行"恢复为真实判据

OpenData 的 gate 因 `alembic check` 与两个证据册长期失真而**在 `Verify migrations match the models` 一步就停住**，后面的 `make gate` 从未执行。本轮把它推到真实判据：

- **Drift（[OpenData #161](https://github.com/cloudQuant/opendata/pull/161)，合入 `1ba6d7d9`）**：`od_job_definitions` 与 `od_metadata_publication_receipts` 由迁移创建、由原生 SQL 读写、不进 `Base.metadata`，autogenerate 每次把它们判成 removed。`alembic/env.py` 增加只排除这两张表及其索引的 `include_object`（附原因）。本地 MySQL 8.0.46 复现了与 CI 相同的 4 条 remove 与 exit 255，修复后 `alembic check` 报 `No new upgrade operations detected.`
- **零依赖证据册**：13 个注册路径的 sha 在真实改动后过期、4 个新模块带入 9 处来源身份字面量、扫描面 741 而 census 记 658。逐条用"pin 字节所属 revision → 当前 HEAD 的实际 diff"复核后重钉 13 条、新增 4 条注册，census **658→741**、冻结基线 **0→9**（9 处全为 Literal/常量来源身份，逐文件 reviewer 记录在案）。`--self-test` 与正式扫描均 OK。
- **brand-check**：13 处旧库名 token 按既有的 `runtime_inventory` 同类理由加入 **token 路径白名单**（旧库名与 rights_evidence 标签是事实标识，改名会破坏端点/路径哈希校验）；只有这 9 个路径对该 token 放行，其余品牌与包引用检查不变。
- **已合入的 [OpenData #160](https://github.com/cloudQuant/opendata/pull/160)（`b079e816`）/ [#159](https://github.com/cloudQuant/opendata/pull/159)（`f33bfc9a`）**：补 C150 的叙事与可追踪测量文件（此前 `.log` 被 `.gitignore` 忽略，重命名为 `.txt` 入档），并刷新 v1 OpenAPI 合同基线到实际 schema。它们分别解决 `evidence-traceability` 与 `published-openapi-check`。

**实测（clean worktree，避免本机 5.2GB 未跟踪 `var/` 干扰）**：`zero-dep-check`、`brand-check`、`ledger-check`、`evidence-traceability`、`js-points-check`、`loguru-check`、`a2-check`、`published-openapi-check`、`quality-ratchet`、`public-api-quality` 全部 **exit 0**；CI（`cc9e3760` 的 quality gate，含 gitleaks 与 MySQL）同样通过了这 11 个成员。**仍红**：`acceptance-probe-check` —— CI 报 **20 个 stale-proof 格**（台账记 proven、探针此刻读 gap）与 **14 条新棘轮条目**（AC-16|05/06/07/09、AC-17|03/05、AC-18|01、AC-19|02、AC-1|08/09、AC-4|01、AC-5|03、AC-8|02）。其中一个根因已经定位：AC-16|05 的判据要求零依赖冻结基线 `recorded_findings == 0`，而本迭代新增的股票日线模块合法携带 **9 处上游来源身份字符串**（`Literal["akshare.daily"]`、`ADAPTER_ID` 等，已逐条复核并登记）。要抹平它只有改产品身份/判据或由 owner 裁定 `--sync-ratchet` 显式入账两条路，**不在无裁定情况下自行处理**。`test-cov` 与 `frontend-*` 尚未在该分支上执行。结论只到"gate 已开始真实执行、11 个成员通过"，**不是整链通过**。

#### 4. AFI CI 的 diff-coverage 修复（[#248](https://github.com/cloudQuant/ai-for-investor/pull/248)，`bf24d397f`）

`Backend - Unit Tests` 长期在**每个** PR 上红，与测试无关：`Check diff coverage` 拿 `origin/master` 当比较基线，而 `dev` 领先 master 数百个提交。#246 的单测腿实测 **8940 passed / 234 skipped** 仍被判定失败（`Missing: 9281 lines`, coverage below 60%），缺的正是 dev 自己尚未发布的代码。改为比较该 PR 的真实目标分支（并先 `git fetch` 该 ref，因为 `checkout` 只取合并提交），阈值与测量口径不变；`diff-cover` 本身会跳过 `--cov=app` 未测量的文件（测试、`alembic/versions/*`），本地以 `--compare-branch=origin/dev` 验证输出 `No lines with coverage information in this diff.`、exit 0。

#### 5. 共同非声明

MySQL 9.4 的结论来自 PR CI 的真实 9.4 服务容器；本地 8.0.46 仅用于复现与回归。OpenData 的 `make gate` 尚未整链绿；acceptance-probe 的 22 个 stale-proof 格需要 CI 环境下的复测与逐格判定。以上均为 CODE/OFFLINE 与 CI 证据，不构成真实源/生产/自然周期验收。

### Wave 18：Backend 单测首个绿腿、diff-coverage 基线、akshare 上游删模块与报告证据生产者接缝

#### 1. 第一个真正跑完并变绿的单测腿

AFI `dev` @ `3f45d281c` 的 `Backend - Unit Tests (py3.11)` = **success**：**8940 passed / 234 skipped**。这是该作业在"因 lint 失败被 skipped"与"被 `--maxfail=5` 截断"之后的第一次完整绿腿；同一提交上 MySQL 9.4 Contract、Lint、四个 mypy ratchet、前端四作业与 E2E 五作业也全部 success。

#### 2. py3.10/py3.12：不是挂起，而是跑完后的上游删模块

两条腿各跑 62 分钟（3.11 为 32 分钟），结论是 **1 failed / 8838 passed / 1 error**，不是卡死。根因：unit-test 作业只在 canonical Python 上安装 `config/requirements-dev.lock`；3.10/3.12 腿自由解析依赖，作业日志里 `akshare-1.20.21` 覆盖了锁定的 1.18.97，而 1.20 删除了 `akshare.forex` 与 `akshare.stock_feature`：

- `test_forex_hist_em_default_uses_bounded_usd_cnh_symbol` → `ModuleNotFoundError: akshare.forex`；
- `tests/test_akshare_script_service.py` 在导入期即失败（其导入的脚本模块级引用 `akshare.stock_feature`）。

[#251](https://github.com/cloudQuant/ai-for-investor/pull/251)（`819be711`）按仓库既有的 `pytest.importorskip` 约定给这两个入口加保护，并在原因里写明版本差异；生产仍安装锁定的 1.18.97，脚本的模块级导入不改。**3.10/3.12 是否转绿以该合并后的 CI 为准**。

#### 3. diff-coverage 的比较基线（[#248](https://github.com/cloudQuant/ai-for-investor/pull/248)，`bf24d397`）

`Check diff coverage` 原先比较 `origin/master`，而 `dev` 领先 master 数百个提交：#246 的单测腿实测 8940 passed 仍被判 `Missing: 9281 lines`（缺的全是 dev 自己未发布的代码）。改为比较该 PR 的真实目标分支并先 `git fetch` 该 ref；`diff-cover` 本身会跳过 `--cov=app` 未测量的文件（测试、`alembic/versions/*`），本地以 `--compare-branch=origin/dev` 验证为 `No lines with coverage information in this diff.`、exit 0。

#### 4. E03-04/05 报告证据生产者接缝（[#250](https://github.com/cloudQuant/ai-for-investor/pull/250)，`c3877b6b`）

`report_evidence_producer.py` 在任务执行开始时读取**声明的固定 publication**（经注入的授权感知 reader），构造 `StockDailyReportEvidenceVector` 并写回 `parameters_json`（`flag_modified`），保存前的 `_revalidate_report_evidence` 仍是唯一闸门。缺 reader、reader 授权/coverage 拒绝、选择器与返回不一致、观测时间缺失/冲突全部 fail-closed，13 项新测试 + 22 项既有证据测试通过，回归 85 passed / 1 skipped。

**明确未完成（不得写成已满足）**：选择器只含 instrument/publication 身份、不含业务窗口，而 reader 的 `MarketDataProviderRequest` 必须先给 `start_at/end_at`；`read_authorized` 也只返回结果、不暴露授权 receipt。选窗口策略与暴露 receipt 属产品决定，未擅自编造。因此真实运行中的选择器任务仍以 `stock_daily_report_evidence_reader_unavailable` fail-closed、不产生报告——E03-04/05 保持 **PARTIAL**，`SUBAGENT_TASKS.md` 已同步。

#### 5. OpenData `test-cov` 首次实测与冻结迁移修复（[OpenData #162](https://github.com/cloudQuant/opendata/pull/162)，`968cd6a0`）

clean worktree 全量 `make test-cov`：**35307 passed / 247 skipped / 73 failed / 18 errors**（9:21）。分诊：18 errors 是本机 venv 缺 `pytest-timeout`；约 49 项 yfinance 失败是本机 `curl_cffi` 与锁不一致（`YFINANCE_UNSUPPORTED_CURL_CFFI_VERSION`）；**6 项是真实问题**——`test_publication_stock_scope_migration.py` 对 0017/0018 的冻结字节做 sha 校验，而 #158 给 A2 mypy 平面补注解时改动了这两个历史 revision。重钉哈希并记录改动性质：0017 仅加注解；0018 另把一个字段取到局部变量再做 `String/length` 收窄，语义不变。修复后该模块 **13 passed**。**非声明**：`test-cov` 在 CI 的整链结论仍需 CI 复核；本地环境差异已逐类列明。

#### 6. OpenData gate 仍未整链通过

11 个成员在 CI 通过；`acceptance-probe-check` 仍红：**20 个 stale-proof 格 + 14 条新棘轮条目**。已定位的根因之一是 AC-16|05 要求零依赖冻结基线 `recorded_findings == 0`，而迭代新增的股票日线模块合法携带 **9 处上游来源身份字符串**（`Literal["akshare.daily"]`、`ADAPTER_ID` 等，已逐条复核登记）。抹平它只有改产品身份/判据或由 owner 裁定 `--sync-ratchet` 两条路，本轮不自行处理。

---

### Wave 19：AFI 矩阵与依赖面收口、OpenData gate 的「PR 形状 ≠ push 形状」根因、test-cov 首轮

#### 1. AFI：矩阵腿与 akshare 声明边界

- **[#253](https://github.com/cloudQuant/ai-for-investor/pull/253)（合入 `2ddcd9f92`）**：unit-test 三条腿此前只在 canonical Python 上装 lock，3.10/3.12 用自由解析跑 62 分钟后红。改为**每条腿都装 `config/requirements-dev.lock`**，并把矩阵收成 `3.11 / 3.12`——3.10 不是被"跳过"，而是 lock 在它上面无法解析（`akshare==1.18.97` 与 `contourpy==1.3.3` 都声明 `Requires-Python >=3.11`），一条只测解析器的腿没有判据价值。合入前 py3.11 腿实测 **8940 passed / 234 skipped**，41 项检查全绿。
- **[#254](https://github.com/cloudQuant/ai-for-investor/pull/254)**：把 `akshare` 的声明范围收成 `>=1.18.96,<1.19`。理由是三个 data_fetch 模块在 import 期引用上游内部路径（`akshare.forex.forex_em`、`akshare.stock_feature.stock_sns_sseinfo`、`...stock_technology_ths`），而 1.20.21 的 wheel 里 `akshare/forex/` 与 `akshare/stock_feature/` 已不存在——这正是 nightly（`41290727588`，job `124801241435`：`1 failed / 7916 passed / 1 error`，`ModuleNotFoundError: No module named 'akshare.stock_feature'`）的成因。**同一 PR 还要跟着改 `scripts/ci/tests/test_check_deps_sync.py`**：那份契约测试钉住了未封顶的 `>=1.18.96` 字面量，漂移样本也按同一字面量做字符串替换，范围一收它俩同时失效（`Check - Deps Sync` = `2 failed, 7 passed`）。本地 `pytest scripts/ci/tests/test_check_deps_sync.py -q` **10 passed**。
- **治理门禁的一课**：#254 声明 R2 被判红——`matched_rules` 指出 `**/pyproject.toml` 与 `**/requirements*.txt` 命中 `r3-dependency-and-security-inputs`，**路径推导的风险等级不能被作者的较低声明降级**。改成 R3 后同头 SHA 的 Governance Gate 转绿。

#### 2. OpenData gate：探针的红格子集合随运行变化——三个假设依次被自己的数据证伪

`acceptance-probe-check` 在不同的 CI 运行里量出**不同的红格子集合**，于是任何一次冻结都可能对下一次运行不成立。本轮为了搞清它，连着证伪了自己三个假设：

| 观测 | 当时的形状读数 | 结果 |
| --- | --- | --- |
| run `41323810828`（PR，默认 merge ref） | `git rev-list --count HEAD` = **3**，`is-shallow-repository` = **true** | AC-16\|09 gap（`scanner=972, fragment_population=972` 明明相等，只被 shallow 旗标判死）；AC-19\|02 把浅边界提交当成"档案今日首次入库"；AC-17\|03/05 额外产生 `judge` 命中 |
| run `41321297008`（同一分支的 workflow_dispatch，**跳过 `make gate`**） | 完整历史 | 同一棵树量出 **2 judge + 18 stale-proof**，AC-16\|09、AC-19\|02 无命中 |
| 本地 clean worktree（detached 分支头，安静树） | 完整历史 | AC-16\|09 **proven**、AC-19\|02 **proven**、AC-17\|03/05 gap（与已钉文本一致） |
| run `41328176599`（假设一：改成 `ref: <PR head sha>`） | checkout 后仍 `HEAD=3, shallow=true` | **假设一被证伪**：SHA checkout 与 merge ref 一样 |
| run `41332032552` / `41335236551`（假设二：改成 `ref: github.head_ref`，并在 `make gate` 前 `--unshallow`） | `after-checkout shallow=false head_commits=976`、`before-gate shallow=false head_commits=976`、`after-gate shallow=true head_commits=5` | **假设二被证伪**：分支 checkout 是完整的，gate **开始之前**历史也是完整的；截断发生在 `make gate` **运行期间**，所以 gate 前的补全什么也没保住（该步骤已删除） |
| run `41335493770`（假设三：形状决定读数——#166 的 PR 跑，用的是 dev 的原 ci.yml 与默认 merge ref） | 默认 merge ref | **假设三被证伪**：AC-16\|09 **proven**、AC-19\|02 **proven**。同一个 merge-ref 形状，一次读出完整、一次读出截断 |

排除过程留下的两条硬事实：

1. **不是 checkout 形状**。#163 的跑与 #166 的跑用的是同一类 checkout（merge ref/branch 都出现过 proven 与 gap 两种结果），而 `before-gate` 与 `after-gate` 之间仓库自己变了形。
2. **不是那 11 个前置成员**。在独立克隆里按 gate 顺序逐个跑 `brand-check zero-dep-check secret-check ledger-check evidence-traceability js-points-check loguru-check a2-check published-openapi-check quality-ratchet public-api-quality`，**全部 rc=0 且 `shallow=false head=972` 自始至终不变**。所以变形发生在 `acceptance-probe-check` 自己的运行里，且只在 CI 环境（本地没有 Docker，AC-21 那片 owned-MySQL 叶子跑不起来）——嫌疑集中在探针为若干格子起的 pytest/docker 侧效应，尚未定位到具体一行。

因此本轮对「入账」给出**修正后的结论**（比前几轮更保守）：

- 棘轮的 finding 文本本身是稳定的（`stale_cell_finding()` 只拼 item 与被读的**时刻面名单**，不拼实时数字），所以 10 个稳定格子的入账是有意义、可复现的登记。
- 但 **AC-16|09、AC-19|02（以及只在部分运行出现的 AC-17|03/05 `judge`）不能靠冻结解决**：它们取决于"探针运行期间仓库是否被截断"这一运行期事实。把它们钉进基线，下一次它们读出 proven 时又会撞上「收口未重钉」而红；不钉则随时可能冒出新增。**先修仪器（让历史面量一个受控快照，或找到探针内部的截断源），再谈冻结。**
- 另注：`#164` 的 20 条来自**跳过 `make gate` 的派生运行**，而真实 gate 运行量出的是「10 钉中 + 4～14 新增」——这正是「量一个不跑 gate 的形状，然后期望跑 gate 的运行匹配」的失败，不是某次 PR 的偶发。

在同一棵树上第四次量：本地独立克隆按 `--gate-check` 完整跑完（130 格全部走到判定，945 条 break 各施加一次，反事实面 129/130），结果又是**另一组读数**——`agrees=109 / stale-proof=21 / 命中 10 / 新增 12`（AC-13|06、AC-16|05、AC-16|06、AC-18|01、AC-18|03、AC-1|08 judge+stale-proof、AC-1|09、AC-4|01、AC-5|03、AC-8|02、§6|03），而 AC-16|09、AC-19|02 仍读 **proven**，全程 `shallow=false head=972` 未变形。

于是同一棵树共有**四种读数剖面**：跳过 gate 的派生跑（20）、本地完整 `--gate-check`（21 + 12 新增）、CI gate 跑（20 stale-proof + 14 新增）、以及 #166 那次 CI gate 跑（17，且 AC-16|09/AC-19|02 为 proven）。这把结论从「形状没统一」收紧为「**仪器对环境不确定**」：AC-13|06/AC-18|03/§6|03 只在缺 MySQL/Docker 的机器上红，AC-16|09/AC-19|02 只在 CI 的 gate 运行里红，而红格子的集合还取决于同一轮里前面跑过什么。任何一次 `--sync-ratchet` 冻结的都是这四种剖面之一，因此它不可能让后面的任何一种运行变绿。#163 的 sync 入口仍然保留——它是记录当前剖面的工具，但**入账之前必须先让读数确定**（把历史面与外部依赖面改为在受控快照/显式能力位下判定），否则冻结只是把不确定性挪到下一次运行。

- **[#163](https://github.com/cloudQuant/opendata/pull/163)**：`sync_acceptance_ratchet` 手动派生入口（只打印 diff 并上传 artifact，CI 永不提交基线）；PR 跑改测 head 分支（这是**树**的忠实性，与历史无关）；并在 checkout 后与 gate 后各打印一次形状——这两行打印就是上面全部结论的来源。
- **[#164](https://github.com/cloudQuant/opendata/pull/164)**：owner 裁定的棘轮入账（items 10→18、pins 10→20，无删除）。按上面的修正，它**尚不能作为可让 gate 转绿的成品合入**：需要在真实 gate 形状下重测，或先修历史面。已在本 PR 上留下完整测量记录，等属主决定是"修仪器后重钉"还是"把 probe 成员降级为 advisory"。

#### 3. OpenData `test-cov`：首轮可归因失败与一次自查

在只读 clean worktree 里用 CI 的安装 argv 复现 `make test-cov`：**73 failed / 18 errors / 35307 passed / 247 skipped，8:55，覆盖率 87.52%**——阈值 `--cov-fail-under=84` 不是阻塞项。[#165](https://github.com/cloudQuant/opendata/pull/165) 只修可归因的五类：

- `curl_cffi>=0.7.0` 会解析到 0.17.0，而 yfinance provider 用 `_GOVERNED_CURL_CFFI_VERSIONS = {0.13.0, 0.16.3}` 精确 fail-closed → 27 项红。钉到已评审的 0.16.3 后 `-k yfinance` **434 passed**。
- `dev` extra 少了 `pytest-timeout`，`--strict-markers` 下 `@pytest.mark.timeout` 在每个 xdist worker 收集期报错 → 那 18 个 error。
- 两处把 `os.fstat` 换成缺 `st_size` 的假对象，pytest 自己的 capture teardown 读它。
- 三个 sina worker 用例要求 cwd 在仓库之外，`make` 从根目录跑时永远不满足 → 改为 `monkeypatch.chdir(tmp_path)`。
- 「启动不建表」守卫解析的是 `main.lifespan`，而 `create_all` 已移进 `_existing_lifespan`，于是它量到 0 个调用点却断言 1 个——**这一条是判据自己失效**（与 AC-8\|02 的读数直接相关）。
- 一个参数化行在收集期冻结 `datetime.now()`，比该行的 `observed_at_utc` 还早，先撞了顺序检查。

**这一轮也暴露了我自己的验证盲区**：#165 首跑在**第二个成员**就红——`FAIL: reference policy is unusable: stale sha256: pyproject.toml`。`pyproject.toml` 在引用策略里按 path+sha256 双钉，改它就必须同 PR 重钉摘要并写明理由；我在本地只跑了 pytest 与 ruff，没跑 `zero-dep-check`。补钉后本地 `verify_no_akshare.py`（census 仍 741、findings 仍 9）与 `check_brand.py` 均绿。

#### 4. OpenData batch5 身份刻度的两处过期钉（[#166](https://github.com/cloudQuant/opendata/pull/166)）

31 个逐文件摘要里只有 2 个失配，`git diff --numstat 1ad2aee0 HEAD` 证明净漂移是 **+1 行 / 0 删除、两行都是注释**（`typing.cast` 返回第二个实参，域 id、绑定、`__all__` 都没动）。按仓库既有惯例**就地**入账 `yfinance_cast_comment_rebase`（不新造 `snapshot_id`），并保留 175 个仍写着旧摘要的 `docs/evidence` 文件（`C101/claims.merged.json` 一个文件就 100 处）——那是当轮的人工评审凭证，不是活体刻度，也没有 gate 成员读它。修复后四个文件 **118 passed**（原 7 failed / 111 passed）。

#### 5. 18 个已冻结格子的性质分类（决定后续投入用）

读 `measure_*`/`judge_*` 后的判断，不含臆测：

- **纯代码面可收口**：AC-4\|01、AC-1\|03、AC-8\|02、AC-17\|02、AC-17\|03、AC-17\|05、AC-17\|08、AC-18\|01、AC-1\|09；
- **必须实连外部系统或重跑证据轮**：AC-11\|04（真实 MySQL 仓库 EXPLAIN）、AC-16\|07（干净 venv 集成重跑）、AC-5\|07 / AC-17\|06（≤24h 的 bandit 档案、随 HEAD 漂移的覆盖率钢印——这类是"可续期"而非"永久闭合"）；
- **属主/产品决策**：AC-1\|08（§1 权利登记表 35 个引用源目前 0 行——**此句已被 Wave 21 §8 证伪**：35 行齐全，红来自探针按字面量要求列名）、AC-5\|03、AC-16\|05/06（9 处上游来源身份字面量）；
- **判据自身不可满足（`judge` 族）**：AC-1\|08 的 `repair.dated="*rows"` 继承了 `rows=0`、AC-16\|07 的 `repair` 漏了 `archive_self_written`、AC-17\|02 的 `repair` 漏了 `raw_findings`——修探针不等于收口内容。

**留给属主的一个真实问题**（本轮刻意没有自动"修好"）：`47ed8e59` 把 README 的数据免责声明从「本项目不构成任何投资建议」改成限定句式，未留理由，而 `docs/data-rights-registry.md` §4 标题写着「与 README 同步维护」却仍是全称句式——AC-16\|08 读出 gap 正是这个分叉。恢复全称能让判据变绿，但那是法务口径的改动，不是我能替属主定的。

#### 6. 共同非声明

本轮全部结论属 **code/offline 与 CI 平面**：#253/#254/#165/#166 是依赖声明、矩阵与测试刻度的收口；#163/#164 让门禁**可判**，其中 #164 的 20 条入账是 owner 裁定的"已知红"登记，**不是 proven**，也不构成真实源、部署或自然周期验收。真实源取数与权利/保留、生产 MySQL 与备份恢复、影子对账、单写者切换、全 A 股权威域与逐标的完整历史、授权签发/吊销审计、报告门禁的生产适配器仍按前几轮的口径保持未闭合。

---

### Wave 20：OpenData 门禁从「不可判」变成「可判」，test-cov 首次真实分诊

本轮把上一轮留下的两个结构性障碍真正解决，并把 `test-cov` 的可归因失败分批改掉。合入记录（OpenData `dev`）：

| PR | 合入 SHA | 内容 |
| --- | --- | --- |
| [#167](https://github.com/cloudQuant/opendata/pull/167) | `4068b45b` | PR 跑改测 head 分支树；`make acceptance-probe-check` 前补全历史；gate 前后各打印一次形状 |
| [#168](https://github.com/cloudQuant/opendata/pull/168) | `cc14b327` | AC-1\|03 的 5 个未登记路径按 path+sha256 入账，格子读出 **proven** |
| [#169](https://github.com/cloudQuant/opendata/pull/169) | `e3564508` | 两个 alembic head 断言改为测图形状（单头/无分支/边保留），pandas 3 Arrow str dtype 造成的假通过修回 |
| [#170](https://github.com/cloudQuant/opendata/pull/170) | `02df8948` | FastAPI 0.162 的 `_IncludedRouter` 嵌套：跨 include 走查路由；先证明端点集合在 0.115/0.162 下逐项相同，再改判据读取方式 |
| [#171](https://github.com/cloudQuant/opendata/pull/171) | `70eeacbd` | 离线 `--sql` 渲染只跳过「服务器版本断言」这一条、且只在 `upgrade()` 且 bind 真是 `MockConnection` 时；离线边界改为**声明+被测**（`OFFLINE_HEAD=0013`，越界即红），0012 双处摘要随改动重钉 |
| [#172](https://github.com/cloudQuant/opendata/pull/172) | `26a6eb5e` | 用 18 个共驻 CPU 负载实测子进程完成预算（p95 6.4–12.3s、max 18.1s）后统一为文档化的 60s；patrol 日期炸弹改为相对式；csi500 的 inode 复用假设修正 |
| [#173](https://github.com/cloudQuant/opendata/pull/173) | `cc17835b` | **探针自修历史**：九个读历史的面在读取前一刻补全链条（清单不止两个），补不了就 `refused` 并照旧判 gap，绝不造事实 |

#### 1. 「形状不确定」这件事被解决，并有对照数据

#173 之前：PR 作业 `124981684123` 里 AC-16\|09 读到 `HEAD/all=2/1002, shallow=true` 判 gap，而 dev push 作业 `124957785974` 两侧形状一致（975 commits）判 proven。#173 之后，同一个 PR 形态的作业 `125006024661` 读出：

```
台账↔读数：agrees=113, unflipped=0, open=0, deferred=0, stale-proof=17
VERDICT AC-16|09: proven      VERDICT AC-19|02: proven
```

与 dev push 作业的 `agrees=113 / stale-proof=17` **完全一致**。也就是说 PR 跑与 push 跑现在量的是同一批格子，#164 那种「冻结一次就永远对不上」的困境来自的那个变量被消掉了。判据完整性有证明：排除 `readings` 赋值后九个 judge 的 AST 逐字节相同，`breaks` 与 moment 面集合未变，因此没有一条既有钉被这次修复作废。

留下的手段也留在门禁里：`history_repair = already-complete|unshallowed|refused|unread` 会打印在每次读数里，谁在 gate 期间截断仓库仍然没查到，但判定不再依赖它。

#### 2. 新暴露的同类问题：AC-17|07 的红来自「跑与跑之间比较的基线不同」

#173 之后 PR 跑仍有 10 条新增，其中 **AC-17|07（新增公开 callable 的 docstring/注解 100%）在 push/本地是 proven，在 PR 跑是 gap**，原因是这个格子经 `a2_check` 取「新增面」：PR 跑带 `A2_BASE_REF=dev`，于是 population = 本 PR 自己改的文件（本例里没有新的公开 API）→ 判据明确写着「空群体上的 100% 不算测量」→ gap；push/dispatch 跑没有 `A2_BASE_REF`，population = 自基线以来的全部 A2 文件（本地实测 179 文件 / 599 callable）→ proven。

这是**判据语义**问题而不是环境问题：同一条 AC 在两种运行里量了不同总体。把它钉进棘轮会重演「一侧新增、一侧收口未重钉」，所以本轮不冻结它，需要属主先定「新增面」的定义应当是"本差分母"还是"全仓 A2 分母"（若选后者，改法是这一格忽略 `A2_BASE_REF`，不改任何阈值）。

#### 3. 流程教训（同一坑踩了三次）

OpenData 的引用策略按 **path + sha256** 登记了 `pyproject.toml`、`Makefile`、`scripts/quality/acceptance_item_probe.py` 等文件的字节；改这些文件而不同 PR 重钉摘要，`zero-dep-check`（gate 第 2 个成员）会直接中止整条门禁，前面所有信号都拿不到。#165、#167、#173 各中一次。规则固化为：**推之前先跑 `python scripts/codemod/verify_no_akshare.py`**，重钉理由要写明 pin 所属 revision、此后 revision 数、带品牌行数与出现次数前后相等。

#### 4. `test-cov` 的真实进度（不再是「从没跑过」）

基线 73 failed / 18 errors / 35307 passed（8:55，覆盖率 87.52%，阈值 84 不是阻塞）。#165/#166/#169/#171/#172 之后，可归因项已清；**仍红且理由明确**：deadline-window 一族在 >2× 超订下仍敏感（要重推 deadline/child-sleep/观测窗口三元组，不是加大数字）、`test_sina_fzb_recorded_transport_e2e`（25s 子进程 vs `lease_ttl=3s`，慢而活的 worker 会被判死——属主决定）、`tests/test_reviewed_app.py` 两个计时用例、`test_ths_csi500_one_shot_sqlite_gate` 的 marker 格式用例（`-n 0` 也红，是真失败）、以及 `tests/test_frontend_endpoint_contract.py`：`reviewedRuns.ts` 调的 4 个 `/reviewed/*` 路径只有 `create_reviewed_app` 注册，`main.py` 只挂 `api_router`（/api/v1、/api）与 `api_v2_router`，是否线上 404 属 DEPLOYMENT 面，需真实部署核对。

#### 5. 共同非声明

本轮所有绿都在 **code/offline 与 CI 平面**：#168 让一个格子从 gap 变 proven 是登记完整性的修复，不是验收；#170/#171/#172 改的是测试如何测量，不是产品是否可用；#173 让验收仪器变得可复现，但它本身不关闭任何验收面。AC-1\|08（§1 权利登记 35 个引用源 0 行——**已被 Wave 21 §8 证伪**，登记表 35 行齐全）、AC-5\|03 / AC-16\|05 / AC-16\|06（9 处上游来源身份字面量）、AC-4\|01（判据按字面拼写把关节，见 #164 讨论）以及真实源、生产 MySQL/部署、影子对账、单写者切换、自然周期、全 A 权威域、逐标的完整历史、授权签发/吊销审计与报告门禁生产适配器**依旧未闭合**。棘轮重测由 dispatch 作业 `41362343738` 产出，只有那次测量落在真实 gate 形态上才允许入账。

#### 6. 一次我自己制造、CI 看不见的回归（#171 → #176）

诚实记录：**#171 引入了一条 dev 上的真实回归，而且当天无法被 CI 发现**。`alembic_data/versions/20261027-0015_source_attempt_gate.py` 不只是一个迁移文件——它的字节是 `alembic_source_gate/schema_contract.py` 里 `V1_REFERENCE_SHA256` 钉住的 **v1 参照**；adopt 任何 source-gate schema 之前都要先与它比对。#171 为了让 0015 也能离线渲染改了它，契约随即拒绝 adopt，本地实测后果：

| 命令 | dev 修复前 | 修复后（#176） |
| --- | --- | --- |
| `make test-cov` | **134 failed / 154 errors**（49 个 `test_source_gate_quota_provisioning`、40 个 `test_source_attempt_gate_one_shot_v4`、28 个 `test_ths_one_shot_transport` …） | **15 failed / 35414 passed / 247 skipped / 0 errors**，覆盖率 88.33% |
| `pytest tests/test_warehouse_migrations.py tests/test_source_gate_quota_provisioning.py` | 1 failed / 5 passed / **49 errors** | 64 passed / 1 skipped |
| 邻近 4 个 source-gate / publication 迁移模块 | 未测 | 107 passed |

修法不是把 `V1_REFERENCE_SHA256` 改成新摘要（那会让"adopt 对照的是原始 v1 revision"这句话失去所指），而是**把 0015 恢复成被钉的字节，并让它把自己不能离线渲染这件事声明进 `_ONLINE_ONLY_REFUSALS`**；`OFFLINE_HEAD=0013` 不变（0014 早已是前缀终点），边界测试改为断言 0015 属于 refused，这样将来有人再往反方向"修"，刻度会立刻叫出来。

教训两条，都已写进长期记忆：① 文件可以被**代码里的常量**按 sha256 钉住，而不只是被 JSON 登记——动 `alembic*/versions/` 之前必须跨 `alembic_source_gate/`、`opendata/`、`scripts/`、`tests/` grep 文件名找摘要常量；② 只要有成员挡在 `test-cov` 前面，这类破坏 CI 就看不见，**合并过迁移/生成 schema 相关改动之后必须本地跑一次全量**。

### Wave 21：棘轮入账后第一次真实读数，剩余红被分成「过期钉 / 只在我的笔记本上红 / 属主决定」

上一轮结束时 `acceptance-probe-check` 刚刚第一次通过，`test-cov` 第一次拿到真实读数。本轮把那条读数拆开：哪些是**测试对账本读错了**，哪些**根本不是仓库的红**，哪些必须属主先裁定。合入记录（OpenData `dev`）：

| PR | 合入 SHA | 内容 |
| --- | --- | --- |
| [#164](https://github.com/cloudQuant/opendata/pull/164) | `b389d6fe` | 棘轮按 **CI 自己那次测量**入账：16 个格子 / 17 条钉，无删除；来源是 dispatch 作业 `41362343738`，不是任何笔记本 |

判据形状被解决之后，PR #164 的门禁作业 `41372558789`（作业 `125045929651`）第一次走到 `test-cov`：

```
= 14 failed, 35419 passed, 243 skipped, 11 subtests passed in 1047.60s (0:17:27) =
Required test coverage of 84% reached. Total coverage: 88.33%
```

#### 1. 六个测试文件的过期钉（[OpenData #177](https://github.com/cloudQuant/opendata/pull/177)，head `1b2a47ae`）

同一棵树在钉住的 3.11 extra 环境里，改前 `4 failed, 80 passed, 1 skipped`，改后 `84 passed, 1 skipped`，四条失败恰好各命中本 PR 触碰的一个文件：

| 格子 | 账本后来怎么动的 | 旧钉为什么错 |
| --- | --- | --- |
| `test_a2_exclusion_scope`（迁移清单） | #161 `1ba6d7d9` 改了 `alembic/env.py` | 它不再是「早于 A0 且从未被改」的唯一例外，`dark` 必须是空集 |
| `test_check_brand` | #161 为 `*_data` 一个 token 追加 9 条路径 | 账本共 15 条路径；用例现在显式承认这第三类，等式仍然钉住完整 15 条，新增被登记路径依旧会红 |
| `test_nested_vendor_quality_scope` | `eea69cca` 起 `opendata_client` 计 3（`6169b9e0` 给严格快照 SDK 加了 `snapshots.py`）；参照基线 0→9 条 finding（#161） | 两者都是**计数钉**，所以把 9 条上游身份字面量逐条列出，作为「上游引用不能悄悄进账本」的绊线 |
| `test_ths_csi500_one_shot_sqlite_gate` | 迁移夹具实际持有 `sg0004_source_one_shot_v4`（实测），而两个 marker 格式用例硬写 `V2_REVISION` | 校验器按 marker 分派参照 schema：接受用例直接失败，**拒绝用例因为「V2 参照 vs V4 表」而假绿**。改为重新写入夹具真实持有的 revision 后，那条 fail-closed 断言才真的在验「约束名被改」 |

同一个文件里还有第二个反向过期钉，是 CI 教我的：两个清单用例直接调 `guard.resolve_files(None)`，而 `a2_check` 只要看到 `A2_BASE_REF` 就把总体缩成**本次运行自己改的文件**——工作流只在 pull_request 跑导出它。于是同一棵树 push 跑绿、PR 跑红。用本分支的 base 导出该变量本地复现：改前 `2 failed, 61 passed`（19 个适配文件被报「dropped from the zero-tolerance set」、32 个迁移文件被报 dark，而这个 PR 两棵树都没碰），改后 `63 passed` 且在**有与没有** `A2_BASE_REF` 两种形状下同结果。两处都改走 #175 为探针加的 `a2_files_on_recorded_baseline()`（弹出变量→按登记的基线解析→恢复），清单没有因此变虚：把 `opendata/data/providers/akshare/provider.py` 从解析结果里删掉只红适配用例，删 `alembic/env.py` 只红迁移用例（都实测后还原）。

#### 2. 五条「红」其实只存在于我的笔记本：CI 一直在供给 OpenBB 钉定检出

`test_openbb_inventory_guard` 四条 + `test_ac2_case_probe::test_self_test_closes_and_every_break_flips`（其 self-test 的三条内部失败 `AC2-01/12/25` 全部同因）。仓库的供给机制早就存在且是 dev 的祖先：`a755f4aa` 在 `.github/workflows/ci.yml:140-148` 用 `git fetch --depth=1 …/OpenBB.git "$COMMIT"` 取 `UPSTREAM_COMMIT = 3e071fcc2cd9f891cac6040ae60296dba76dab46`（`scripts/quality/provider_model_inventory.py:26`）并导出 `OPENDATA_OPENBB_PATH`；模块只读对象库，从不检出工作树。缺省回退路径 `/Users/yunjinqi/Documents/new_projects/OpenBB/openbb_platform`（同文件 29 行）是维护者笔记本专用——这就是本地报 `Pinned upstream Git object is unavailable.` 的全部原因。实测：只导出环境变量 `OPENDATA_OPENBB_PATH=/home/yun/Documents/OpenBB/openbb_platform`（该仓库含 `3e071fcc` 且可从 HEAD 到达）即 `5 failed, 43 passed` → `48 passed`，未改任何文件。**结论：这五条不是产品也不是测试缺陷，属主需要定的只是本地跑法（导出变量，或把 29 行的个人路径换成显式必填）。**

#### 3. `test-cov` 的真实进度：14 → 9（CI 实测），分类见下

#177 第一个 head 的 CI 作业 `41377376327`：

```
= 9 failed, 35424 passed, 243 skipped, 11 subtests passed in 795.19s (0:13:15) =
Required test coverage of 84% reached. Total coverage: 88.33%
```

9 条的归属（不是「再修修就绿」，而是三种不同性质）：

| 归属 | 条数 | 处置 |
| --- | --- | --- |
| A2 清单的形状依赖 | 2 | 本轮第 1 节已修，随 #177 合入 |
| `/reviewed/*` 契约 | 1 | **不是过期钉**，属主决定，见第 4 节 |
| AC-1\|08 权利登记 | 2 | **不是数据缺口**，见第 8 节：判据按字面量要求列名，探针缺陷 |
| AC-1\|09 gitleaks 正则 | 1 | 镜像分支已就绪，等 CI 自己的棘轮读数，见第 5 节 |
| `test_process_executor` deadline 一族 | 3 | 负载敏感，需要重推 deadline/child-sleep/观测窗口三元组，不是加大数字 |

两次读数的**逐条差分**比计数更有信息量，所以把 14 条与 9 条的 id 都取回来对齐（`125045929651` 与 `41377376327`）：

| 14 条里有、9 条里消失 | 是否被本分支修掉 |
| --- | --- |
| `test_check_brand`（1）、`test_nested_vendor_quality_scope`（1）、`test_ths_csi500_one_shot_sqlite_gate` 的 marker 用例（1） | **是**，第 1 节的三个过期钉 |
| `tests/test_reviewed_worker.py::test_cancelled_lease_stops_running_child_without_publication` | **否**——本分支未触碰该文件，它自己变绿了 |
| `tests/test_sina_fzb_recorded_transport_e2e.py::test_recorded_sina_response_traverses_transport_worker_publication_and_rest_pages` | **否**——同上 |

而 `test_process_executor` 一族在两次里都是 3 条，但**参数化 id 换了**：14 次里是 `messages7-response_invalid` / `messages13-process_exit_status_invalid` / `extra_ipc`，9 次里是 `messages5-worker_setup_failed` / `messages10-response_invalid` / `extra_ipc`。两条 a2 清单项在两次里都在（第二个 commit 才修掉）。

由此得出一条比「红变少了」更有用的判断：计数从 14 到 9 中只有 **3 条是真实收口**，另 **2 条是会自己漂移的用例**（`test_reviewed_worker` 取消租约、`test_sina_fzb_recorded_transport_e2e`），加上参数化身份在族内跳变的 3 条 deadline 用例——即**这 5 条的绿不能当作已验收的证据**，它们测量的东西依赖机器负载。Wave 20 §4 把本地 transcript 与 CI 读数混在一起列「仍红」清单，那份清单里哪些属于同一类漂移并未逐条回溯；从本节起，`test-cov` 的状态以「CI 某次作业的 id 清单 + 该清单是否由某个 commit 改变」表述，不再只报计数。

#### 4. `/reviewed/*` 量出来的结论与上一轮的猜测相反

上一轮 §4 写的「需真实部署核对」这一条被**离线证据替代**了：`backend_table()` 走的不是朴素的 `app.routes` 走查，而是 `app.openapi()`，而 FastAPI 0.162 的 OpenAPI 生成器**确实会跨越 `_IncludedRouter` 嵌套**（main.app 只有 8 个 `app.routes` 对象却生成 151 条路径）。手工跨越 include 分支遍历活对象得到 178 条路由，其中 `/reviewed` 前缀 **0 条**；四个操作真实存在于 `opendata/api/reviewed_runs.py:263`（`APIRouter(prefix="/reviewed")`），但只有 `create_reviewed_app` 挂载它，而 `grep -rn create_reviewed_app opendata/ scripts/` 只有定义与 `__all__` 两处——`Dockerfile`、`opendata.service`、`start_app.sh` 全部服务 `opendata.main:app`，nginx 也只把 `/api/` 转给这一个进程。参照契约 `docs/afi204-v1-openapi.json`（140 路径）与 v2（9 路径）里没有任何 reviewed 路径。

所以「部署后可能 404」的措辞可以升级为：**按当前仓库的接线，浏览器可达的进程里没有任何东西挂载这四个调用**，而 `frontend/src/router/index.ts:88-92` 的后台页真的在调它们。两条捷径都被检查并拒绝：删客户端声明等于拆掉一个已交付功能的传输；把 router 挂进 `main` 而没有 runtime，`get_reviewed_runtime`（`reviewed_runs.py:266-299`）会答 503，门禁转绿而页面照旧坏。反例（只在内存里）：往调用集合加 `GET /reviewed/nonexistent-probe` 仍然原样输出该 id，绊线没钝。#177 只把这段测量写进守卫的模块 docstring（28 增 0 删，断言一行未动，`1 failed, 13 passed` 前后相同），**属主需要裁定的是：哪一个进程持有 `ReviewedRuntime`、它的台账 schema 与角色计划**。

#### 5. AC-1|09：镜像 C150 的正则，但棘轮必须由 CI 自己重测

`.gitleaks.toml` 的 `generic-api-key` 允许清单被 `e940fd7d`（#154，C150 那一轮）加了第 8 条正则，而探针常量 `GENERIC_API_KEY_ALLOWED_REGEXES` 仍是 7 条——历史上每一条允许清单变更都在同一 PR 里回写探针（C75 `60148ce5`、C89 `bddbb06f`、C101–C105 `b15717b6`、C149 单独镜像 commit `50ab04d4`），这次漏了。分支 `fix/od-ac109-regex-drift`（commit `31777488`）选择**镜像而不是删清单**：`regexTarget="secret"` 加两侧锚点意味着只有与八个夹具标签逐字节相同的串被豁免，不改变凭证检测的宽度；而 `docs/evidence/C150/gitleaks-counterfactual.txt` 量过删除那条的臂（`without_c150` 把 10 条命中全部还回来），且 `fixture-ths-quota-v1` 已无活树载体，工作树里无从改名。探针文件本身按 path+sha256 登记，`verify_no_akshare.py` 随即 `stale sha256` → 同 PR 重钉 `1ab81a26b988f60e…` → `6c71ae68f49023ad…`（pin 属 rev `01e3a179`、此后 0 revision；品牌行 212==212、akshare 163==163、openbb 96==96、扫描器 (module,kind) 重数集 13==13）。实测这一面：`exact public-rule exceptions preserved` 由 `no` 变 `yes`；本地整格仍 `gap`，因为剩下三面要 gitleaks 真跑（本机未装，`template_scan_rc: 127`）。

但 AC-1\|09 在棘轮里有一条 `stale-proof` 钉（`ledger_state: proven` + 探针读 gap 才成立）。镜像之后 CI 会把这一格读成 **proven**，即「收口未重钉」方向的红——所以入账必须来自 CI 自己的测量：dispatch 作业 `41379944842` 正在跑 `--sync-ratchet`，产物落地后再把删掉 AC-1|09 那一格的账本作为同分支的第二个 commit 推上去。

#### 6. AFI #256 的红不在正文，而在 GitHub 的重跑语义

`Frontend - Lint & Type Check` 里那一步（`Iteration 175 §4.7 — PR template i18n manifest`）实际读的是 **PR 正文快照**。实测：正文在 `01:28:44Z` 就已含 `- 测试证据`（出现次数 1，脚本核对），而 attempt 2 于 `02:23:44Z–02:24:44Z` 重跑仍报 `FAIL: PR description contract incomplete: - governance field missing: 测试证据`——**rerun 复用创建该 run 时的 event payload，不会重读正文**。修法不是再 rerun 一次，而是产生一个新事件（本轮即随 Wave 21 文档提交新 commit，从而带上新正文）。这条语义写进长期记忆，避免下一次再花一个 30 分钟往返。

#### 7. 共同非声明

本轮的绿全部在 **code/offline 与 CI 平面**：#177 改的是测试如何对账，AC-1|09 改的是探针如何镜像清单，二者都不关闭任何验收面；`/reviewed/*` 的结论是「按仓库当前接线浏览器会 404」的静态推断 + 活应用对象的路由枚举，仍**不是** DEPLOYMENT 面（没有真实部署核对过）。AC-1\|08（判据字面量缺陷，见第 8 节——登记表本身 35 行齐全）、AC-5\|03 / AC-16\|05 / AC-16\|06（9 处上游来源身份字面量）、AC-4\|01、AC-16\|08（免责声明与权利登记的措辞分歧）以及真实源、生产 MySQL/部署、影子对账、单写者切换、自然周期、全 A 权威域、逐标的完整历史、授权签发/吊销审计与报告门禁生产适配器**依旧未闭合**。

#### 8. 更正：AC-1|08 是仪器缺陷，不是数据缺口——我在 Wave 19/20 写错过一次

**我写下过一句错误的话**：Wave 19 §5 与 Wave 20 §5 都记成「AC-1\|08 需要属主决定，因为 §1 权利登记表 35 个引用源目前 0 行」。**这是错的**，而且错的正是本轮反复在防的那类东西：把仪器读不出来当成事实不存在。本轮把两格红拿到手之后逐条重测：

* `docs/data-rights-registry.md:41` 的表头是 `| # | 数据源 | 接入方式 | 条款链接 | 允许本项目落库 | 允许再分发 | 允许商业使用 | 公开条款复核日期 | 责任人 | 状态 |`；`_parse_rights_registration_table`（`scripts/quality/acceptance_item_probe.py:1615` 一带）要求列名**逐字等于** `复核日期`。
* 表头校验一失败，`records` 就是空，`rows` 量到 0，`uncovered` 于是**级联**成 35——「35 个引用源 0 行」是 `table_valid=False` 的下游伪影，不是登记表的真实状态。
* 决定性实验（在 detach 出来的临时 worktree 里做，做完还原，未提交）：只把表头的 `公开条款复核日期` 改回 `复核日期`，`acceptance_item_probe.py --item 'AC-1|08'` 立刻 `VERDICT AC-1|08: proven`；把 table_valid 单独修好后重算六面是 `rows=35 / dated=35 / undecided=0 / unlinked=0 / responsible_missing=0 / uncovered=0`。
* 回归点可以精确归属：`5db160ba`（#23「reconcile source rights declaration」，2026-10-27）同时做了两件事——把列名改掉，并把 v1.8 的告诫句「登记完整性不等于所有用途获准」重写成 v1.9 的「不代表独立核验或全量许可」。探针的字面量早于它（`3f05f636`，2026-10-08）。上一次这条读绿的存档还在 `docs/evidence/C75/ac1-08-rights-registry-repin.txt`（`'table_valid': 'yes'`、verdict proven）。

修法选择**改仪器，不改数据**：探针现在要求「恰好一列以 `复核日期` 结尾」，并把那一列重新键入 `RIGHTS_DATE_COLUMN`，下游面只认一种拼写。三条反例实测（`table_valid` 仍会红）：列名改成不含后缀 → False；出现两列同后缀 → False； shipped 表 → True / 35 行。测试里断言旧告诫句的那一行同步改成现行句，紧邻的反空话守卫（`"全部获准" not in verdict.readings`）保留。**登记表一行都没有动**，也不该动：为了这条绿去编辑权利声明就是把仪器缺陷转嫁给事实记录。

顺带查清两件仍未解的事，都记下来而不是顺手改掉：

1. **`repair` 仍然不可达（二阶仪器缺陷）**：AC-1\|08 的 `repair` 写 `dated="*rows"` 却没有 `rows` 键，`resolve_repair` 会把**量到的** `rows="0"` 抄进去，`int(rows)>0` 因此失败。table_valid 修好后 `rows` 量到 35，所以它今天不再是拦路原因；但「一旦真出现 0 行就无法自动补齐」这条路径依旧存在，需要单独修。
2. **`unlinked` 只看 URL 形状，不看它是不是条款**：#22 `https://www.multpl.com/`、#30 `https://finviz.com/`、#31 `https://www.usa.gov/`、#35 `https://www.wsj.com`、#27 `https://api.congress.gov` 都是站点首页，§1.2 自己已经声明这些链接「原样取自其 `website` 字段，不代表已取得或审阅条款」。也就是说这一格存在**假绿**风险：全部行「合规」但其中若干行的条款其实从未取得。属主要定的是「条款链接」的最低语义（必须是条款页？还是允许首页 + 状态标注？），这是新的属主问题，替代了那个被证伪的旧问题。

于是 Wave 20 §5 的「属主决定」清单要改口径：AC-1\|08 不再是数据缺口，但它换来一个更小的问题（条款链接语义）与一个探针待修项（`repair.rows`）。AC-1\|08 的棘轮入账同样只能来自 CI 自己的测量（dispatch 作业在本次修复后重出），不在本地钉。

### Wave 22：test-cov 从 14 红到 3 红，最后一条红原来是单写者切换的可见端

四个 PR 合入 OpenData `dev`：

| PR | 合入 SHA | 内容 |
| --- | --- | --- |
| [#177](https://github.com/cloudQuant/opendata/pull/177) | `d781d189` | 六个测试文件的过期钉 + A2 清单改为按登记基线解析 + `/reviewed/*` 的测量写进守卫 docstring |
| [#178](https://github.com/cloudQuant/opendata/pull/178) | `397a8508` | C150 的 gitleaks 正则镜像进 AC-1\|09，并按 dispatch 作业 `41379944842` 的产物入账（16 格/17 钉 → 15/16，其他格 family hash 零漂移） |
| [#179](https://github.com/cloudQuant/opendata/pull/179) | `a4fb18fd` | `test_process_executor` 一族改为事件驱动；根因是夹具的假子进程在未被调度的线程里 `os.dup` 一个**已关闭**的 fd（产品写完命令即关闭，`process_executor.py:608`），于是退出从不上报、父进程烧完 deadline |
| [#180](https://github.com/cloudQuant/opendata/pull/180) | `4d972657` | AC-1\|08 的列名改为「恰有一列以 `复核日期` 结尾」并重新键入规范名，并按 dispatch 作业 `41387268027` 入账（15/16 → **14 格/14 钉**） |

AFI 侧：#256 以 `ef425cdf` 合入（Wave 20 + 21 文档）。

#### 1. CI 读数（以作业 id 清单表述）

| 作业 | 树 | 结果 |
| --- | --- | --- |
| `125045929651` | #164（首次执行 test-cov） | 14 failed / 35419 passed，1047.60s，覆盖率 88.33% |
| `125070735018` | #177 首个 head | 9 failed / 35424 passed，795.19s |
| （PR #179）`41386120435` | dev `d781d189` + 事件化 harness | **5 failed / 35428 passed**，1405.37s；`test_process_executor` **全族消失** |
| （PR #180）`41390775162` | dev `397a8508` + 判据修复 | **3 failed / 35430 passed**，809.70s；12 个成员依次绿到 `acceptance-probe-check`，说明 14/14 的账本与真实 gate 形态一致 |

本地在合并后的 `4d972657` 上对六个受影响文件复测：`309 passed, 2 skipped`，且
`verify_no_akshare.py` 仍是 `OK: 1069 file(s) walked … frozen baseline: 9`（重钉摘要在 rebase 时按
#178 之后的字节重算：`6c71ae68…` → `0e0044c5…`，含品牌行 234==234、akshare 163==163、openbb 113==113）。

#### 2. 「一族恒为 3、但名字每次换一个」是怎样被抓住的

三次读数里 `test_process_executor` 都是 3 条，而参数化 id 依次是
`messages7/13`（14 红）→ `messages5/10`（9 红）→ `messages8 + no_bytecode_flags`（7 红）。**计数不变、身份漂移**
这个形状本身就排除了「机器偶尔慢一点」的解释，指向一个必然发生但被 deadline 掩盖的缺陷；把三次 id 对齐之后，
根因（closed-fd dup）才被复现出来。若只报「14 → 9 → 7 → 3」，这条会一直被当成负载噪声推后。

#### 3. 最后一条红不是遗漏，而是单写者切换的可见端

`tests/test_frontend_endpoint_contract.py` 的四条 `/reviewed/*` 在 dev 上仍然红，本轮读到了它**为什么**红：
`deploy/afi204-reviewed/README.md` 明确写着 reviewed 运行时按设计尚未在生产装配——「production composition root
仍需构造 task catalog、engine、dispatcher、worker SPI 与 role plan」，而未来的部署必须先「declare the sink IDs
owned by that reviewed app，**stop legacy writers for those sinks**」再启用 unit，且
「Do not run this alongside legacy collectors writing the same sink」。`nginx.conf` 里也没有任何 reviewed
location（只有 `:81` 的 `location /api/ → backend`）。

因此这不是「忘记挂载」，而是**单写者切换这一验收面尚未发生的另一端**：提前把 router 挂进 `main.app` 会让
`get_reviewed_runtime` 答 503，门禁转绿而后台页照旧不可用，同时诱导人在 legacy 采集器仍在写的情况下启动第二个写者。

连带后果必须说清：`make gate` 是 fail-fast，`test-cov` 排在四个前端成员之前，只要这条还红，
`frontend-lint / frontend-typecheck / frontend-collection / frontend-test / frontend-e2e` 就**永远不会被测量**；
本机也无法替代（`frontend/node_modules` 不存在，网络不足以安装）。所以属主实际是三选一：
(a) 把后台页在运行时未装配时改为显式「未启用」（前端小改动，同时四条声明消失，守卫自然绿）；
(b) 执行单写者切换并装配 reviewed 运行时（真正的收口，但那是本迭代最大的未闭合面）；
(c) 让这条红继续作为提醒，同时接受前端五个成员在 CI 里持续不可测。

#### 4. 共同非声明

本轮所有绿都在 **code/offline 与 CI 平面**：账本从 17 钉降到 14 钉是两次真实收口的入账（AC-1|09、AC-1|08），
不是把红格子改名；#179 改的是测量方式，产品的 60s deadline、可杀性与栅栏传播未变。AC-5\|03 /
AC-16\|05 / AC-16\|06（9 处上游来源身份字面量）、AC-4\|01、AC-16\|08 措辞、AC-17\|07 分母、
`repair.rows` 不可达、`unlinked` 只看 URL 形状的假绿风险，以及真实源、生产 MySQL/部署、影子对账、
单写者切换、自然周期、全 A 权威域、逐标的完整历史、授权签发/吊销审计与报告门禁生产适配器**依旧未闭合**。
另需记录：本轮一次异常打印把 `Authorization: Bearer …` 带进了会话输出（`subprocess` 抛出时回显 argv），
该 PAT 应立即轮换；后续脚本已改为 check=False 并屏蔽 argv。

### Wave 23：`make gate` 第一次整链变绿——但绿的是仪器，不是验收

合入记录（OpenData `dev`）：

| PR | 合入 SHA | 内容 |
| --- | --- | --- |
| [#181](https://github.com/cloudQuant/opendata/pull/181) | `b54ee558` | AC-1\|08 的 `repair` 配方原本在自己要修复的那种读数下不可达（`resolve_repair` 从**实测** facts 复制 `*key`，于是 `dated="*rows"` 继承了塌陷读数的 `rows=0`）；两个计数改为同指 `cited`。塌陷读数对照实测：dev 配方 → gap，本配方 → proven；健康读数两侧都 proven |
| [#182](https://github.com/cloudQuant/opendata/pull/182) | `49a5b4ea` | `/reviewed/*` 的决定：按 `deploy/afi204-reviewed/README.md` 所述，审核运行时**按设计尚未装配**（切换前要声明自有 sink 并停止这些 sink 的旧写入者），所以页面改为显式陈述「审核运行时未装配」，由 `VITE_REVIEWED_RUNTIME_ENABLED === 'true'` 控制（严格相等，未设置即失败关闭）；transport 是**搬家不是删除**（`git mv` 到 `frontend/src/reviewed/api.ts`），守卫反而变强（同一抽取器钉到 `opendata.api.reviewed_runs.router`、主平面不得出现 `/reviewed`、任何出厂构建不得打开该开关、反例固化为常驻用例） |
| [#183](https://github.com/cloudQuant/opendata/pull/183) | 待合 | 最后一条 test-cov 红的分诊与预算对齐，见第 3 节 |

AFI 侧：#257 `02cdd029`（Wave 22 文档，四条工作流全绿后合入）。

#### 1. 门禁整链首次全绿，并且前端平面第一次被测量

dev `49a5b4ea` 的 push 作业 `41403148134`：**`make gate` PASSED**，18 个成员依次执行完毕——

```
brand-check, zero-dep-check, secret-check, ledger-check, evidence-traceability, js-points-check,
loguru-check, a2-check, published-openapi-check, quality-ratchet, public-api-quality,
acceptance-probe-check, test-cov,
frontend-lint, frontend-typecheck, frontend-collection, frontend-test, frontend-e2e   => PASSED
Required test coverage of 84% reached. Total coverage: 88.33%
after-gate shallow=false head_commits=992 all_commits=1044
```

这里有两条必须写清的性质。**其一**，后五个前端成员在本迭代里**从来没有被执行过**：门禁 fail-fast，`test-cov` 排在它们之前，只要套件红着它们就轮不到，而本机也测不了（`frontend/node_modules` 不存在，网络不足以安装）。**其二**，因此 #182 的 TS/Vue 改动在合入时是**明确标注 NOT VERIFIED** 的——现在由 CI 判定为绿（eslint、`vue-tsc`、vitest 三个新增未启用用例、collection、Playwright 全过），这才第一次有了证据；本条记录的顺序很重要：先声明未验证，再由 CI 补上，而不是把未验证说成已验证。

`test-cov` 的完整轨迹（以作业 id 清单而非计数表述）：14（`125045929651`，本成员史上首次执行）→ 9（`125070735018`）→ 5（`41386120435`）→ 3（`41390775162`）→ dev 上 2（`41393936947`：`/reviewed` 契约 + sina e2e）→ 1（`41397694887`，只剩 sina）→ **0**（`41403148134`）。覆盖率始终 88.33%，阈值 84 从未是障碍。

#### 2. 绿的是仪器一致性：账里仍有 14 格 stale-proof

门禁绿与验收之间存在一条硬差距，就在 `docs/quality/acceptance-gate-ratchet.json`：**14 格 / 14 钉**，每一格都是 `ledger_state = proven` 而探针当场读出 **gap**，被属主裁定为「已知红」入账：

```
AC-4|01, AC-5|03, AC-5|07, AC-8|02, AC-11|04, AC-16|05, AC-16|06, AC-16|07,
AC-16|08, AC-17|02, AC-17|03, AC-17|05, AC-17|06, AC-17|08
```

这些格子的性质在 Wave 20 §5 已分类：一部分是纯代码/登记工作（可继续收口），一部分需要活的 MySQL 或新鲜 clean-venv 证据轮（AC-11|04、AC-16|07、AC-5|07、AC-17|06，其中后两格本身带**时效门槛**，过期就红，属可续期证据而非永久收口），其余属属主裁定（AC-5|03、AC-16|05/06 的 9 处上游来源身份字面量、AC-16|08 的免责声明措辞、AC-4|01 按字面拼写判关节）。入账一次红不等于验收一次绿——**迭代 204 的「开发」面至此可以自称 CI 平面全绿，「验收」面没有闭合。**

#### 3. 最后一条红的分诊：parked 的猜测是错的，但它掩盖了一个真的产品限制

`test_sina_fzb_recorded_transport_e2e` 在五次读数里出现两次。上一轮把它 park 成「25s 子进程 vs `lease_ttl=3s`，慢而活的 worker 会被判死，需属主决定」。**这个说法被实测推翻**：父进程在孩子活动期持续续租（`opendata/pipeline/process_executor.py:615-617`、`655-657`），实测 200–223 次心跳、最大间隔 idle 264ms / 72 hogs 时 1008–1329ms，而租约是 3000ms——孩子从未危及租约。

真正无法续租的是**围栏发布提交**：`commit_result` 独占该 worker Engine 的唯一连接（`create_worker_engine` 钉 `pool_size=1`，`opendata/reviewed_worker.py:288-291`）并在提交里重读进入时抓到的到期时间（`opendata/pipeline/run_ledger.py:586`、`601-602`），所以 **`lease_ttl` 单独为那 103 行写入封顶**。实测 `commit_result`：idle 0.74s → 36 hogs 2.25s → 72 hogs 5.05–6.88s，而最后一次续租只比它早 0.32s。72 hogs 时 3s 租约到期，成功转换回滚，而记录失败的 `fail` 转换同样需要活租约（`run_ledger.py:745-759`），于是运行留在 `running`。

#183 的做法是把**测试**预算对齐到同族用例早已测过并采用的数值（60s 子进程 / 60s 租约，`tests/test_sina_fzb_process_job.py:130`、`:907`），不降任何断言、不动产品文件，并且反例非空转：把 `heartbeat` 改成永不续租 → `2 failed`，报 `_LeaseLostError`。复现门槛也要诚实写下：≤0.7× 超订在本机从不失败（serial 7.48/7.71/7.66s、12 hogs 14.45/12.00s、`-n 4` 组合 227 passed），只有 72 hogs 才复现；修复后 72 hogs 十连过（45.41–93.57s），但其中一次在输出结果前失败且未捕获错误码、其后 18 个样本未复现——记为 NOT VERIFIED，不抹掉。

**被这条红掩盖的真实产品限制仍然开放**，且没有被我悄悄选择方案：在足够超订的 runner 上，一次**成功**的发布可能回滚并且无法记录自己的失败，运行卡在 `running`。围栏发布窗口除了 `lease_ttl` 之外不受任何东西封顶，因为它持有唯一连接且写入期间不能心跳，而事后记失败又需要同一条已过期的租约。属主三选一：(1) worker Engine 允许多连接或改用第二条连接续租；(2) 给发布本身设语句级超时并由不需要过期租约的监督者带外记录失败；(3) 把「过期后仍 `running`」当作预期状态，配一条文档化的对账清扫。三条都触及单写者、worker 可杀性、栅栏传播这些本迭代保护的不变量，所以是决定而不是清理。

#### 4. 共同非声明

本轮的绿全部落在 **code/offline 与 CI 平面**：门禁全绿说明仪器之间一致、套件不再失败，**不说明任何数据来自真实源、不说明部署形态可用、更不说明自然周期成立**。上面 14 格 stale-proof 是入账的已知红；AC-5|03 / AC-16|05 / AC-16|06、AC-4|01、AC-16|08、AC-17|07 分母、条款链接语义、fenced 发布续租限制，以及生产 MySQL/部署、影子对账、单写者切换、自然周期、全 A 权威域、逐标的完整历史、授权签发/吊销审计与报告门禁生产适配器**依旧未闭合**。#182 让页面停止发出无人应答的请求，是把它原本无法工作的事实说清楚，不是把审核运行时上线。

### Wave 24：六格由 CI 度量入账（14 钉 → 8 钉），AC-17|08 的「0」先被量化再被相信

#### 1. 入账：14 钉 → 10 钉，读数来自 CI 自己的产物

OpenData `dev` 现在读 **10 items / 10 pins**（`5fc3615f`，PR #185）。入账依据是 dispatch 作业
`41783225848`（head `e9a716b7`）产出的 `--sync-ratchet` 产物，逐字为：

```
CI items: 10 pins: 10
tree items: 14 pins: 14
closed vs tree: ['AC-17|02', 'AC-4|01', 'AC-5|07', 'AC-8|02']
new vs tree: []
other family-hash movement: {}
```

也就是说这四格之外**没有任何一格的族哈希动过**，入账不是「顺手多关了几格」。合入后 PR 门禁作业
`41787031996` 与 dev push 作业分别 PASSED，这条记录写的是：绿的是仪器之间一致。

四格各自的性质必须分开写，不能合并成「修好了」：

| 格 | 真实原因 | 平面 | 会不会再红 |
| --- | --- | --- | --- |
| AC-4\|01 | 判据按字面量 `with self._semaphore_for(host)` 找闸门，而代码在 `7ee1ef25` 后改成先绑定再在调用处进入（`http_client.py:1868/1887` 绑定，`:1107/:1147` 进入） | CODE/OFFLINE | 否（改为 AST 判别，见下） |
| AC-8\|02 | `lifespan` 在 `1ee7be9c` 变成委派包装，守卫本体仍在 `_existing_lifespan` | CODE/OFFLINE | 否 |
| AC-5\|07 | 24 小时时效窗过期；C89 用同一棵树重扫（`source_sha256` 与归档逐字相同）续期 | CODE/OFFLINE 的**时效证据** | **会**（可续期，不是永久收口） |
| AC-17\|02 | 42 处 `# nosec` 只写规则号不写理由，另有 3 处豁免 suppressing nothing | CODE/OFFLINE | 否 |

AC-4\|01 的新读法不是把判据放宽，而是把它写得更严：`per_host_semaphore_entered()` 用 AST 判断「有没有真的进入」，
允许直接 `with`、同函数内绑定后进入、以及经一层 `@contextmanager` 委托（该委托必须 acquire→yield→finally
release）；**只绑定不进入仍然判红**。反例实测：赋值不进入→否；`._semaphore_for` 从不调用→否；回到
`7ee1ef25^` 的旧写法→是；把当前树改回旧写法→是。AC-8\|02 同样只跟进**一条**可静态解析的 `lifespan` 委派，
且旗标表达式逐字节相同，所以「委派里悄悄丢掉检查」照样判红。两格都没有动阈值、没有动判据语义。

#### 2. AC-17|08：先把「0」的覆盖面量出来，再决定能不能入账

这一格要求 `docs/evidence/C44/shell_audit.py` 的四个面同时为 0。本轮把可数的一族清掉了，但**没有**在它读 0
之后就入账——原因见 §3。

- PR #184（合入 `ba1e41b8`）：定义抄写 46 → 19，恒真断言 1 → 0。
- PR #186（`d6b64b2e`，在跑）：定义抄写 19 → **0**。我在rebase 后的树上独立复算，读的是脚本自己打的
  摘要行而不是 `HIT` 计数（该脚本在摘要之前还会为反例打印若干 `HIT`，用 grep 数会多数）：

  ```
  shell_count[self-reference] = 11      shell_count[vacuous-assert] = 0
  shell_count[constant-shell] = 0       shell_count[source-form-check] = 0
  files_scanned = 670                   VERDICT shells=found t1=met exit=1
  ```

  19 条替换都是「让断言能因产品回归而变红」：页/字节/窗口上限改判边界行为（4,000 条翻页通过、4,001 条
  在第 1 次请求就抛 `FMP_PROVIDER_LIMIT_VIOLATION`；3,650 天可、3,651 拒），身份串改判注册表解析结果，
  凭据环境变量名改判真正发到线上的 `Authorization` 头。五处反例在 /tmp 的副本里改动产物字节后确实变红。
- 自指一族的问题在**判据本身**：`self_reference_findings()` 扫整条 assert，只要同句里既出现本地计算 helper
  又出现生产符号就开火。它既产假阳性（现存 11 条全是「用 builder 造输入 + 写死的期望」这种形状），又漏掉
  真正危险的 `expected = helper(...)` 先赋值再比较，以及只经属性链触到生产的断言。
  改成按 `ast.Compare` 逐操作数判定后：11 → 0，同时**新抓到 6 条旧规则看不见的真自指**
  （`tests/test_ecb_series_parser.py:192/238/239/307` 的 `_key` 重新拼了生产侧的 series-key 格式；
  `tests/test_source_grant_provisioning.py:564-565` 的 `_datetime_to_epoch_us` 重跑了生产侧的换算），
  这 6 条已按独立期望重写。反例表在 `docs/evidence/C44/README.md` §十 +
  `tests/test_shell_audit_self_reference.py`（17 passed）。

#### 3. 为什么 AC-17|08 现在还不能入账：把「盲区」变成可数的量

规则读 0 之后，我没有直接派 sync 作业入账，而是先用一次性分支把四类被规则刻意忽略的形状量了出来
（opt-in 旗标，默认输出与出货版逐字节相同）：

| 形状 | 命中 | 深读样本 | 其中真自指 | 主要构成 |
| --- | --- | --- | --- | --- |
| A 期望值取自本地重算对象的成员/下标 | 14（2 文件） | 6 | **0/6** | 读假客户端的 `calls[0]["url"]`、读 sha 钉住的录制夹具 |
| B 期望值经生产常量/算术 | 38（25 文件） | 10 | **2/10** | 合法差分（`fencing_token + 1`、`pytest.approx(close * 0.8)`）；真问题见下 |
| C 经 fixture/conftest 间接可达 | 0 | 3（放宽探针） | 0/3 | `set(ameribor_fixture)` 这类是输入 |
| D 无比较的断言 | 142 | 8 | **0/8** | 70 条是 `isinstance` 契约检查，28 条是真值判断 |

结论不是「盲区很大所以放弃」，也不是「盲区存在所以读 0 算数」：**194 条里只有 1–2 条是真自指**，
其中危险的形状是「期望值由被测试对象自己的方法算出来」——
`tests/test_c85_runner.py:160` 的 `pipeline.invalidated == [pipeline._pipeline_id(WINDOW)] * 2`，
以及 `tests/test_run_ledger.py:360/409` 把租约政策原样复述成 `NOW + timedelta(seconds=12)`。
这类断言在生产算法改动时**不可能变红**，正是 AC-17|08 要抓的空壳，所以我把它单独提升为默认判据的一臂，
并修掉被它点到的用例；A/C/D 三臂不提升——把它们变成默认只会把「isinstance 契约」和「token+1 顺序检查」
这两类有用断言逼成删除，属于用仪器把人逼向假绿。

**因此本波明确不入账 AC-17|08**：登记里这一格继续留在 10 钉内，等「生产自证期望」这一臂落地、
且 #186 与规则分支都在 `dev` 上之后再由 CI 度量决定。把四个面读 0 当成验收完成，就是我这一轮要防的那类假绿。

#### 4. 对迭代计划的一次修正：验收面需要的是环境，不是更多工时

我用只读方式盘了本机能不能产出这些证据，结论直接写进计划：

- 本机 MySQL 跑在 127.0.0.1:**13306**（`opendata_ci`）与 **13307**（`opendata`、`opendata_data`、
  `codex_iter191_local`），**没有任何分区表，也没有任何 `dwd*` 表**；不存在 `akshare_data` /
  `ai_for_investor` 这两个 AFI 运行时库。仓库里也没有 `OPENDATA_*_MYSQL_DSN` 这类变量，DSN 由
  `MYSQL_*` / `DATA_MYSQL_*`（默认 localhost:3306）在 `opendata/core/config.py` 组装。
- 于是 **AC-11|04 在本机不可能续期**：它要的 `window-pruning-explain.txt` 必须带
  `query_module_sha == sha256(opendata/pipeline/query.py)[:12]`（归档钉 `2f73f2bf9d44`，当前
  `e3c7ecf301dd`），而那条 EXPLAIN 问的是活的分区表。同理，影子对账、单写者切换、自然周期、
  全 A 权威域、逐标的完整历史、授权签发/吊销审计、报告门禁生产适配器**都不在这台机器能证明的范围里**。
  这些不是「再努力一点」的差距，是平面缺失：要关它们需要一次真实部署与足够长的日历。
- **AC-17|06 另有一道结构性障碍**：`COV_STAMP_DIR` 被硬编码成 `docs/evidence/C85`，而 `make gate` 把
  `acceptance-probe-check` 排在 `test-cov` **之前**，所以 CI 在读这一格时盘上根本没有当次
  `coverage.xml`——要么改 gate 内成员次序（会改变门禁形状，属主决定），要么让探针承认「归档与 HEAD 同树」
  即足够。阈值我没有动。
- **AC-17\|05 的红九成是环境，不是一切都还没做**：`port_replay()`（探针 `:3287`）调
  `scripts/codemod/report_port.py` 时不传 `--upstream-repo`，于是回退到
  `port_module.py:58` 的 `REPO_ROOT.parent / "akshare"` —— 维护者笔记本旁的一个检出，CI 永远没有。
  `collect_drift` 又不调 `verify_upstream`，缺上游不会大声失败，而是每条锁记录变成一句
  「upstream file … disappeared upstream」：同一格在笔记本上是 0 待办 / 327 行逐字一致，在 CI 上是
  `report_exit 1 / rows_total 0 / render_matches_archive no`。PR #191 按 OpenBB 已有的路子加同一条缝
  `OPENDATA_AKSHARE_UPSTREAM_PATH`（只在 `port_module` 一处解析，四个调用者共享），workflow 从
  `upstream.lock` 自己读 URL 与 commit 并断言抓到的 HEAD 等于锁内 commit。本机用
  `git archive c4f6a631…` 只读取出锁钉的树实测：327 files / 0 TODOs / 渲染与归档
  `docs/port-report.md` 逐字节一致，重放面全绿。
  **但这一格仍判 gap，只剩一条**：`upstream.lock` 记 10 条人工改动，而 `THIRD_PARTY_NOTICES.md` 与
  `port_module.MANUAL_EDITS` 各 9 条，差的正是 `_vendor/akshare/__init__.py`（锁里的理由写的是
  「Generated lazy flat facade …」）。两种改法都能让数字一致，但它们断言的事实不同——「补登记」等于说它是
  一次人工偏离，「取消 manual_edits 标记」等于说它是 codemod 自己生成的必然产物。这是属主对三处登记语义的
  裁定，本轮一处登记文件都没动，也没有入账。

- 本机**可以**产出的是 AC-16|07：两个依赖面恰为 `.[web,dev]` 的干净 venv，在没有源码包的验证目录里跑
  `pytest tests -m 'integration and not e2e' --no-cov -o addopts= -v`，归档 `ARCHIVE_ROUND` 与目录名一致。
  这一条在写 C151 轮次（进行中）。

对计划的改法：把「迭代 204 开发完成」与「迭代 204 验收完成」正式拆成两个判据——前者等于 CI 平面全绿 +
棘轮里可代码收口的格子清空；后者需要 DEPLOYMENT / NATURAL_CYCLE 证据，属主必须先给环境。

#### 4b. CI 平面上冒出来的两条负载敏感红，都是仪器/框架问题，但其中一条藏着产品缺陷

门禁转绿不是终点，同一条链上又出现两处「只在跑得慢的时候红」：

1. `test_partial_ipc_frame_does_not_block_parent_deadline_or_cleanup` 报
   `ValueError: invalid literal for int() with base 10: ''`（作业 `41800821881`，35,437 项里 1 项）。
   根因在测试自己的同步方式：`_ReadinessClock` 用 `marker.exists()` 认定 worker 已起，而子进程用
   `Path.write_text()` 发布 pid —— 该调用先 `O_TRUNC` 打开再写，中间存在「文件已存在但为空」的窗口。
   改成先写同目录兄弟文件再 `os.replace()` 原子替换，窗口消失。反例可复现：注入 20ms 延迟后，
   旧写法 400 轮里 **398 轮**能被读到且不可解析，新写法 **0/400**（`/tmp/marker_race_demo.py`）。
   #189 合入 `f7108c61`，未动任何断言、超时或产物代码。
2. `frontend-e2e` 里 `test_real_browser_download_chain_against_owned_mysql` 报
   `assert set() == {91, 92, 93, 94, 95}`（dev 作业 `41798566273`）。读代码定位到两件事：
   **其一**，用例在 `:1500` 先断言录制到的来源调用，之后才在 `:1728/:1764` 看 Playwright 退出码，
   而 trace 由 `afterEach` 无条件写出，所以任何浏览器/基础设施中断都会伪装成「产品没打到来源层」——
   这是判据掩盖，#190 把它改成先验基础设施健康（非零退出必须命中既有的
   `AC21 natural UI navigation failed` 标记，否则按基础设施失败报出退出码与脱敏输出），并要求正好 5 个 202。
   **其二**，路由在 `opendata/api/data.py:149` 用 `bg = asyncio.create_task(_bg_download())` 把任务只绑在
   函数局部变量上，而 CPython 明确说明事件循环对 task 只持**弱引用**——被回收就是「发了 202 但永远不干活」。
   #190 按仓库自己的既有做法（`api/pipeline.py:63` 的 `_TASKS` 注册表 + `services/scheduler.py:456-466` 的
   done-callback 释放）补上强引用，仍 202、仍同状态码、请求路径不新增 await。

两条都必须写清各自没有证明什么：#189 的反例是本机注入延迟得到的，不是 CI 现场；#190 的新用例断言的是
「注册表在飞行中持引用、完成后释放」这个不变式，而本机解释器（3.11/3.12）实测**不会**在 ready queue 里丢任务
（2,000 个无引用 sleep task 全部跑完），所以它不是丢任务的复现。`41798566273` 究竟是弱引用回收还是基础设施中断，
我没有证据去断言——区分两者的档案在那次作业的证据目录里，本轮只把「不能再被伪装」这件事做完。#190 的门禁作业
`41815883011` 全 18 成员绿，含 `frontend-e2e`。

#### 5. AFI 侧本轮状态（平面：CODE/OFFLINE + CI）

#264 已合入 `40e6808a`：npm audit 基线在四个依赖 bump 合入后重新钉（`lockfile_sha256`
`9dd9c879…` → `4856e2f7…`，high/critical 两边都是 0/0），并且给 venv 缓存加了自愈——
`.venv/bin/pytest --version` 探测失败就整棵重建，因为还原出来的解释器是指向 setup-python 缓存的符号链接，
runner 小版本一动就会 `exit 127`，而 `actions/cache` 从不覆盖已存在的键。前端链（eslint / vue-tsc / vitest /
build / bundle 预算）在隔离的 `npm ci` 副本里跑通并留档：vitest 2176/2177，唯一那条失败的用例被证明是副本
缺 `../backend` 路径，不是产品回归。

#265（纯文档，更正验收基线）遇到一次与文档无关的红：`Backend - Unit Tests (py3.11)` 里
`tests/test_ai_research_holdout_worker.py::test_cross_worker_crash_after_checkpoint_recovers_without_redispatch`
在 42 分钟的 xdist 全量里失败于 `assert 'PASSED' == 'FAILED'`，同一 run 的 py3.12 腿通过，本机单跑该文件
13 passed（3.13、serial、`--no-cov`）。#265 重跑后同一 head 变绿并合入 `0080d329`；但**没有把它写成「已修」**，
而是把根因读清楚了：

- 该用例唯一的 PASSED 通路是 `holdout_worker.py:359-385` 的 `except ValueError` 分支——它只接受
  `HOLDOUT_FINALIZE_LEASE_EXPIRED` / `_STALE`（由 `holdout_finalize.py:1993-1994` 与 `_second_authority_fence`
  2056/2065 抛出），随后走 observed-recovery 就地结算成 PASSED；也就是说**模拟崩溃根本没发生**，
  于是没有失败可记。
- 触发条件被算出来了：1 秒租约在「派发 CAS 与 checkpoint 提交之间」到期。实测该段只要 ~20 ms，
  所以必须约 50 倍膨胀才会命中；纯加负载复现失败（5 次 `-n 4` 全绿、14 hogs + `--cov` 15 次全绿），
  而注入 `_StallAfterResultJournal(1.05)` 后**逐次**复现出 CI 的那条签名。
- 污染被结构排除：`tests/conftest.py:25,64-70` 是进程内 in-memory SQLite + StaticPool，逐用例重建。
- 修法不是加大超时：把崩溃臂与恢复臂解耦（崩溃臂用不会到期的租约，恢复臂用**确定性**把租约置为过去，
  走数据库时间而不是 `sleep(1.1)`），四条断言一条不减。同族脆弱性在本仓早有记录，见
  `tests/asset_research/test_task_runner.py:407-410` 的注释。
- 分诊同时暴露一条**必须交给属主**的产品事实：`holdout_worker.py:359-385` 允许一个已经丢租约的 worker
  在同一次 `run_once` 内自己结算运行（由数据库时间 CAS 与 generation bump 双重栅栏：
  `holdout_finalize.py:1560/1588`、`holdout_finalize.py:1507` + `holdout_claim.py:585`，所以不会二次结算）。
  如果本迭代保护的不变量是「丢租约的 worker 不得结算」，那这是一处被代码接受的例外，旧用例看不见它。
  本轮把它写进 §7 的决定队列，不代替属主判定。

#### 6. AC-16|07 的干净环境证据已经真的重跑过（待入账）

C65 那一轮的留档只点到 9 个模块，而 `integration` 标记集现在是 10 个，所以 `archive_blind=1` 把这一格判红——
这是**刻意的棘轮**：扩大标记集必须重跑干净环境证据，否则正向证据会随着分母膨胀悄悄变成部分证据。
PR #187（`docs(evidence): C151 …`）交的是两个从零建的 venv（依赖面恰为 `.[web,dev]`，`akshare`/`openbb`/
`openbb_platform` 三者 `find_spec` 全 absent，`pip check` 通过），在**移除 `opendata/` 源包**的验证目录里
各跑一遍 `pytest tests -m 'integration and not e2e' --no-cov -o addopts= -v`：

```
A (clean-a): 229 selected → 229 passed / 0 failed / 0 skipped, 196.93 s → CLEAN_A_RUN_EXIT=0
B (clean-b): 229 passed / 0 failed / 0 skipped, 161.58 s                    → CLEAN_RUN_EXIT=0
archive_round=C151  archive_self_written=yes  archive_absent=yes  archive_blind=0  marked_units=10
VERDICT AC-16|07: proven（本机读数；入账仍要等 CI 的 --sync-ratchet 产物）
```

没有裁剪、没有 deselect、没有 xfail、没有改用例；留档正文含全部 458 条逐用例行。诚实的限制也要写下：这台机器
的开发解释器本来就没有那两个包，所以「干净」在本机既是钩子强制的也是环境巧合，CI 自己的解释器才是独立读数。

入账确实发生了，而且是由门禁自己叫出来的：#187 的第一次门禁作业 `41796550488` 红在
`棘轮收口（AC-16|07 / stale-proof）：基线钉的这条 finding 这一遍没有再出现`，也就是 **CI 当场量到这一格已经过**，
要求显式重钉。据此派 dispatch 作业 `41796605842`，产物读数为
`closed = [AC-16|07]、new = []、other family-hash movement = {}`，逐字应用到分支后门禁转绿，合入 `db927f56`。
账本自此 **9 格 / 9 钉**。这条流程本身就是仪器的一个证明：它不仅能钉住红，也能自己叫出「这一格该释放了」。

#### 7. 属主决定队列（本轮没有替任何人做决定）

| # | 决定 | 本轮已做到 | 还差什么 |
| --- | --- | --- | --- |
| 1 | fenced 发布续租窗口：成功的发布在高负载下可能回滚且无法记录自身失败（卡 `running`） | 机制已量化并复现（72 hogs 才出现） | 三选一：多连接/第二连接续租、发布语句级超时+带外记录、接受 `running` 加对账清扫 |
| 2 | `条款链接` 的最小语义 | 已证实现有 `unlinked` 只查 URL 形状 | 决定「首页链接」是否算权利行，否则 AC-1\|08 有假绿风险 |
| 3 | AC-16\|08 免责声明措辞 | 定位到 README:171-180 与判据字面不一致 | 采纳哪一句：改 README 还是改判据（都不动阈值） |
| 4 | AC-17\|07 的分母 | 已证明 PR 跑与 push 跑量的是不同总体 | 本差分母还是全仓 A2 分母 |
| 5 | AC-5\|03 + AC-16\|05 + AC-16\|06 是同一个决定 | 定位到 `1ba6d7d9` 把 9 个新串塞进 baseline 而未裁定 | 注册为来源元数据，还是改名 |
| 6 | `make gate` 是否继续 fail-fast；`acceptance-probe-check` 与 `test-cov` 的次序 | 已证明 AC-17\|06 在现行次序下不可能读活 | 次序或「归档同树即足够」二选一 |
| 7 | AFI 前端 leg 是否设为 required check | 已证明人可以让门禁绿着合进去 | 分支保护改动属维护者 |
| 8 | PAT 轮换 | 已提醒（一次异常把 argv 暴露到终端） | 属主执行 |
| 9 | 丢租约的 worker 可否自己结算 | 机制、栅栏与不可复现性已量化（§5） | 判定「允许并补文档」还是「禁止并改产品」，两者都不能用加大超时蒙过去 |

#### 8. 共同非声明

本波所有绿都落在 **CODE/OFFLINE 与 CI 平面**：14 → 8 钉是六次入账，其中 AC-5\|07 是 24 小时时效续期，
会再红；AC-17\|08 四个面读 0 之后**故意不入账**，因为要先确定那个 0 覆盖到什么。#184/#186/#187 与规则分支
都没有真实源调用、没有生产部署、没有经历自然周期，也就都不能被引用为「迭代 204 验收完成」。

真实需要环境的面按 §4 已被证明**不在这台机器可证明的范围内**（AC-11\|04 也再次由 CI 自己的判词确认：
「窗口本身是实测绿的……缺的是留档正文的 query_module_sha 和当下的查询层代码对不上」）：生产 MySQL/部署形态、影子对账、单写者切换、
自然周期、全 A 权威域、逐标的完整历史、授权签发/吊销审计、报告门禁生产适配器、AC-11\|04 的活分区表 EXPLAIN、
AC-17\|06 的当次 coverage 归档。要关这些，需要属主提供部署与日历时间，而不是更多代码。

### Wave 25：把「还剩 8 钉」逐项变成可判定的三类：环境、属主裁定、仪器缺陷

Wave 24 结束时账上是 8 格 / 8 钉。本轮不猜它们属于哪一类——逐格读出判据要求的每个面、跑一次单格度量、
再用能落地的改动去验证归类。三条 PR 在跑（#191 已合入 `58e14c54`，#192、#193 待门禁）。

#### 1. AC-17|05 的最后一格红是**登记缺项**，不是政策分歧（已改，PR #192）

#191 把上游检出送进 CI 之后，这一格只剩一句自陈：三处人工改动登记 `upstream.lock` 10 条 /
`THIRD_PARTY_NOTICES.md` 9 条 / `port_module.MANUAL_EDITS` 9 条，不一致 1 条。对三本账做集合运算，
差集恰好是 `__init__.py` 一行。它不是「要不要算人工改动」的分歧：`upstream.lock` 早已写
`manual_edits = true` 并带上 `LAZY_VENDOR_FACADE_MANUAL_EDIT_REASON`，
`migrate_provider_layout.py:982-984` 在生成时就是这么声明的，而
`docs/evidence/C74/README.md` + `ac2-case-ledger.json`（`360c61dd`，2026-10-14）已经把生成式惰性门面
判为「可登记的偏离」。缺的是两本账没同步。

改法只登记、不改行为：`MANUAL_EDITS` 加一条 `transforms=()` 的条目（`apply_manual_edits` 遍历 transforms，
空元组不可能重写字节；根包在 `report_port.py:266`、`port_module.py:798` 又都在 `port_source` 之前被特判），
`THIRD_PARTY_NOTICES.md` 补第三小节并把「分两类」改成「分三类」。实测它既无效又有效：
重放仍 `327 files, 0 pending TODOs`、渲染与归档 `docs/port-report.md` 逐字节一致，
而 `--item 'AC-17|05'` 从 gap 变 **proven**。
反向方案（把锁里的 `manual_edits` 改成 false）被证据否决：它会与 `report_port._registration_todos`、
`tests/test_port_module.py:438-446`、AC2-04 的签名保真面（`ported_signature_fidelity.py:230`）以及
`provider_source_review_evidence_build.py:300` 对根文件的描述相互矛盾。

#### 2. AC-17|06 的 11 条红里，**8 条是仪器键解析缺陷**（已改，PR #193），剩下 3 类才是要人决定的

`_cov_relative` 把归档报告里的 `<source>`（打标机器的绝对路径）拿去 `relative_to(root)`，
抛 `ValueError` 就退回 Cobertura 原始名。于是换一台机器读同一份归档：报告侧键是 `pipeline/x.py`，
A2 侧是 `opendata/pipeline/x.py`，两边永远连不上，被判的总体静默变成空集——
「总体为空然后 0/0」正是判据自己警告的那种假红。同一份归档、同一枚戳记，改前改后：

```
联接命中 0 → 290    解析起作用 no → yes
A2 新代码 0.00% / 0 文件 → 89.85% / 290 文件（门 85%）
戳记自合 0/5 → 5/5   分总体 2/8 → 8/8   点名根空总体 2 → 0   红灯理由 11 条 → 4 条
```

回退分支只在文件真的存在时才返回连接结果，连不上仍旧交回原始名，所以这一面仍是失败关闭方向；阈值与面名没动。
**这一格照旧判红**，且红得更有意义：归档报告只覆盖 2026-10-10 的 320 个文件而今天 A2∩`opendata` 有 710 个
（要一次真的 `make test-cov` + 重新盖章）、戳记源码树与 HEAD 不同树（每改一次 `opendata/` 就会重新老化，
是滚动续期）、CI 在读这一格时盘上没有 `coverage.xml`。第三条不是「再跑一次」能解决的：
`Makefile:223` 的 `acceptance-probe-check` 排在 `:225` 的 `test-cov` 之前，
而 `coverage.xml` 只由 `test-cov` 写出且被 `.gitignore:49` 忽略，全新 runner 上它必然不存在——
要么改门禁成员次序（改变门禁形状，属主决定），要么承认「归档与 HEAD 同树即足够」。
另有一条我一并记下而没有动手：`COV_STAMP_DIR` 硬编码 `docs/evidence/C85`（探针 `:14401`），
而 `coverage_archive_stamp.py:120-160` 是**就地覆盖**归档轮次——「续期」目前等于改写一轮历史证据，
这该由属主裁定，我不替它选。

#### 3. AC-17|03 的红是 `orphan_py`，而它是**属主裁定**，不是可以顺手改的数（不动）

单格度量里判据其余各半全绿（`ratchet` exit 0 / face none、`ruff_selfdev` 129 ≤ 148、`mypy_selfdev` 0、
`bandit_selfdev` 0、平面可见性 1616/1616 与 937/937、触碰即达标 1539↔1539），唯一红灯是
「全体 tracked `.py` = 2291，既不在被测根下也不在 A2 集里的 = 334」。我用离线脚本复现了这个数：
**334 个全部在 `docs/evidence/` 下**（Wave 21 的猜测方向正确，数字也对，不是仪器多数）。
`a2_check.py:83 ARCHIVE_PREFIXES=("docs/evidence/",)` 旁边就写着 *Owner ruling 2026-10-22 (option C)*，
所以「排除」本身是有据的裁定。三条看似可走的路都被证据挡住：按名字排除正是判据禁止的事；
把 `docs/evidence` 计入 A2 要先量代价——该子树 ruff 33 条 / bandit 43 条 / 4 个文件需要 format，
`129+33=162 > 148` 快照上限，会把债务面直接判红并触发一次「抬高」；改成 `SELFDEV_PATHS` 加根则撞上
`ratchet._scope_changes` 的「package added to scope」保护，且从此每写一轮证据都要交税。
现成的替代登记（`docs/quality/immutable-evidence.json`，343 个 `active_entrypoints`）覆盖这 334 个里的
**0 个**——那些路径根本不在里面。所以这一格要的是属主一句话：一次性归档仪器属不属于静态债务平面。

顺带记下一条仪器缺陷而我**没有**顺手修：`touched_dropped_selfdev` 是恒真的——`touched` 与 `a2_files`
取自同一个 `changed_files(baseline)`（`:3267-3268`、`:3228`），因此它按构造看不见任何被前缀排除的文件。
把它改成能看见，第一次读数就会把上面那 334 个全部报成「被排除的自研文件」，
直接与 2026-10-22 的裁定相撞。修它之前必须先有属主对 `orphan_py` 的裁定，否则就是把仪器改成
「要么假绿、要么必红」的形状——这属于决定，不属于清理。

#### 4. 本轮之后剩下的格与它们的性质

入账之后账本预期是 7 钉（AC-17|05 由 #192 释放）。逐项：
**环境类** AC-11|04（活分区表 EXPLAIN，本机已证不可产出）、AC-17|06（要 `test-cov` 重跑 + 盖章 + 次序决定）；
**属主裁定类** AC-5|03 / AC-16|05 / AC-16|06（同一件事：`1ba6d7d9` 把 9 个新串塞进 baseline 而未裁定）、
AC-16|08（README 与判据字面不一致的措辞采纳哪一句）、AC-17|03（本轮判定）；
**时效类** AC-5|07（24 小时，会再红，属可续期证据）。
这七格没有一格是「再写点产品代码」就能关的——这是本轮最重要的结论，也据此把计划里
「开发完成 ⇒ 验收完成」的隐含推论正式拆开。

### Wave 26（2026-11-05）：把四条缺口逐条变成裁定，并在 AFI 侧新开「采集脚本类型平面」

本轮起点是属主对四处剩余验收缺口的逐项裁定。三条给出可执行结论，一条被证明**不能由这台机器执行**；
另有一条属主在裁定过程中新提的要求（覆盖 ai-for-investor 里上千个采集脚本），已按实测展开成
一个新的类型平面。以下每条都标明它属于哪个平面。

#### 1. AC-16\|08：README 免责正文补回原句，本机实测 `gap → proven`（CODE/OFFLINE，PR #195）

判据要求 README 与 `docs/data-rights-registry.md` 两处**正文**都含字面句「不构成任何投资建议」——
不是看小节标题。登记表自 `4ee1bbca`（A0 建档）起一直带这句；README 的同一句在 `47ed8e59`
（2026-10-12，提交标题与正文都只谈 C98 门禁逐成员链证据落档）被换成
「通用数据说明不构成针对特定个人的投资建议；具体服务或输出的性质应按实际内容与适用法律判断」，
该提交没有为措辞单独留裁定。登记表自身第 125 行要求「本表任何结论变化必须同步更新 README 免责声明」，
因此这不只是判据字面不满足，而是两文档失同步。

属主裁定：**两句都保留**。README 现在先写「本项目不构成任何投资建议。」再保留 C98 的细化句，
既不撤回 C98 说过的话，也不删产品文档里的既有免责范围。单格实测（同一探针、同一棵树、改前改后）：

```
disclaimer_body_ok: no → yes      VERDICT AC-16|08: gap → proven
registry 侧两次均为 yes；LICENSE 首行与 BSL 四条款 4/4 两次均不变
```

入账不在这条 PR 里：CI 的门禁原文已经把话说了 ——
`棘轮收口（AC-16|08 / stale-proof）：基线钉的这条 finding 这一遍没有再出现——真修好了就 --sync-ratchet 把基线减下来`
（作业 `41932030079`）。已按协议对 `fix/od-disclaimer-wording-sync`（其树在 #192 合入后为 7 钉）
发 dispatch 作业 `41936345046` 取 `--sync-ratchet` 工件，工件到手才作为第二个 commit 落账，
期望账本 7 钉 → 6 钉。这台笔记本的读数不构成入账依据。

#### 2. AC-17\|03：属主选了「逐个登记」，实测这条路**不由本机执行**（不动，登记为属主动作）

裁定内容是用 `docs/quality/immutable-evidence.json` 逐个登记那 334 个 `docs/evidence/**/*.py`，
取代按前缀整片排除。核验结果是这条路对本机封闭，三处都是硬门：

| 门 | 位置 | 实测 |
|----|------|------|
| 清单自身被代码钉死 | `scripts/quality/immutable_evidence.py:32` `MANIFEST_SHA256_PIN`，`:362` 默认用它校验 | 现提交清单字节的 sha256 = `6edd0786c62b1e7a…` 恰等于代码钉；加任何一行即门禁红 |
| 候选身份只来自一份**不在仓库里**的分类 | `:24-26` 钉 `docs/evidence/C100/quality-scope-audit/immutable-wave9-exact5055/classification.json` 的 sha256；`:430` 要求类别恰为 `B` | `.gitignore:249` 整片排除 `/docs/evidence/C100/**`，本机没有这份 5055 行分类，也无法忠实重跑那次审计 |
| 批准要另一枚代码钉工件 | `:33-35` `APPROVAL_ARTIFACT_SHA256_PIN`，逐行需要 `receipt` 溯源指针与 reviewer/时间戳 | 模块 docstring 原话：「never discovers exemptions by directory or filename pattern」 |

所以这一格维持已入账红，并把属主要做的三件事记进 `SUBAGENT_TASKS.md`（重跑分类审计 → 出经审阅的清单与批准工件 →
更新两处代码钉）。我没有改用「新寄存器 + 改判据」来绕：判据原文禁止按名字排除，那等于把仪器改成
「要么假绿、要么必红」，属于决定而不是清理。

#### 3. AC-5\|03 / AC-16\|05 / AC-16\|06：按裁定维持已入账缺口（不动）

同一根因：零依赖扫描器的冻结基线里 9 条 string finding 全是产品身份串
（`adapter_id "akshare"`、`source_id "akshare.daily"`、`request_source` 默认值、
`STOCK_DAILY_EXECUTION_SOURCE_ID`）。裁定是维持现状、验收结论写明未闭合；既不收窄扫描器口径
（那等于放宽已勾的 AC-16\|05 AST 口径），也不改标识符拼写（那是跨仓 wire 契约与已发布 OpenAPI 的字面量，
也正是 C35 收口过的门禁空转）。

#### 4. #194：#189 只修了一半，CI 红的那条路径根本没被改到（CODE/OFFLINE 实测）

#189 把三个**进程内**发布点改成 write-then-rename，但红仍在 `test_timeout_before_ready_kills_descendant_in_launch_isolated_group`
（作业 `41855342867` / 作业 id `126662332027`：`ValueError: invalid literal for int() with base 10: ''`，1 failed / 35476 passed）。
读源码才看清：真正发布 marker 的是 `_write_test_worker()` **生成的子进程脚本文本**，五种模式全部还写着
`open(marker, 'w')`。守卫测试因此按 operand 判定，而不是按变量名：先对 pre-fix 树与新树各跑一遍同一检测器，

```
pre-fix   truncate-open 目标 = ['marker'] ×4 + ["'/tmp/…/pid'"]，os.replace 出现 False ×5
post-fix  每个模式都 = ['partial']，os.replace(partial, marker) True ×5
```

`before_command` 这一格正是第一版守卫（只认字面 token `marker`）会漏掉的形态——它 open 的是烤进源码的绝对路径；
这条是靠跑旧文件发现的，不是推理出来的。反事实臂把两种历史形态都断言在内，守卫不会靠看不见而通过。

#### 5. 新开：AFI 的 1108 个采集脚本进类型平面，顺带暴露 831 个真 bug（CODE/OFFLINE，PR #270）

属主在裁定 AC-17\|06 时改提了一条要求：「我希望能够覆盖 ai-for-investor 里面的上千个采集数据的脚本」。
盘点对象 `src/backend/app/data_fetch/scripts/`：1108 个 tracked `.py`（git 全跟踪、无未跟踪 .py）。

* 为什么此前不在任何门禁里：`src/backend/pyproject.toml:150` 的 mypy `exclude` 写着 `"scripts/"`，
  mypy 按**非锚定子串**匹配，把 `app/data_fetch/scripts/` 一起吞掉。`mypy app` 报 checked 740 files，
  另有 1108 个文件从未被类型面读过。ruff 侧本来已覆盖且干净（0 findings、1108 files already formatted）。
* 指过去实测 1103 errors / 881 files，其中 **831 条是同一个真缺陷**：每个脚本的 `main()` 都写
  `script = SomeScript(); script.run()`，而整条 MRO 里没有 `run`
  （`FuturesSpotSys` → `AkshareToMySql` → `MysqlBase` → `Database` → `object`，运行时 `hasattr(cls,'run')` 为 False），
  `app/data_fetch/` 全树 `__getattr__`/metaclass/`setattr` 注入 0 命中。生产掩盖它是因为调度器
  `app/services/akshare/script.py:379-383` 先解析 `fetch_data`，从不走 `main()`。
* 做法：831 个文件各改一行 `script.run()` → `script.fetch_data()`（831 个目标类都声明
  `fetch_data(self, *args, **kwargs)`，实测 831/831，调用形状不变；另有 50 个脚本本来就这么写）。
  实测 `1103 → 226 errors`、`881 → 58 files`、`attr-defined 831 → 0`、`assignment 45 → 0`、`override` 保持 3，
  且没有任何错误类别增长。
* 同批第三个 commit 修的是 20 个脚本里的假注解：`def fetch(self, fund_code: str = None)` —— 默认值今天就是 None，
  注解却在说 str。改成 `str | None = None` 不动任何默认值与调用点，`assignment` 45 → 0、`arg-type` 18 → 13。
* **被自我复核否掉的方案**：第一版给 `AkshareToMySql` 加 `run(**kwargs)` 委托 `fetch_data`，
  一处修 831 个文件。它把 `override` 从 3 变成 162 —— 164 个脚本自带 `run(self, <位置参数>)`，
  任何基类签名都比它们宽；而且若 `fetch_data` 在运行时也挂到基类上，`hasattr(instance,"fetch_data")`
  对所有子类都成立，会把那 164 个脚本在 `script.py:263`/`:380` 误路由。该 commit 以 revert 留在历史里，
  没有被抹掉。
* 平面现在是 advisory：`--scope collection` 在 CI 里只报数不判红，基线要由 CI 自己的读数经
  `ALLOW_BASELINE_UPDATE=1` 的评审式 `--update` 冻结后再摘掉 `--advisory`（本仓 `baseline_update_guard.py`
  的存在理由就是禁止同一 PR 里既改代码又抬基线，见迭代193 审计项 C10）。226 这个数是笔记本读数，只作引用。
* 剩下的 226 条**没有**被豁免，主因已量化，供后续波次直接取用：
  88 条 `union-attr` 来自 `Database.cursor: _DatabaseCursor | None`（`core/database.py:73`）——
  这是共享 DB 层的形状问题，修它需要设计决定（`connect_db()` 返回游标或强制 `_require_cursor()`），
  不该塞进验收收尾波次；39 条 `index` 是同一条「按整数下标取字典」的抄写形态；
  30+ 条 `assignment` 是 `def f(x: str = None)` 这类可安全改注解的默认值。
* 覆盖平面仍未动，且明确不声称：`.coveragerc` 排除 `app/data_fetch/**`，1057 个非 `__init__` 脚本里
  只有 120 个（11.35%，出现在 13 个测试文件里）被测试引用。把它们并进 `--cov=app` 的 70% 门槛需要真测试，
  不是改一行配置。

#### 6. 入账后的账本

`docs/quality/acceptance-gate-ratchet.json` 自 dev `81bc5f9e1`（#192）起为 **7 钉**：
AC-5|03、AC-11|04、AC-16|05、AC-16|06、AC-16|08（待 #195 重钉后消失）、AC-17|03、AC-17|06。
dev 侧的复测作业 `41936293992`、#195 的 sync dispatch 作业 `41936345046`、#194 与 AFI #270 的门禁作业
在写这一节时仍在跑；本波不把在跑的作业写成已通过，也不把任何 PR 合并本身当成验收面闭合。

#### 7. AC01 脚本半区刷新：现行分母是 1057，不是 1066，且有 9 行无源映射（CODE/OFFLINE，本机清点）

顺着采集脚本这条线把 AC01 要求的「带环境身份/采集时间的清单 + 双向 anti-join」在脚本半区做了一遍现行刷新，
结论与九条异常行都记在 [INVENTORY_AUDIT_20261105.md](INVENTORY_AUDIT_20261105.md)。要点：

* 分母：`app/data_fetch/scripts/` 下 tracked `.py` = **1108**，其中非 `__init__` = **1057**，未跟踪 0。
  `INVENTORY.md:11` 的「1,066」是 CSV 行数当文件数，差的正是下面 9 行。
* 正查（清单→树）：1066 行里 9 行在树里不存在；对这 9 行又做了三重检验——
  git 历史既无 `--diff-filter=A` 也无 `--diff-filter=D` 记录（从未入库）、其 `source_sha256`
  不匹配全仓任何 `.py` 的内容哈希、在 `opendata` 工作树按文件名也是 0 命中。
  即：**这 9 行带着哈希，但没有任何可复核的来源**。其中 2 行 `static_role=helper_review_only`、
  7 行 `entrypoint_run` 且 `route=PENDING_PROVIDER_MAPPING`。
* 反查（树→清单）：1057 个非 `__init__` 脚本全部在 CSV 内，未列 0 条；51 个 `__init__.py` 按 CSV 口径不计。
* 判定：脚本半区可称「已刷新」，不可称「已闭合」——`无未解释项` 还要求说清这 9 行从哪来，
  本会话拿不出证据归类，故交属主裁定，且 CSV 自此不得被引用为「1,066 个脚本已有迁移映射」的依据。
  AC11 的分母自此按 1057 计。AC01 另一半（实际 DB 任务含 inactive、systemd/cron/worker、表、消费者）
  本次**已以只读方式刷新**（`ak_scheduled_tasks` 1103 行 / **1098 armed** / 5 inactive；
  `ak_data_scripts` 1066 注册，9 行无文件、0 文件未注册、0 任务孤儿），但这组数字同时推翻了一条旧前提，见下一小节。

同一份台账还给出一个此前任何文档都没写过的硬数：**AC11 已分派处置的脚本是 0 / 1057**。1057 条活行的 `status` 全是
「待盘点/待映射」(1049) + 「review_only」(8)，`migration_route` 全是 `PENDING_PROVIDER_MAPPING` / `HELPER_REVIEW`，
而这两个占位值既不在计划 §5 的七种处置词表内、也没在任何 markdown 里定义（grep 0 命中）。因此 §6 要求每周上报的
「已处置脚本 / 总脚本」按算术只能写 0/1057；把 1049 条 PENDING 读成「已映射」就是虚报。分族（stock 384 / other 317 /
index 93 / fund 87 / futures 64 / option 46 / bond 41 / fx 20 / crypto 5）与分频（daily 680 / weekly 266 / hourly 85 /
monthly 21 / **unspecified 5**）都记在审计文档里供分派直接取用——注意族与频率本身也仍未人工确认，不是已知输入。
静态形状与类型面互相印证：`entrypoint_fetch_data` 885 个类里 831 个的 `main()` 调用不存在的 `run`（#270 已修），
`entrypoint_run` 162 个自带入口。

### Wave 27（2026-11-05）：运行时不是「慢」，是不存在——把它从字节码里认回来

这一波没有推进任何验收行，但把「验收面为什么一直读不到绿」这件事第一次量清楚了：**dev 上的代码从来没有在这台机器上跑起来过**。全部读数见 `RUNTIME_REPAIR_20261105.md`，此处只记结论与身份。

1. **崩溃循环**：`ai-for-investor.service` 在 21:43 读到 `NRestarts=1457`，当天 20 次 `Application startup failed`。原因不是负载也不是依赖，是 `expected heads ['20261101_stock_analysis_report_evidence_vector'], found ['20261019_akshare_enum_values']`。
2. **库状态无法由仓库重建**：那个 found 的 revision 在仓库里不存在，`alembic current` 与 `alembic stamp` 都报 `Can't locate revision`。它的身份只能从 `__pycache__` 的两个 pyc 里读出来（`1a2ef06c542b2…` 与 `514fdcff185a1…`）：`20261017_legacy_paper_import_cutover → 20261019_akshare_scheduler_claims → 20261019_akshare_enum_values`，前者建 `ak_task_run_claims`/`ak_scheduler_control`，后者归一化 5 个 `(表,列,允许值)` 且 downgrade 主动拒绝。**dev 的模型已不再引用这两张表**（`alembic check` 报成 `remove_table`），所以不需要重建迁移，需要记录的是「本机库带着一段仓库复现不出来的历史」。
3. **九天全量失败的真正成因是运行身份漂移**：4,279 条 `failed` 的错误文本 `AKShare script worker exited with code 1 without a result` 在 `dev`、`origin/master`、`docs/iteration-204-wave26` 三个 ref 里都 `grep` 不到——产生这些执行的进程跑的既不是 dev 也不是任何分支的代码。`error_trace`/`result` 长度全为 0，所以当时无人能归因。这一条本身就是 AC01 要的运行入口证据。
4. **修复**：先备份（`ai_for_investor_pre_upgrade_20261105T2148.sql.gz`，135,093,875 B，`gzip -t` 通过，867 条 CREATE/INSERT，`sha256 5bca70ab417e04b1…`），再判明 tracked 待补链只有 `20261030/20261031/20261101` 三个纯新增对象、与幽灵迁移作用面无重叠，然后 `alembic stamp --purge 20261017_legacy_paper_import_cutover` → `alembic upgrade head` → 重启。`current == heads == 20261101_…` 单 head，`/docs` **200**，`NRestarts=0`。冷启动约 70 秒（嵌入模型加载），期间 8000 端口 refused 是正常现象，不是回归。
5. **采集回来了，是计数不是形容词**：13:57:03→14:10 UTC 共 10 条执行，**9 completed / 0 failed / 1 running**；写入量逐条读回 `+5,371`（`stock_esg_msci_sina`）、`+29`、`+15`，两条为 0（幂等）。对照 §1 的九天 4,279/0。顺带钉下一条会反复坑人的事实：**`ak_task_executions.created_at` 是 UTC**（同连接 `NOW()=22:04:32` / `UTC_TIMESTAMP()=14:04:32` / `MAX(created_at)=14:03`）。
6. **恢复运行时资产只恢复能证明的那一个**：worker 从留档原样取回（`sha256 8715a285f2c38ef7…`，`--plan` 只读 `source_or_database_calls: 0`，ruff check/format 通过），它调度的 **5 个控制器 `git log --all --diff-filter=A` 逐个实测 added-in-any-ref = 0**：crypto 有两份 proposal 快照，stock/etf/bond/cffex 四条本机一份都没有，只有它们写出的 progress JSONL 证明曾经存在。把一个写数仓的脚本按「大概是这份」放回运行时是猜测，所以 #273 只含 worker；装好后 `--apply` 变成具名失败关闭（`run_id 20261105T140002Z-6a51aa6b97a0`，`required runtime inputs missing: …crypto_full_history_recovery.py`，`write_possible: false`，`source_failure_recorded: false`）。重建 / 停用 / 只恢复 crypto，交属主。
7. **本波并行开的开发流**：#272 `feat/afi-frontend-coverage-states`（204-E03-03/E05-02，前端覆盖状态不再折叠；本机 `vue-tsc` 干净、`--max-warnings 0` 干净、6 个受影响测试文件 **137 passed** 由集成人自己复跑得到）。另三条在跑：OpenData `204-A04-04` post-commit visibility seal（A05-04/06/07 的前置，全仓此前根本不存在该概念）、AFI `204-E04-01/02/03` 研究工件绑定 publication、#270 分支上的采集脚本类型平面剩余 226 条（`Database.cursor` 联合类型 88 + 整数索引形状 39 两处共享层）。
8. **平面**：以上全部落在 CODE/OFFLINE 与**本机 DEPLOYMENT 观测**。AC14 的小时数钟从 2026-11-05 14:03 UTC 才开始累计，48 次连续小时的最早可能完成点是 2026-11-07 14:03 UTC；AC05/AC13/AC17/AC18 零进展。按属主指示 1,098 个 armed 任务已全量放行真实源，因此源侧配额与跨进程预算（AC13）立刻成为活问题，不是以后再说——`scheduler.py:106/132` 会武装每一条 `is_active`，而 2026-10-25 台账记的是 1,103 行里 69 条 active。

### Wave 29（2026-11-06）：队列被一个作业卡住九小时，拆开后暴露运行资产平面与调度器双写时钟

本轮起点不是新需求，而是接手时的实际状态：本地 `dev` 落后远端 3 个提交，wave 27/28 的记录
仍停在未合并的 PR 里（dev 上的 `DEVELOPMENT_STATUS.md` 最后一个标题是 Wave 26），
而 `dev` 头 `25fd1b4ab` 上 **只有一个作业红**：`Security - Secret Scan (177 §D)`。
22 个开放 PR 里 18 个的 `mergeable_state` 只是因为这一条红而不稳定。平面：以下第 1、2 条是
CI 门禁债务面，第 3-6 条是 CODE/OFFLINE，第 7-9 条是 DEPLOYMENT/NATURAL_CYCLE 的本机运行态。

#### 1. 解阻塞：#304 是唯一的红，且它的红来自一个未合并分支上的提交（CI 实测）

`ci.yml:811-905` 的 full-history 扫描用 `fetch-depth: 0`，因此**所有 ref** 的历史都在扫描范围内。
真凶是 `fix/afi-runtime-environment-identity`（PR #301）分支上提交 `7e3b8a444107` 里
`src/backend/tests/test_runtime_environment_identity.py:32` 的合成字面量
`SECRET_SENTINEL = "sup3r-s3cret-dsn-passw0rd"`；`blocking_ready=true` 使它变成硬门。
证据链不是推断：CI 工件 `gitleaks-report.sarif`（artifact 13484184756，job 127764998791）
只有 **1 条 result**，正是这条；#304 的 PR 作业 42165197171 自身 success；
`scripts/ci/check_gitleaks_history_baseline.py` 在应用前后分别给出 accepted=280 → 281 且两侧各自单独应用会红
（`count is 280, baseline requires 281` 与反向）。本机无法复现扫描本身：gitleaks 下载不通
（只有 `api.github.com` 可达），且该 commit 不在本地对象库里。

合入 #304 后 dev 头 `0a4c5ab31` 的 secret scan 作业 **success**（run 42224170243 逐作业读回）。
两条必须一起记的残留：(a) 该指纹登记的是一个**测试占位串**，#304 正文自陈"未做属主裁定"，
只是沿用 cfets 先例；(b) 它 SHA-scoped 到一个未合并提交——分支被删则 `.gitleaksignore` 条目成为
死账，分支被 rebase 且新提交仍带字面量则会再触发门禁。PR #301 本身在跑，两条都要在合并它时再看一次。

#### 2. 集成税：同一族三行文件让 14 个 PR 同时变 dirty，以及为什么它必然复发

合 #304 之后，`mergeable_state=dirty` 从 1 个（#293）变成 14 个。机制是可复核的：
几乎每个分支都往 `.gitleaksignore` 追加**同一个** cfets 指纹块、往
`scripts/ci/gitleaks_history_baseline.json` 追加同一个 exception 对象并各自动 `accepted_fingerprints`。
dev 的两个 blob 因此是各分支的**严格超集**，去重后的并集恒等于 dev 版本
（每个 rebase 后 `git diff origin/dev -- .gitleaksignore scripts/ci/gitleaks_history_baseline.json` 为空）。
15 个分支（13 个由并行代理、2 个由本代理：#274/#278）以 merge 而非 rebase 并入 dev——
因为已有作者自审是绑定在旧 head 上的，force-push 会把它们变成孤儿；随后按新 40 位 head 重投自审。
每个分支推送前都跑 `check_gitleaks_history_baseline.py`（全部 `passed (accepted=281, unresolved=0, blocking_ready=true)`）
与冲突标记扫描。这一说法我另外用 API 的 blob sha 独立复核过，而不是只看代理的汇报：
`/.gitleaksignore` 与 `scripts/ci/gitleaks_history_baseline.json` 在 15 条分支（13 支集成 + #274/#278）上
与 dev 的 blob **全部逐支相同**（dev blob `1104263cf352…` / `c72a0cfae526…`），不匹配数 0。

结构性结论，与"本轮已做完的事"分开记：只要"每个 PR 各自重记全局指纹台账"这个形状不变，
每次合并就会把其余 PR 全部打回 dirty。可选项是把指纹改成按 PR 追加的独立文件、
或让 `accepted_fingerprints` 由 `.gitleaksignore` 行数导出而非手填；两者都动门禁语义，
属属主裁定，本波不动。

#### 3. 采集脚本类型平面：advisory 面第一次有了可复跑的读数，机械族被真实修掉 34 条

CI 的测量形状是 `src/backend` 下 `python ../../scripts/ci/mypy_ratchet.py --scope collection --advisory`
（`ci.yml:594-596`），内部执行 `mypy --config-file config/mypy_collection.ini app/data_fetch/scripts`。
本机 `.venv` 的 mypy 1.14.1 在 `app/config.py:71` 直接 INTERNAL ERROR，必须用 lock 钉的
**1.20.2**（`config/requirements-dev.lock`）才与 CI 同口径。

* 我在 dev `0a4c5ab31` 实测 **159 errors / checked 1108 files**（`mypy_ratchet[collection]: advisory, no baseline yet - errors=159`）。
  这条推翻了 wave 26 的 226：#275 之后 `union-attr` 88→9、`index` 39→1、`assignment` 30+→7。
* **PR #305**（`fix/afi-collection-plane-mechanical`）修机械族与两个真缺陷：
  `var-annotated` 15→0、`valid-type` 5→0、`dict-item` 1→0、`index` 1→0、`operator` 23→13，
  我在它的 head 上独立复跑同一命令，得 **125 errors / checked 1108**——平面未缩小，
  且没有任何一族变多。它不含 `# type: ignore`、不动 `mypy_collection.ini`、不加基线文件，
  因此不触 `baseline_update_guard.py`。
  其中两处按 wave 26 的定义是**真 bug 而非类型噪声**：`funds/weekly/fund_detail_info.py`
  把一个名字先绑成 `set(...)` 再当序列下标取（`entrypoint` 之外的第二类"字典按整数下标"抄写形态），
  以及 `stocks/daily/stock_bid_ask_em.py` 对同一个 `data.get("f32")` 调两次使收窄失效。
* 属主 2026-11-06 裁定：剩余 `operator`/`union-attr`/`str-bytes-safe` **按站点依据 DDL 收窄**，
  不做 DB 层访问器、也不带着它们冻结基线。**该裁定已落地为 PR #308**（head `0be658dad`）：
  同一命令实测 **125 → 95**，`operator` 13→0、`union-attr` 9→0、`str-bytes-safe` 7→0，
  `checked 1108` 未变，`call-overload` 23→22、`arg-type` 10→9，
  `import-untyped` 40 / `return-value` 15 / `assignment` 6 / `override` 3 未动，无任一族增加；
  类型形状与入口测试 32 passed。两处仍是真缺陷而非类型噪声：
  `re.match` 被调用两次（守卫一次、body 一次）使 body 得不到收窄，
  以及 `akshare_catalog_batch.run()` 的计数 dict 混了 int 与 str——后者的修法是给它命名形状
  （TypedDict）而不是 cast，因为 cast 会把真实的类型混合藏起来，而 TypedDict 运行时就是普通 dict，
  负载与键序不变。至此采集平面从 dev 的 159 走到 **95（-64）**。
* `import-untyped` 40 我没有"顺手加 stub"，而是把代价量出来了：只装 `types-requests`
  时 collection 159→119（且逐族差分证明其它一族没变），但 **blocking 的 app scope 从基线 0 变 +6**，
  门禁会红；补上 `types-PyMySQL` 后 app 降到 +3、collection 仍 119。剩余 3 条是真实类型问题
  （`strategy_target_approvals.py:1065` redundant-cast、`approved_target_authority.py:329` arg-type、
  `akshare/data.py:202` Series[Timestamp] 对 TimestampSeries）。所以这是一笔需要先修 3 个 app 侧真错、
  且与开放 PR #302 在 `data.py` 上重叠的独立工作，不是免费项。测量后环境已还原（复测回 159）。
* 平面仍必须是 advisory：基线只能由 CI 自己的读数经评审式 `--update` 冻结，
  所以"代码修复 PR"与"基线冻结 PR"是两个 PR，本文件所有 159/125 都只作笔记本引用。

#### 4. 运行态普查第一次给出 AC11 的真实分母，并按属主裁定执行了一次生产写

用已合并的 #284 普查工具（`scripts/task_param_audit.py`，只读）在本树跑全量 armed 面：
`binds 155 / accepts_var_kwargs 886 / script_file_absent 50 / unexpected_param 7`，
`ak_data_scripts` 1066 行（active 1051）中 9 行 `module_path` 在树中不存在，接口表 0 行。
把它与修复后执行记录交叉，得到 AC11 迄今第一个可辩护的分子：
**运行态已证明"能绑定且写入行"= 143 / 1098**（放宽为"完成即可"= 180），
`script_file_absent` 50 与 `unexpected_param` 7 在修复后 **100% 失败**。

属主裁定"停用幽灵任务"→ 对队列 A 的 50 个任务执行 `is_active=0`（before-image
`/tmp/it204/ac11-queue-a-before-20261106T134756Z.json`，13:47:56 UTC，armed 1098→1048）。
三条边界一起记，否则这条读数会被误用：

1. **停用尚未可判为生效。** 观测窗内那 50 个任务 0 次执行，但它们的 cron 落在 CST 06/08/09/15/19 时，
   窗内一个槽位都没到；代码侧 `_run_task_job → run_task_now` 不回查 `is_active`
   （`scheduler.py:95/138`），`reload_active_tasks` 只遍历 active 集合、从不注销已转 inactive 的 job
   （`scheduler.py:129`），而运行进程是 11-05 以全量 armed 启动的。
   首个可判观测点在 11-07 约 00:35 UTC。
2. 这 50 个任务的失败是幽灵注册**唯一的可见信号**，停用后可见性净下降。
3. 更糟的是：9 个无文件注册对应的**目标表对象根本不存在**（`information_schema` 计数 0），
   其中 `release_policy`/`yield_release_policy` 从未有过任务。
   所以 AC05/AC10 对这些数据集必须继续写"未覆盖"，而不是"覆盖为空"。

同时修正 wave 26 的两条口径：`INVENTORY_AUDIT_20261105.md` 的分频分布是 **CSV 声明值**，
与 armed cron 不一致（自称 daily 的 694 个任务里 690 个实际是星期受限；
`ak_data_scripts.frequency` 对全部 armed 任务的值都是 `manual`，不携带信息）；
且 CSV 的 9 个 `source_sha256` 在 AFI 全仓 3099 个 tracked `.py` 的 sha256 集合中 0 命中——
`static_role` 只能读源码得到，故 CSV 生成自一棵**带未提交文件的工作树**，
台账与 DB 注册同源，不能互为印证。

#### 5. 新缺陷：`ak_scheduled_tasks` 的两个时间列被两个写入者用两种钟写（数据+代码双向证据）

`AkshareExecutionService._utcnow_naive()` 写 naive UTC，`AkshareScheduler.run_task_now`
随后用 `datetime.now()`（本机 Asia/Shanghai）覆盖同一列 `last_execution_at`；
`next_execution_at` 直接取 APScheduler 的 `job.next_run_time`（触发器在
`AKSHARE_SCHEDULER_TIMEZONE` 上），落进 naive 列即墙上时间。

实测由本波新增仪器 `evidence/2026-11-06-wave29/scheduler_clock_duality.py` 产出
（只读，`--env` 取 backend `.env`，输出 JSON 同目录），16:14:50Z 读 **1048 armed**：
`shifted-by-tz-offset` **214**、`agrees-within-1h` **821**、`older-than-any-execution` **13**、无执行行 0。
单小时 cron 的任务共 **964** 个，`next_execution_at` 落在 cron 墙钟小时的 **964/964（全中）**，
而 `last_execution_at` 只有 **135/964**。
**我此前写的是"53/53 与 2/53"**——那是按"daily 形状"窄筛手动跑的一次数；仪器把母体换成"小时字段为定值的全部任务"
后，方向不变、比例同为极端（next 全中 / last 一成多），但绝对数应以仪器为准，旧写法作废并在此留痕。
214 vs 上一轮的 192 也不是矛盾：采集自 2026-11-05 14:02 UTC 恢复后每条完成都在被本地钟覆盖，
这条计数随运行单调增长，引用必须带读数时刻。
一次自打脸值得记：仪器第一版用 `datetime.now()` 打时间戳并标成 UTC，跑出来是
`2026-11-07T00:14:33Z`（本机 CST），**恰好就是本节描述的那个缺陷**；改为
`datetime.now(timezone.utc)` 后才是 16:14:50Z。这个错误反而说明该缺陷会自然发生在任何忘记时区的代码里。

后果：任何跨列比较差 8 小时。wave 28 修的是 AC14 **仪器比较侧**（#282），本波发现的是**写入侧本身**；
两者不是同一件事，不能因为"§282 已修 tz"就把这条当已闭合。修复在 **PR #306**
（含 `reload_active_tasks` 注销失效 job，使第 4 节的停用真正生效）；
存量校正在 `scripts/ops/normalize_scheduler_clock.py`，**按分类逐行 shift，
偏移不落在 +7~9h 签名里的行一律不动并单列报告**，且必须在代码部署+采集器重启之后执行，
否则仍在跑的调度器会把墙上时间写回去。本波只跑了 dry-run 并保留其分布读数。

#### 6. AC01 另一半第一次被刷新：进程跑的是旧代码，10 个 sidecar 里 8 个因宿主文件失败

14:05–14:07 UTC 只读复测（`systemctl --user show`、`journalctl --user`、`git`、`pip list`、`SELECT`）：

* `ai-for-investor.service` 主进程启动于 11-05 22:44:45 CST，NRestarts=0，启动时 HEAD 为
  `9f573d34d3d0`，工作树现在 `0a4c5ab3` —— **部署了但没重启**，中间 7 个提交不在运行进程里。
  因此本波所有运行态读数描述的是旧代码行为，而任何"修复已在生产生效"的说法在重启前都不成立。
* 10 个 sidecar 单元中 **8 个确定性失败**，原因同族：systemd 依赖的宿主文件不存在于任何 git ref
  （`crypto_full_history_recovery.py`、`bond_convertible_history_controller.py`、
  `backfill_stock_amount_sina.py`、`run_stock_tail_slices.sh`、`run_dce_option_recovery.sh`、
  `run_dce_browser_capture.sh`、`policy_expiry_watchdog.py`、`run_etf_nav_shard.sh`、
  `run_option_history_loop.sh`）；`etf-nav-backfill@0-3` **此刻正在 30 s 周期的崩溃循环**里。
  这说明 AC01 的清单若只按 `git ls-files` 取 1108 的分母，对运行资产平面是盲的。
* `full-history-recovery` 在 exit 2 的同时记 `cursor_advanced: true`——失败仍推进游标，
  是一条独立的可观测性/幂等缺陷。
* 今日消费面：272 completed / 65 failed / 1 running，109 个目标表有正行增量（+128,336 行），
  `ak_data_tables` 155/1061 今日更新；**892/1044** 个 armed 任务的目标表今日无成功写入，
  但多数是周/月形状未轮到，因此**不可**读成"892 个数据集缺数"。
* `md_capability_ledger_entries` 仍为 **0 行**，无生产写入者——wave 28 认定的
  AC02/AC03/AC09/AC18 真实阻塞点未变。

#### 7. AC14：小时目标在结构上只能由一个任务产出，而它一次都没成功

按 cron 逐字段展开（列表/区间/步长/星期/day-of-month）：能每小时触发的 armed 任务只有 **1 个**
（`id=1049 crypto_hourly_market`，`3 * * * *`），它在 23.5 h 窗口内应得 24 个槽位、
24 次全部 600 s 超时、completed 0。停用后的形状分布是 weekly 941 / sub-daily 83 / 月度 21 / **daily 只有 2**；从停用前的 daily 32 掉到 2 正是那 50 个被停用任务造成的（-30 daily、-18 weekly、-2 sub-daily）。本波第一版分类漏看 `day-of-month`，把 21 个月度形状算成 `daily 23`，纠正过程记在 `RUNTIME_READOUT_20261106.md` §4，错误本身也保留。
所以"48 次小时自然运行"这一格不是单纯等时间，先把 1049 的超时或任务形状定下来才有意义。

与 wave 28 §1.2 的 `hourly 仍 103` **口径不一致，此处不改写对方的数**：本机的 1 是
把 cron 展开成触发集合后 `小时字段 == '*'` 的任务数，103 是 #282 仪器自己的分档。
AC14 判据需要把"小时面"的定义写死，否则这一格可以永远各说各话——这是一条属主/判据决定，
不是代码问题。

#### 8. OpenData 侧：账本 6 钉、两个 PR 合入、test-cov 是间歇红且我的初判方向反了

* `docs/quality/acceptance-gate-ratchet.json` 现为 **6 钉**（AC-5|03、AC-11|04、AC-16|05、AC-16|06、
  AC-17|03、AC-17|06）；wave 26 期待的 7→6 已落地在 `1815e2a2`（PR #195），工件为 run 41936345046
  的 `acceptance-gate-ratchet`（artifact 13376730203）。README/登记表两侧正文均含
  「不构成任何投资建议」。
* 我合入 **#196**（visibility seal）与 **#200**（AC-15 durable layers 实测），二者 mergeable_state=clean。
* dev 头 `f1a82bca` 的红在 `make gate` 的 `test-cov` 成员，报
  `sqlalchemy.exc.TimeoutError: QueuePool limit of size 1 overflow 0 reached, timeout 0.05`。
  **我先交下来的归因是错的**：我说它是 #197 运维页引入的连接泄漏。实测 `git diff 28607e18..f1a82bca`
  是 12 个文件、全在 `frontend/`、0 Python、0 测试——#197 没有创建任何 engine/route。
  真因是潜伏竞态：`reviewed_worker.py:249` 的 worker Engine 固定 `pool_size=1, max_overflow=0,
  pool_timeout=0.05`，且 `_verify_pool_wait_bound`（`:862-878`）把放宽它判为产品违规；
  测试在主线程驱动 ledger 的同时 `run_once` 每 250 ms 心跳占用那唯一槽位，
  一次 >50 ms 的心跳写就让测试自己的 checkout 饿死。CI 在 35,488 条里撞中一次。
  **它是间歇的，不是常驻红**：合入 #196/#200 之后 OD dev 作业 42224189357（`02fb79a2f`，14:29:03Z）
  两个作业全 success，其中 `quality gate` 跑满 18 个成员，test-cov 在没有 #201 的情况下自己变绿。
  因此 #201 的正确定位是加固潜伏竞态，把它写成修复了常驻红是不准确的。
  **PR #201** 按"只修测试、不动产品不变量"处理：给取消者一条自己的 `NullPool` 直连 Engine，
  池参数一字未动，并加了三条守卫（占满槽位时第二次 checkout 必须以原错误失败、
  槽位被占时驱动仍能读+取消、事件级证明不泄漏），配 12 次重复加压全绿。
  两条残留被明确记录而未修：生产取消路径仍与 worker 共享那一格 Engine（竞态→可重试 503），
  `test_reviewed_worker.py::test_child_exception_text_...` 用同一 0.05 s 界、加压下也红过一次。
* AC-1|08：#198 把判据改成"条款链接必须真的落到页面"后一测即 gap（35 源 16 条只指站点根），
  账本仍写 proven，于是 `acceptance-probe-check` 红。按属主裁定，我发了
  `sync_acceptance_ratchet=true` 的 dispatch 作业（run 42228207697 @ `4d50d4a8e`）取工件，
  **记钉必须由该工件产生**；补 URL 才是真修，但 16 条链接内容属源站事实，臆造即伪造。

#### 9. 本波对接的影响

本轮把三件事变成事实：CI 队列的可判状态（不再被一个历史扫描笼统挡着）、
AC11 的第一个证据化分子、AC01 运行资产平面的首次刷新。它同时新增两条未闭合缺陷
（调度器双写时钟、systemd 依赖的宿主文件不在任何 ref）。
按 `SUBAGENT_TASKS.md:257` 的收口条件，任何 PR 合并、任何笔记本读数、任何 `--sync-ratchet`
入账都不构成验收面闭合；本轮没有任何一格 AC 判定被改写为"通过"。

#### 10. 本波草稿被独立事实核查后改掉的八处（保留错误本身）

一个专职核查代理把本节与 `RUNTIME_READOUT_20261106.md` 的每条数值都用原始命令重跑了一遍。
它推翻或收紧了八处，全部就地改正，且**不抹掉错误**，因为下一波需要知道错在哪一类：

1. **7 个数据型幽灵的目标表不是不存在，而是有约 2,400 万行存量数据**（最大
   `OPTION_COMMODITY_DAILY_HISTORY` 22,093,150 行）。我只查了元数据库 `ai_for_investor`，
   没查 `AKSHARE_DATA_DATABASE_URL` 指向的 `akshare_data`。正确表述是"存量有、生产者无"，
   既不是"已覆盖"也不是我写过的"表不存在"。新鲜度当时**未测**（业务日期列名按常见猜测 7 表全未命中）；
   **随后同一波内测到了**（见下面 §12 与 §13 的更新：业务日到 2026-10-26/10-23，
   且生产者被**双向绑定**，所以"写入者无法绑定"这句也在同一波内被推翻，纠正记录同样保留）。
2. `crypto_hourly_market`(1049) 并非"从未成功"，它在 2026-10-19~10-27 累计 completed 178 次；
   准确说法是"自那次全量失败起点之后一次也没成过"。
3. 宿主缺失文件是 **12 个**（7 个 ops + 5 个控制器/回填脚本），受影响 sidecar 是 **9 个**，
   且那 9 个 ops 路径**全部**不在 git 索引里（我先前写"至少 10 个""其中 8 个不在索引"都不准确）。
4. 时钟交叉验证的 53/53 与 2/53 出自一个未固定的 daily 口径，按任何明确定义都复现不出 53；
   可复现的版本是 23/23 与 2/23。
5. 普查、AC11 分子（143/180）都是停用前 armed=1098 的读数；停用后同树复跑
   `script_file_absent` 变 0、分子变 155/1048 与 193/1048。引用必须带时间戳。
6. 目标表零写入的分母是 1044 而不是 1048：4 个 armed 任务的脚本行没有可用 `target_table`。
7. #304 那条"该 commit 不在本地对象库里"已不成立（PR ref 使其可见）；本机不可复现的只有 gitleaks 二进制下载。
8. "3099 个 tracked .py" 混淆了文件数与摘要数：3169 个文件、去重后 3099 个不同 sha256。

核查同时**确认**了没有问题的部分：dev 唯一红作业及 #304 的两文件范围、
SARIF 只 1 条 result、collection 159→125 与逐族不增、`.coveragerc` 排除、
6 钉账本与免责正文两处齐全、OD 红作业是 `quality gate`/test-cov 且 `git diff 28607e18..f1a82bca` 全在 `frontend/`。

#### 11. AC14 仪器 #282 被专门审了一遍：没有我犯的那个 bug，但 wave 28 的一个数字与它矛盾

我在 §4 犯的那类错误（展开 cron 时漏看 `day-of-month`）值得确认是否也在正式仪器里，
所以逐行审了 #282 的 `src/backend/scripts/ops/report_iteration204_acceptance_window.py`。结论：

* **没有该缺陷。** `expected_slots` 展开五个字段并按日匹配（:267-268、:282-284）。
  可跑验证：`15 10 5 * *` 判为 monthly，在不含 5 号的窗口里得 **0 槽位**，含 5 号时恰得一个；
  不认识月/季受限形状时返回 None 并记 `slot_check: unavailable`，不猜。
* 字段解析支持 `*`、`*/N`、单值、逗号列表、`lo-hi`，其余拒绝（:211-239、:270-273）。
* 时区与"未到期"处理正确：槽位按 `Asia/Shanghai` 枚举再转 UTC，有反事实测试钉住；
  零槽位记 `no_expected_slot_in_window` 而不是算失败。它的 21 项测试在本机全过。
* 它的 hourly 定义是"小时字段展开为全部 24 个值"，因此该桶**不可能**装 103 个任务。

由此产生一条对记录本身的要求：wave 28 §1.2 写"#282 修后 `hourly 仍 103`"，
而以 #282 自己的分类器不可能得到 103（本机按 armed cron 展开，小时字段为 `*` 的只有 1 个任务，
即 id 1049）。这不是谁数错了，而是**两个工具的 hourly 定义不同却被写进同一句话**。
本波不改写 wave 28 原文，只声明二者不可互换，并要求 AC14 判据把"小时面"的定义写死。

#### 12. 采集平面在本波结束时的四档读数，以及幽灵表的新鲜度与生产者绑定

| 度量点 | 命令（与 CI 同口径） | 读数 |
|---|---|---|
| dev `0a4c5ab31` | `mypy_ratchet.py --scope collection --advisory`，mypy 1.20.2 | **159** errors / checked 1108 |
| #305 head `bce164cb4` | 同上 | **125**（机械族 + 2 个真缺陷） |
| #308 head `0be658dad` | 同上 | **95**（按 DDL 逐站点收窄；operator/union-attr/str-bytes-safe 归零） |
| stub 对照实验（只测，不改仓） | 同上 | collection 119，但 app scope 基线 0→+6；补 `types-PyMySQL` 后 +3。测毕已还原并复测回 159 |

剩余 95 条：`import-untyped` 40、`call-overload` 22、`return-value` 15、`arg-type` 9、
`assignment` 6、`override` 3。平面仍必须是 advisory：基线只能由 CI 自己的读数经评审式
`--update` 冻结成第二个 PR（`baseline_update_guard.py` 禁止同一 PR 既改代码又抬基线）。

幽灵注册对应的 7 张表，本波最终测到（`akshare_data`，日历取该库 `TRADING_DAYS` 8797 行）：

| 表 | 行数 | 业务日列 | 业务新鲜度 | 物理写入止 | 生产者 |
|---|---|---|---|---|---|
| `OPTION_COMMODITY_DAILY_HISTORY` | 22,093,150 | TRADE_DATE | 2026-10-26 | 2026-10-26 20:07 | BOUND |
| `OPTION_CFFEX_DAILY_HISTORY` | 858,096 | TRADE_DATE | 2026-10-26 | 2026-10-26 23:39 | BOUND |
| `OPTION_ETF_DAILY_HISTORY` | 854,174 | TRADE_DATE | 2026-10-23 | 2026-10-23 19:45 | BOUND |
| `FUND_MONETARY_INCOME_HISTORY` | 91,419 | VALUE_DATE | 2026-10-26 | 2026-10-27 08:55 | BOUND |
| `FOREX_SINA_DAILY_HISTORY` | 37,327 | TRADE_DATE | 2026-10-26 | 2026-10-26 22:45 | BOUND |
| `ETF_REALTIME_QUOTE_EM` | 13,156 | QUOTE_DATE/OBSERVED_AT | 2026-10-26（仅 8 个业务日，滚动快照） | 2026-10-26 15:50 | BOUND |
| `FUND_REVIEWED_UNIT_NAV_HISTORY` | 4,491 | VALUE_DATE | 2026-10-26 | 2026-10-27 08:45→08:51 | BOUND |

绑定方式是两条独立链路交叉：每个注册 slug 在 `ak_task_executions` 里**最后一次 completed**
与对应表的物理写入秒级吻合（执行行 UTC、`OBSERVED_AT` +08，换算后一致）；
磁盘残留 `__pycache__/<slug>.cpython-313.pyc` 的 `co_filename` 逐字等于注册的 `module_path`，
常量池里恰只有其目标表名，七个 sha256 已记录、副本存于
`/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/pyc/`。
表级对 `TRADING_DAYS` 的缺口为 0~12（`ETF_REALTIME_QUOTE_EM` 的 305/312 是快照表形状使然，不是欠覆盖）。

仍然不可知、因此不许被当成闭合的三件事：`.py` 源文本不在任何 ref（`log_bin=ON` 但无
`REPLICATION CLIENT`，`SHOW BINARY LOGS` 报 1227，无法给删除定日）；谁删的、为什么删，
`var/reports`、`var/backups`、`afi204-evidence` 三处均无记录；逐标的内部缺口需要源原生日历，本机没有。

#### 13. 治理声明的文档在教一个必然被拒的写法（本地复现 + CI 实测）

* 形状是被测出来的，不是读码猜的。`scripts/ci/check_pr_governance.py:70` 的
  `_RISK_RE = re.compile(r"\b(R[0-3])\b")` 在 `:197` 用 **`fullmatch`** 取值，七种写法的实测结果：
  `- 风险等级: R2` 通过、`- **风险等级**: R2` 通过、`` - 风险等级: `R2` `` 通过、
  `- 风险等级: R2 —— 命中 x/**` **不通过**、`R0/R1/R2/R3 + 命中路径说明` **不通过**、
  另起一条 `- 命中路径:` bullet **不影响**（gate 只要求目标分支/风险等级/测试证据三键）、
  只写在 HTML 注释里的值 **不可见**（因此未填的模板占位符必然失败）。
* `CONTRIBUTING.md:387` 教的正是第二种不通过的写法。代价：#306 变红
  （`Governance Gate=failure`，run 42229971310 / job 127933073661，步骤 4
  "Evaluate trusted governance policy"），#307、#308 只是还没轮到 gate。
* 第二条陷阱：dev 的分支契约**字面**匹配 `feature/*|fix/*|docs/*|refactor/*|test/*`，
  `feat/`（commit type 的拼法）不在其中；而 GitHub 不能改开放 PR 的 head 分支，
  所以唯一修复是把同一个 commit 推到合规分支名重开。#307（head `e31e22937f8d59a915dcd63e74a59f7fe9471f56`）
  因此关闭，同 sha 以 `feature/afi-ac11-runtime-evidence` 重开为 **#309**，内容与提交零变化。
* 方法固化成 `/tmp/it204/gov_pre.py`：用 dev 上的**可信 checker** 在真实 PR 元数据上跑整队列。
  26 个开放 PR 里 gate 失败 3 个——#262（dependabot，迭代204 之外）、#307、#308——
  全部在 CI 轮到它们之前改掉。这条预检本身把三次"红一次再修"换成一次批量修。
* **#310** 修文档并把这个形状钉成可执行契约（`test_risk_level_is_a_bare_token_and_the_path_goes_on_its_own_bullet`，
  该文件 59 passed）。`.github/PULL_REQUEST_TEMPLATE.md` 有同一个问题但**故意不在 #310 里**：
  risk map 判它 **R3**（`scripts/ci/tests/test_governance_contract.py:213-233` 把该文件列进 R3 集），
  属主级变更，单独记进债务表。改文档而不是改策略：严格 fullmatch 是有意设计
  （`test_html_comment_decoys_cannot_supply_risk_or_test_evidence` 就是为它写的）。

#### 14. 我自己的合并闸门有一条会把 PR 永久判死的缺陷

* 机制：`/commits/{sha}/check-runs` 在同一 sha 上**累积**历次 rerun 的记录。#198 的 head
  `4d50d4a8ec` 返回 6 条：最新的 run 42228207697 `quality gate` + `secret scan` 均 success，
  而旧 run 42155237562 / 42155243723 的 `quality gate=failure` 仍留在列表里。
  任何"每条 check 都绿才合"的逻辑，只要不按 `(app, name)` 取最新一条，就会把这个 PR 永久判红。
* 修法：按 `(app.name, name)` 取最大 `id` 之后再判 pending/red。改后 #198 立刻判 READY，
  已 squash 合入 dev = `34be0a1b9c`；同一修法下 #306 的 gate 失败记录在我改完 PR body 后
  从 red 列表消失（pending 16、red 空）。
* 影响面自评：这条缺陷只会**少合**，不会**错合**——保守方向的 bug。但它在账面上的效果是
  把"CI 排队"伪装成"CI 红"，而我差点按后者去写 wave 29 的结论。仪器错的时候，
  错的方向决定了它是被忽略还是被相信。

#### 15. OD AC-5|07 的真因不是树漂移，是"记账作业不重算证据"

* 先否证我自己上一轮的假设：绑定树**没动**。`source_sha256 0499005a…829def` 与 325/325
  个文件哈希在 `02fb79a2` 上全部仍验证通过。`measure_ac5_07` 只报两条事实不合格、
  `security_issue_count=2`，码子恰为 `scan-stale` / `triage-stale`，出处是
  `scripts/quality/ported_security_evidence.py:33` 的 `MAX_EVIDENCE_AGE = timedelta(hours=24)`
  与 `_validate_freshness:154-175`，而工件 `generated_at` 是 2026-11-04T05:30:42Z。
* 重建（bandit 1.9.4、干净 venv、`make security-bundle-rebuild`）：
  **1048 findings / 31 HIGH / 241 files / 15 rules**，`scanner_exit=1`、`errors=0`、
  `identities_matched=1048/1048`、`carried_prior_rows=1048`——**没有一条是新发现**，
  因此不需要写任何新处置，没有 `nosec`、没有抑制、没有改代码。重建后
  `VERDICT AC-5|07: proven`（issue=0），CI dev run 42224189357 的 gate.log 独立佐证
  （`built:true … identities_matched:1048` 后紧跟 `proven`）。
* 结构缺陷在记账面：`.github/workflows/ci.yml:260-264` 的 `sync_acceptance_ratchet` 分支
  **只跑 `--sync-ratchet`**（成员 gate 是 `!= 'true'`，正好排除了 rebuild），
  于是"钉住证据的作业"从不重算证据，只会把 24 小时前的读数再钉一遍。
  OD **#202**（head `631866305ea392d8dd1cfc4b6216476400a1563e`）把 rebuild 移到记账步骤之前，
  加 3 条接线测试（变异验证：删掉 / 内联 / 遮蔽这一行，三条全红），
  并在 `akshare-reference-allowlist.json` 重钉 ci.yml 摘要；
  **不提交任何 bundle 字节**——提交会把一次读数重新计时，
  并使台账注记里的 `scan_sha256 da976114…` 与 python 3.11.8 字面量失真。
* 因此上一轮"AC-5|07 多出 8 个意外钉"的读法必须降级：那 8 钉里含过期读数，不可原样入账。
  #202 合入后的属主侧动作是在 dev 上再 dispatch 一次 `sync_acceptance_ratchet=true`，
  预期工件应为 **6 钉 + AC-1|08，且不再出现 AC-5|07**；
  AC-1|08 的记钉只做在那份新工件到手之后，不预判、不用本机读数替代。

#### 16. 一条新的、当场可证的 CI 债务：`scripts/ci/tests` 根本不在 CI 里

* `ci.yml` 从这个目录只跑 `test_check_deps_sync.py`（:76）和 5 个 `.mjs`（:1044-1048）；
  **228 个 Python 契约测试没有任何作业执行**。
* 后果实测：dev `0a4c5ab31` 上 `python -m pytest scripts/ci/tests -q` = **5 failed, 223 passed**，
  五条同族——workflow 里的 `actions/checkout` 等 pin 早已升到 v7.0.1（`3d3c42e5aac5…`），
  契约测试仍写死 `11bd71901bbe…`。这类测试的意义正是"pin 变了必须有人重新确认"，
  但因为没人跑它，确认从未发生，漂移不可见。
* 处置分两步，且分开计费：R1 只改测试期望（按上游 tag↔SHA 证据重钉这 5 条，
  并补一条"workflow 的 pin 不在接受集内即红"的测试），**不弱化任何断言**；
  把该目录接进 CI 是 R3（动 workflow），留给属主，作为 #202 之后的一条独立变更。
* 对照实验证明这 5 条与本波其它改动无关：同一命令在 dev 与在 #310 分支上，
  FAILED 列表 `comm -13` 双向为空（0 introduced / 0 fixed）。

#### 17. 本波的 PR 台账（截至 2026-11-06 15:20Z，合并只按"全部 check 完成且成功 + mergeable + 自审绑定 head"三条件）

| PR | 仓库 | head | 状态 | 备注 |
|---|---|---|---|---|
| #198 | opendata | `4d50d4a8ec` | **MERGED** → `34be0a1b9c` | 条款链接必须落到真实页面（AC-1\|08 前置） |
| #201 | opendata | `f1cdbea4de` | **MERGED** → `0754b995d7` | ledger canceller 用独立 Engine |
| #202 | opendata | `631866305ea3` | 排队 | AC-5\|07：记账前先重算证据 |
| #306 | ai-for-investor | `a3840261a4` | 待合（无红，pending 16） | 声明改裸 `R2` 后 gate 通过 |
| #307 | ai-for-investor | `e31e22937f8d` | **CLOSED → #309** | 分支名 `feat/` 不合 dev 契约 |
| #308 | ai-for-investor | `0be658dad8` | 排队 | 声明格式修复（预检抓到，未浪费一轮 CI） |
| #309 | ai-for-investor | `e31e22937f8d` | 新建 | 取代 #307，内容与提交零变化 |
| #310 | ai-for-investor | `d748890ebe` | 新建 | CONTRIBUTING 声明语法 + 钉住它的测试 |
| #311 | ai-for-investor | `f761f0d5d3` | 新建（叠 #286） | 89 行 UNDECIDED 的 `source_function` 分诊 |
| #312 | ai-for-investor | `0b4671a93a` | 新建 | `scripts/ci/tests` 的 5 枚 stale action pin 重钉 + 3 条漂移哨兵 |

本波结束时**仍在跑、因此不作为结果入账**的两件事：采集平面 tranche 3
（55 条可修残余项，40 条 `import-untyped` 按属主裁定保留），以及采集运行态自 2026-10-27 00:55
起 100% 失败的根因定位。已在本波内闭合到可记账的：89 行分诊（#311）与 5 枚 pin 重钉（#312，
本机独立复验 231 passed / 0 failed）。队列深度是本机的约束而不是结论：
AFI 排队 57、并发 runner 5——所以本波把所有"能在本机证明的事"都写成了账，
把"只能等 CI 的事"如实留在等待列里，没有一格被改写成通过。

#### 18. 89 行 UNDECIDED 的 `source_function`：我上一轮对 #286 的反馈被自己修正了一次

* 上一轮我给出的反馈是"#286 的抽取器看不见间接调用，所以 89 行停在 UNDECIDED"。
  本轮把这条反馈本身当作待证假设处理，结论是**部分成立、处方开错了**：
  `assign_script_dispositions.py:209-256` 的 `parse_script()` 确实只认
  `X.fetch_ak_data("literal")` / `ak.<attr>` / `getattr(m,"literal")` / `self.table_name = <literal>`，
  但用一层严格更深的 AST 走查去补，**72 行里新增 0 个** `source_function` ——
  因为这些文件里根本不存在可从调用点抵达的 akshare 标识符：它们是手写内联的
  `requests` / `pd.read_csv` 重实现，或把活交给 `_jin10_macro.py` / `_sina_macro.py` / `_endata_yien.py`。
  正确的处方因此是"换输入"，不是"修遍历"。真正的工具缺口只有两条：
  常量折叠能补回 6 条 `target_table` 里的 2 条（`TARGET_TABLE = "CRYPTO_DAILY_MARKET"` /
  `"CRYPTO_HOURLY_MARKET"`），以及 `from akshare… import` 的名字从未被跟随。
  17 条 `single_source_function` 从来不是盲区。
* 各方法产量（这是本轮唯一有用的新数）：深 AST 0/72 + 2/6 表名；
  bytecode 覆盖 89/89、`co_filename` 89/89、**新名 0 个**（4 个表面命中是局部 def/字符串的
  `co_names` 伪影，所以幽灵表那次的 pyc 先例**不可复用**——源码在版本控制里且缓存与之一致）；
  注册表导出 0 个名字（`function_name` 恒为入口、89 行 `description` 全空，只作断言用）；
  **端点/参数/列切片签名对照**（对本地 akshare 树、helper 展平） uniquely named **37 条**
  ——qvix 靠 `k.csv` 加逐字相同的 `.iloc[:, […]]` 切片，jin10 靠 `category`/`attr_id`/`symbol` 三元组；
  人工判读 12 单命中 + 3 helper + 2 动态 + 11 其它。
* 分类落定：`RESOLVED_SINGLE 49 · RESOLVED_MULTI 17 · NO_AKSHARE_CALL 3 · DYNAMIC_UNRESOLVABLE 2 · OTHER 18`。
  静态可判的上界是 **71**（55 强证据 + 16 条改名推断，值得单独做一次廉价验证记录）；
  **18 条需要 `--source-verification-export`**（9 条 `movie_boxoffice_*` 卡在源端点漂移：
  AFI 抓 `ys.endata.cn/enlib-api`，akshare 仍调 `www.endata.com.cn/API/GetData`，
  这是 EXTEND_PROVIDER 与 REPLACE_SOURCE 的分岔，不是同名映射）；
  **4 条需要属主裁定**（2 条 NBS 浏览器按运行时 `indicator_ids` 键控，2 条 catalog runner 的
  `endpoints_flat.json` 不在版本控制里）。没有编造任何一个 `verified_at_utc`。
* 顺带两条值得留档的意外：`funds/weekly/__pycache__/option_hist_dce.cpython-313.pyc` 里
  **没有** tracked 源码所调用的 `option_commodity_contract_sina` / `_table_sina`（编译产物与
  受控源码漂移，只标注不采信）；`common/daily/print.py` 自己的注释写着
  "Scanner-generated placeholder; akshare has no callable named print" —— HELPER_ONLY。
* 交付：`docs/iterations/…/UNDECIDED_89_SOURCE_FUNCTION_TRIAGE_20261106.md`，
  以 **#311** 叠在 `feature/afi-ac11-dispositions`（#286）上，
  head `f761f0d5d3d7`，绑定自审；结论同时作为评论发到 #286
  （`…/pull/286#issuecomment-6688330567`）。#286 的 head 未被追加提交。

#### 19. 采集运行态：9 天全量失败的根因是 DEPLOYMENT，而且失败信息在已提交代码里根本不存在

子代理做根因定位、我独立复核并改写了它的结论。先给可复跑的事实。

* **失败窗口的边界（只读 SELECT，15:29–15:30 UTC）**：`error_message = 'AKShare script worker exited
  with code 1 without a result'` 共 **4281 行、1081 个任务**，`MIN(created_at)=2026-10-27 00:57`、
  `MAX(created_at)=2026-11-05 00:45`。这不是一个状态，是一个**已闭合的区间**。
* 机理（子代理四条腿证据）：调度器父进程派生 `python -m app.services.akshare.script_worker`，
  而该模块只以未提交文件形式存在于当时的树里；2026-10-27 08:56 CST 一次工作树回退把它删掉，
  父进程（2026-10-25 06:20 启动、未重启）继续派生 → `No module named …`、**exit 1**、无回执。
  佐证：`__pycache__/script_worker.cpython-313.pyc`（10-25 06:16）在没有任何 `.py`、
  也没有任何 git 历史的情况下存活；日志里那段故障引用的
  `scheduler.py:362/508/697` 与 `script.py:2536/1140/1119` **在 157 行的已提交 scheduler.py
  和 1823 行的已提交 script.py 里都不存在**；用该 unit 自己的解释器复现
  `.venv/bin/python -m app.services.akshare.script_worker` → exit 1（不是 2，
  `-m` 的模块缺失正是 1，与台账逐字吻合），且什么都不执行因此不写库。
* **我改写的一条**：子代理把恢复归因于「22:44:45 CST 重启到已提交代码」。顺序不干净——
  重启后的第一条 completed 在 **2026-11-05 14:02 UTC**，而 stable start 是
  `ExecMainStartTimestamp=Thu 2026-11-05 22:44:45 CST`（=14:44:45 UTC，NRestarts=0 至今）。
  在此之前该 unit 正在崩溃循环（journal 21:30:28→21:32:12 CST 的 restart counter 1434→1437）。
  故障与恢复之间 00:46–14:01 UTC 全库只有 **3 行**执行（13:57:03–13:58:02）。
  因此可证的是「树在崩溃循环窗口内被放回已提交代码」，**不可证**的是那一次 start 本身。
* **最要紧的一条，是子代理没看到的**：`grep -rn "AKShare script worker" src/backend --include=*.py`
  在已提交代码里 **0 命中**，而已提交路径 `app/services/akshare/script.py:502 _execute_callable`
  是**进程内**执行，不派生子进程。也就是说——**那条把九天全量失败写进台账的消息，
  无法由任何 ref 里的代码产生**。它属于部署态里一份与版本控制分叉的执行路径。
  这解释了为什么"恢复"不需要任何代码修复：换回已提交路径，同一批任务就成功了。
  结论因此改写 AC 面：**采集能跑不是待修项；待修的是部署溯源与可观测性**——
  一个进程可以带着不在版本控制里的代码运行 41 天，而台账只显示一句状态词。
* 恢复后的真实分布（≥2026-11-05 14:00 UTC）：**completed 474 / failed 99，208 个任务至少成功一次**；
  近 24h 为 438 completed / 96 failed。失败第一次呈现出**可归因的分类**，且与 #284 普查的预测对得上：
  `No callable entrypoint found for script …` 共 51 行 = 已停用幽灵队列那 7 个 slug
  （`fund_monetary_income_history` 26、`forex_hist_sina` 18、`fund_reviewed_unit_nav_history` 4、
  `etf_realtime_quote_sina`/`cffex_option_daily_history`/`commodity_option_daily_history`/
  `etf_option_daily_history` 各 1）；`_ingest_mode` 意外参数 **5 行 = 普查预测的 5 个
  daily_market_data 任务**；另有 `Script call timed out after 600 seconds` 26 行（1 个任务）、
  `returned no data and target table … is empty`（`spot_quotations_sge`、`futures_to_spot_dce`）。
* **停用是否生效，仍然不可判**，但我把可判点从"约 00:35 UTC"收紧了：
  13:47:56 UTC 停用之后幽灵 slug 的执行数是 0，**这不是证据**——它们的 cron 槽在 CST 08:00–09:43
  （=11-06 00:00–01:43 UTC，今天首条正是 `00:35:00`）与 CST 15:00/19:00，
  停用发生在这些槽之后。首个可判窗口是 **2026-11-07 00:00–01:43 UTC**（以及 07:00/11:00 UTC）。
  #306 记录的机理（`reload_active_tasks` 只遍历 active、从不注销已失效 job）预测：**在 #306 部署前它们仍会触发**。
* **运行面大小第一次有了下界**：armed 现 1048，其中 **827 个自恢复以来一次都没执行过**。
  所以任何 AC05/AC10/AC14 的覆盖陈述，此刻最多只能建立在 221 个已跑过的任务上。
  同时把上一轮那条作废规则限定清楚：「晚于 2026-10-27 00:55 的 freshness 陈述一律作废」仍然成立，
  但**从 2026-11-05 14:02 UTC 起写入的行是活数据**，可据以重新取证。
* 我自己两处旧陈述在此作废：(1) 「该 recovery worker 文件从未进过任何分支」——它今天已提交，
  `c16f00515` = PR **#273**，在 `origin/dev` 上，且 `src/backend/scripts/ops/run_full_history_recovery_worker.py`
  现在是被跟踪文件。(2) 上面那条「100% 失败」被写成了一种状态而不是一个区间。
  recovery unit 本身**仍在每分钟失败，但现在是诚实的失败**：
  `required runtime inputs missing: …/bond_convertible_history_controller.py`、`write_possible=false`,
  因为五条控制器腿全在未合入的 #283（`feature/afi-recovery-controllers` @ `0654231d70`）上——
  同一 provenance 缺陷类的"半落地"形态。#280（`fix/afi-killable-script-worker` @ `7ae5f29d81`）
  处理的是超时脚本在 run 结束后继续写库，属另一条腿。
* 待办（都不由本机闭合）：把服务钉到显式部署 checkout 并在脏树时拒绝启动（DEPLOYMENT，
  动 unit/CI 即 R3）；把子进程 stderr 与 traceback 落进 `mark_failed`（CODE，
  现在 4281 行故障的 `error_trace` 全空）；#280/#283/#306 落地后重跑
  `normalize_scheduler_clock.py --apply`。**本轮没有因为"采集恢复了"而把任何一格 AC 改判为通过。**

#### 20. 15:36 UTC 的一次整体复测：分子、分母与"停用的脚印"互相咬合

采集恢复之后，我把三件仪器在同一时刻重跑了一遍，结果是它们互为交叉验证：

* **#284 普查**（`scripts/task_param_audit.py`，只读会话，15:36Z）：`armed_tasks 1098→1048`、
  `tasks_audited 1048`、**`script_file_absent` 从 50 归零**、`binds` 仍 155、`unexpected_param` 仍 7
  （5× `daily_market_data` + 1× `etf_fund_hist_em` + 1× `stock_zh_index_daily`，全是 `_ingest_mode`）。
  也就是说，属主"停用幽灵任务"那条裁定在普查里留下了一个**只可能由它产生**的脚印——
  50 条不可绑定项里没有一条是被"修好"的，它们是被移出 armed 的。
  同时暴露一个新计数 `safe_default_injected_scripts=337`：886 个 `accepts_var_kwargs`
  里唯一可静态判定的子集，**尚未**被纳入 AC11 分子定义（纳入会虚增，先不用）。
* **AC11 分子**（#309 的 `scripts/ops/ac11_runtime_evidence.py`，`--since 2026-11-05T14:00:00+00:00`）：
  **168/1048**，序列 143/1098 → 155/1098 → 161/1048 → 168/1048 单调上升；
  四分类 `completed_and_grew 168 + completed_no_delta 40 + failed_only 13 + not_run 827 = 1048`。
  其中 827 与 §19 里由另一条独立 SQL 测得的"armed 自恢复以来一次未跑"**逐字相同**——
  两条链路没有共享代码，这个一致性是本次读数可信度的主要来源。
* **总体口径声明**：分母从 1098 变 1048 是运行态事实变化，不是我把口径改松了；
  任何引用 168/1048 的地方必须同时带 as-of 与所读总体，否则与旧的 /1098 读数不可比。

`not_run 827` 是本波给 AC05/AC14 的最重要一句：采集已经活着，但**它只跑到了 1048 个任务里的 221 个**。
在 #306 部署、cron 自然铺满之前，任何"全历史覆盖"或"自然周期已续期"的陈述都不成立。

#### 21. 把 AC01 的 hash 锚从一个"未解释项"变成一条有界的 provenance 缺陷（新仪器，44/1057）

上一轮我写下"CSV 的 hash 锚已失效，需从干净树重生成（891/1057 不匹配）"。本轮先否证它、再把它做过头的地方收回来，
最后得到一个此前没人测过、也无法靠读码得到的数：**不匹配不是一种情况，是三种。**

* 仪器：`evidence/2026-11-06-wave29/inventory_anchor_provenance.py`（只读；逐行比较当前字节，
  不等时再扫 `git log --all -- <path>` 的全部历史版本，直到命中锚值）。
  输出 `inventory_anchor_provenance.2026-11-06T1545Z.json`。
* 四桶实测（1066 行）：**match 166 / drifted 847 / never_versioned 44 / missing_file 9**。
* **drifted 847 是可解释、可再生的**：每条锚都命中一个真实 commit，且高度集中——
  `f669d8131`（2026-04-15 "chore(dev): snapshot current workspace changes"）699 条、
  `d001052bc`（2026-06-25）93 条、`1dbd991d7`（2026-07-18）32 条、`73324f83b` 14 条、
  `0b8ad7111` 5 条，另有 6 条单例。也就是说 CSV 的内容基线主要是 4–7 月的树，
  而 `7e46588c8`（#270）一次性改动了其中绝大多数——这与 §上一轮 的"891 条按最后触碰提交归因"完全一致。
* **never_versioned 44 才是真正的新发现**：这 44 行的 `source_sha256` **在 `--all` 的任何 commit 里都不存在**。
  我另外排除了"哈希输入被规范化"这一替代解释——对样本逐一测过
  raw / 通用换行 / 补末尾换行 / 去所有 `\r` / `splitlines()` 重join 五种变换，**全部不命中**，
  且这些文件本身没有 CRLF。因此唯一剩下的解释就是 #286 那条草稿里我原本只是"假设"的话：
  **CSV 是在一棵脏工作树上生成的**，而这 44 行永远无法由版本控制重放。
  44 行的构成（按"最后触碰它的提交"）：`7e46588c8`(#270) 15、`1dbd991d7` 13、`3e9f4a76e`(#275) 6、
  `d001052bc` 5、`b1ddf66fa` 2、`f669d8131`/`0b8ad7111`/`73324f83b` 各 1；
  按 `asset_family`：other 12、stock 10、fund 5、fx 4、futures 4、bond 3、crypto 2、option 2、index 2。
  **我原本想写成"集中在共享 helper（`_jin10_macro`/`currency_fallback`/`dict_result` 等）"，
  实测后撤回**：它们横跨九个资产族、八个最后触碰提交，形状是"盘点当天有一批未提交改动"，
  不是"某一类文件被特殊处理"。把成因说窄比把数数错更难查，所以这里只留分布，不留故事。
* 因此 AC01 判据里"无未解释项"这句，现在的正确写法是：
  **未解释项已从"整列锚不可信"收窄为"44/1057 行的锚无 provenance"**，且这 44 行是**有界、已命名、可逐条复核**的。
  重生成仍然是必须的，但它现在有两层含义：对 847 行是"更新读数"，对 44 行是"第一次真正建立锚"。
* 对 AC11 签核的影响（重要，避免我上一条把风险说重了）：`assign_script_dispositions.py` 的
  `review_file_sha256` 比对的是**工具当场重算的 `item.sha256`**，不是 CSV 里那列。
  所以这 44 行**不削弱**签字语义——签字说的是今天的文件，不是 10 月的那列数；
  需要修的只是别再把 CSV 的锚当作历史基线引用。#311 的 89 行分诊同理不受影响。

#### 22. 采集平面第三刀把 55 条可修族清零（95→40），以及一次"仪器少报 35 条"的自我拦截（PR #314）

子代理提交并推送后我去复核，**先撞到一个假读数，再决定信哪个**：

* 同一 head（`f40a6e1da`）、同一 `config/mypy_collection.ini`、同一 venv（mypy 1.20.2 +
  pandas-stubs 2.3.0.250703 + types-pytz，**无 types-requests**），
  在复用 `.mypy_cache` 的 worktree 里读成 **5 errors**；把 `--cache-dir` 指到空目录后读成 **40 errors**。
  原因可归：我早些时候做过 `types-requests` 装/卸的对照实验（159→119），缓存是在装有 stub 的窗口里写下的；
  卸载之后 mypy 仍回放缓存里"已解析到 stub"的结论，于是把 35 条 `import-untyped` 报没了。
  **方向很重要：这次误差是往好的方向偏**，如果我相信它，就会把"40 条残留"写成"5 条"，
  并让属主裁掉一个根本不存在的 stub 决定。因此本波之后所有 mypy 数字必须声明缓存状态。
* 用全新缓存双端复测，得到可比的一对数：base `0be658dad`（= dev + #305 + #308）**95 errors / 73 files**，
  head `f40a6e1da` **40 errors / 40 files**，`checked` 两端恒为 **1108**——
  检查面没缩，所以这不是"少查文件"换来的下降。55 条可修族
  （`call-overload 22 / return-value 15 / arg-type 9 / assignment 6 / override 3`）**全部清零**，
  残留 40 条逐条都是 `[import-untyped]`，与属主"stub 不在本波动"的裁定一致。
* 完整性我逐项查过而不是听汇报：diff 里 `# type: ignore` **0 处**；`config/`、`scripts/ci/` **未改**；
  改动只落在 `app/data_fetch/scripts/**`（41 文件 937+/89-）与一个新测试文件；
  `cast(` 新增 5 处，其中 `cast(mysql.connector.MySQLConnection, …)` 的模块在该文件第 8 行本就 import、
  且 `mysql-connector-python>=8.0.0` 是声明依赖（lock 里 9.7.0）——不是凭空指定的类型。
* 三类改动**确实动运行时**，PR 里单独声明并逐类钉测（不是静默的"打字工作"）：
  None 分支 ternary（依赖被钉住的 pandas `None→NaN/NaT` 契约，之前把 `None` 喂给强转会广播 NaN 列）、
  `save_data()` 外包 `bool(...)`（docstring 是 `-> bool`，兄弟文件早就这么写，消费方一律 `if success:`；
  测试钉 True/False 同一性而非 truthiness）、以及三个零参 `get_latest_date` 死覆写改名
  `_get_latest_trade_date`，从而让继承来的方法恢复按文档签名可调用。
  其余为纯标注/cast，用源码 census 钉。`pytest tests/test_collection_script_row_narrowing_wave3.py -q` **68 passed**，
  新文件里 24 个测试函数；`ruff check` 全过，`ruff format --check` 1123 files already formatted。
* **交叉验证来自另一个子任务**：#313（迁移清单锚仪器）独立复算出与我 §21 完全相同的
  **166 / 847 / 44 / 9** 四桶，并且给出更强的一条——从每个文件在 `29afaeb47`（CSV 生成提交）
  的内容重导派生列，可复现 **1053/1057** 行；只有 4 行的 marker 变化，且这 4 行全在
  "锚从未匹配任何 blob" 的 44 行里，**847 条真正轮坏的行的派生列一字不变**。
  这从另一个方向证实了 #270 确实只是标注性改动，而不是我此前只能声称的"看起来是"。
  那 4 行 `classes=` 里的类名（`SourceUnavailableError` 等）在仓库历史的任何 `.py` 里都不存在，
  只存在于 CSV 自己的 notes 里——盘点文件的既有缺陷，不是我的推导分歧。
* 平面**仍是 advisory**：#314 不产 baseline；基线冻结必须由 CI 自身读数经评审式 `--update` 单独成 PR
  （这是 `baseline_update_guard.py` 的存在理由，也是本波反复把"代码修复 PR"与"基线冻结 PR"分开的原因）。
  因此"95→40"在 CI 上被自己的读数确认之前，只是笔记本证据。

#### 23. AC11 的 `assigned=0` 现在被证明是"差一个签名"，不是"差一条通路"（scratch 端到端验证，零入账）

`assigned` 一直是 0，而 #286 的权限设计是"提案由工具做，分派必须由具名人类逐文件 hash 签字"。
0 有两种可能：签名还没来，或者签字这条路根本走不通。本波把后者排除掉了。

* 批次 `AC11-proof-01`（`--limit 40 --script-listing filesystem`，方法入库为
  `evidence/2026-11-06-wave29/ac11_assign_gate_proof.py`，**输出只落在 `--work-dir`（默认
  `/tmp/it204/ac11-proof/`），一个字节都不提交**）：工具自己产出 40 条提案
  （`EXTEND_PROVIDER 39 / HELPER_ONLY 1`），`assigned: 0`、`proposed (unreviewed): 40`、
  `UNDECIDED_INSUFFICIENT_EVIDENCE: 0`、`reconciliation problems: none`。
* **拒空名**：把 `reviewer` 留空、其余字段（`decision=approve`、`disposition` 与提案逐字相等、
  `file_sha256` 与工具当场重算的 sha 相等）全部填好再跑 → 40 条状态一律
  `review_missing_reviewer_name`。这道门是真的，不是装饰。
* **认签名**：仅把 `reviewer` 改成 `PROOF-NOT-A-HUMAN`（**故意用一个非人名标记，使这份输出永远不能被
  当作"有人批准过"的证据**）→ `assigned: 40`、`proposed: 0`、§6 口径的
  `assigned ratio 40/1057`，`decided_by` 写成
  `assign_script_dispositions/1 proposed; assigned by PROOF-NOT-A-HUMAN at 2026-11-06T16:02:00Z`。
* **逐文件绑定生效**：只把其中一行的 `file_sha256` 改成 64 个 0 →
  `assigned 39 / review_stale_for_sha256 1`。也就是说签名不能整批盖章后复用，
  文件一动就退回未分派——这正是 §6 要求"逐文件 hash 签字"的语义。
* 顺带得到 AC01 锚数字的**第三个独立来源**：这份工具自己打印
  `inventory sha agreement: {'no': 891, 'yes': 166}`，与 §21 的 166/847/44/9 拆分以及 #313 的复算
  三处一致。三个互不共享代码的仪器给出同一对数，是本节唯一值得一提的强度来源。

结论的准确写法：**AC11 的分派缺的是属主的一个名字与时间戳，不是工程**。
所以本波把"待属主"从模糊状态改写成一条可执行动作——对 `AC11-proof-01` 这批 40 条（或任意批次）
填 `reviewer` + `reviewed_at_utc` 后重跑 `--review-file`，`assigned` 就会离开 0。
我不替属主签这个名；这份 scratch 证明也不进账、不进仓，只用于排除"通路坏了"这一种解释。

#### 24. 队列长度的一个自找原因：OD 同一个 commit 跑两遍全量 gate，而修法被 digest 钉住卡住（新债，已定位到行）

本波一直被"CI 排队"约束，我去量了这个约束有多少是自己造成的。

* **计数**由 `evidence/2026-11-06-wave29/ci_duplicate_run_audit.py` 产出（16:16:32Z 复跑逐字一致，
  输出同目录 `.txt`）：OD **476 个不同 head_sha 中 56 个同时存在 `push` 与 `pull_request` 两种 run**；
  把两侧都限定为 completed 再配一次，得到 **55 对**——即 55 个 commit 在 OD 上把同一套作业跑了两遍。
  对照组很干净：**AFI 229 个 sha 里这样的重复是 0**。
* **根因在两行配置里**（不是 runner 故障）：`opendata/.github/workflows/ci.yml:4-7` 的
  `push.branches` 包含 `[dev, master, "feature/**", "fix/**", "docs/**", "refactor/**", "test/**"]`，
  同时 `pull_request.branches: [dev, master]`。于是推一个 PR 分支会起一次 push run，
  开放的 PR 又起一次 pr run。`ci.yml:22-24` 确实有 `concurrency: group: ci-${{ github.ref }}` +
  `cancel-in-progress: true`，**但两个事件的 ref 不同**（`refs/heads/fix/…` vs `refs/pull/N/merge`），
  所以按 ref 分组的并发控制天然合不掉这两条——这是一条"看着有防重复、实际防不住"的典型形状。
  AFI 的 `pr-check.yml:3-4` 只 `on: pull_request`，因此没有这个问题。
* **代价只能用"run 数"表述**（仪器里同一句已注明）：我试过把这个换算成 CI 分钟数，`/actions/runs/{id}` 的
  `run_duration_ms`、`timing` 以及逐 job 的 `run_duration_ms` 在本 org 的 API 返回里**全部为 null**（实测若干
  completed run），所以**本机无法证明分钟数**。写"浪费 X 分钟"会是编的；写"55 对重复 run"是证的。
  按 OD 的 `make gate` 是 18 个成员、池子只有约 3 个并发 runner 来定性：重复的是整条 gate，不是轻量作业。
* **修法被一处 provenance 钉住，这点必须写清**：`docs/quality/akshare-reference-allowlist.json`
  把 `.github/workflows/ci.yml` 登记为一个 allowlist entry，字段里有
  `sha256: abe808c1ab6d4f9488999664b14bf86b3ec103753c1fd0ad0b1262243f9f9f3f`，
  而 `scripts/quality/acceptance_item_probe.py:1252` 读的就是这份清单。
  我当场比对过：**当前 `sha256sum .github/workflows/ci.yml` 恰等于这个 pin**，说明钉是活的、准确的。
  因此任何触发条件改动都会移动该 sha256，必须同步重登记 entry（含 `reviewer`/`reviewed_date` 的人工注记），
  否则 AC-17|05 的重放面判定会红。这不是"顺手改一行"的修复。
* 两个候选形状，都属 **R3**（动 workflow + 动 provenance 清单），交属主定：
  （a）把 `feature/** fix/** docs/** refactor/** test/**` 从 `push.branches` 摘掉，只在 dev/master 保留 push 触发；
  （b）保留双触发，但把 concurrency group 改成按 sha 键（`ci-${{ github.event.pull_request.head.sha || github.sha }}`），
  让同一 commit 的两条 run 互相取消。
  (a) 会失去"PR 之前先给一次反馈"的用途；(b) 保留用途但把 `cancel-in-progress` 变成跨事件生效。
  我倾向 (b)，因为它的取舍更少；但这属主的调用，本波不擅自改 workflow。

#### 25. 那 9 条 `movie_boxoffice_*` 的分岔，本波用一次真实源运行把它从"待验证"变成"有输入"（新仪器，含对照）

#311 的分诊说：这 9 条卡在源端点漂移，"一次真实源运行就能在 EXTEND_PROVIDER 与 REPLACE_SOURCE 之间定夺"。
我跑了那次运行，并且先把"0 行"这条最容易骗人的证据做了对照——**akshare 的包装函数在请求失败时
同样返回空 DataFrame**，所以 0 行既可能是"源没数据"，也可能是"这台机器够不着源"。不区分这两种就下结论，
是本轮最可能犯的错误。

仪器：`evidence/2026-11-06-wave29/source_egress_probe.py`（只读，输出同目录
`source_egress_probe.2026-11-06T1622Z.json`），16:22:19Z：

* **出口能力对照（必须先有）**：`ak.stock_zh_index_daily('sh000001')` → **8758 行**、
  `ak.macro_china_ppi()` → **249 行**。这台机器能出网，因此后面的空结果**不能**推给网络。
* **上游侧（akshare 用的路径）**：`movie_boxoffice_daily / _cinema_daily / _cinema_weekly / _weekly / _monthly`
  在 `20240219 / 20250101 / 20260105 / 20261104` 四个日期上**全部 0 行**（20 次观测无一例外）；
  `movie_boxoffice_first_week` 在本机安装的 akshare **1.18.64 里根本不存在**。
  另测 akshare 老上游 `www.endata.com.cn/API/GetData/` 的 POST → **HTTP 405 Not Allowed**（nginx 拒）。
  405 与"函数返回空"是两条独立观测，**因果链是合理推断而非实测**：我没有证明该函数就走这个 URL。
* **AFI 自己那侧**：直接实例化树内 `common/_endata_yien.EndataYienClient` 调它的方法——
  `now_date()` → **`2026-11-06`**、`latest_completed_day()` → **`2026-11-05`**、
  `date_data` 返回 **12 键** dict（`table0…table11`）。即 **AFI 用的 `ys.endata.cn` 路径是活的**。
  一条反例也要记：我先用裸 POST 打 `getCommon_DateList.do`，拿到 **200 且 0 字节**（3/3），
  差点据此写"AFI 这条路也死了"；差别就在有没有带 helper 的参数。**空响应不等于空数据源**，同一条原则两侧都适用。
* 因此这 9 条现在的准确状态是：**决策输入已到位**——"复用 akshare 作为 provider"在实测意义上不可达，
  可用的是 AFI 自带的取数路径。但**我没有替属主把 disposition 改掉**：#286 的分类由输入与 review 决定，
  而 `assigned` 仍须具名签字。本波只把这条从"要跑一次"推到"跑过了，结果在此"。

顺带一条对**其它**行的硬约束（它限制了 AC10 与余下 18 条在本机可证的范围）：

* `push2.eastmoney.com` 与 `82.push2.eastmoney.com` 各 3 次尝试**全部 ConnectionError
  （RemoteDisconnected）**，而 `datacenter-web.eastmoney.com` 与 `data.eastmoney.com`
  三次都 200。所以这不是网络抖动，是**按主机**的不可达。
  含义：依赖 push2 行情面的 `*_em` 脚本**在本机做不出真实源逐字段对照**——任何这类"已对照"的陈述
  在这台机器上不可产生，必须换主机或换出口。这与 §24 的"某些量本机测不出"是同一种诚实，
  不是进度问题。

#### 26. 同一仪器顺手把其余待定名与一类失败归因也测了：两个函数在本版本 akshare 里不存在，DCE 那条是源侧空

把 §25 的仪器加了 `--names` 再跑一次（`source_egress_probe.2026-11-06T1625Z.json`，16:25Z，出口对照同批仍是活的），
几条原来只写作"需真实源验证"的行现在有了观测：

* `cost_living`、`shfe_stock_weekly`：在 akshare **1.18.64 里根本不存在**（`ABSENT_IN_INSTALLED_AKSHARE`）。
  这不是"数据取不到"，而是"没有可复用的上游函数"——#311 原来把 `cost_living` 记作
  "name absent from the upstream export set"，现在在**本机安装的版本**上得到了直接印证。
* `macro_china_nbs_nation(kind, path, period)` / `macro_china_nbs_region(kind, path, indicator, region, period)`：
  无参调用直接 TypeError 报缺 2 / 3 个必填参数。这把 #311 里"通用浏览器、数据集由运行时
  `indicator_ids` 选定"的判断从描述变成**签名级证据**：它们不是某个数据集的入口函数，
  因此"一条脚本 ↔ 一个 akshare 函数"的映射模型对这两行本身就不成立，属主裁的是映射模型的例外处理，不是选哪个函数。
* `futures_to_spot_dce(date=…)`：20240219 / 20250101 / 20260105 / 20261104 **四个日期全 0 行**；
  `option_hist_dce(symbol, trade_date)` 无参也是 0 行。
  这条有额外价值：§19 的恢复后失败清单里有一类
  `Script futures_to_spot_dce returned no data and target table futures_to_spot_dce is empty`（4 行 1 任务），
  当时只能说"脚本没拿到数据"。**现在能进一步说：上游同名函数在同一批日期上也是空的**，
  所以这不是 AFI 侧代码坏，而是源侧对该标的/日期无供给——即 §5 词汇里的 SOURCE_LIMITED 形态。
  仍需注意别把这条推远：0 行是四日期样本，不是"该函数永久无数据"；且 DCE 系列是否受
  push2 那类主机不可达影响，本轮未测（`datacenter-web`/`data.eastmoney` 可达，DCE 域名未测）。
* 由此 AC11 的 89 行状态可以准确地重述为：静态可判 **71**；9 条 boxoffice 已有 §25 的决策输入；
  2 条在 akshare 里不存在（`cost_living`、`shfe_stock_weekly`）；
  2 条 NBS 有签名级证据说明映射模型不适用；其余仍是"需要 `--source-verification-export` 或属主裁定"，
  没有因为这几条测好了就把整格往上抬。

#### 27. AC11 第一次有了 `REUSE_PROVIDER`：0 → 6 行，每行都有一次非空的真实源调用背书（含两处"够不着"的诚实边界）

这是本波对"脚本半区处置分派"最实在的一次推进，而且起点是一个我自己差点写错的数。

* **先纠正我自己的读法**：第一次统计"有多少行的 `source_function` 被 OD 已注册 fetcher 引用"时，
  我把 ledger 里的 `evidence` 当成 list 遍历，得到 **0**，据此几乎要写"REUSE_PROVIDER 在本 iteration 不可达"。
  实际 `evidence` 是**字符串**，逐字符迭代让所有子串匹配都失败了。重做后正确值是 **8 行**。
  这条留在这里是因为它的形状很典型：**一个解析 bug 会伪装成一个实质结论**，
  而"0 个"这种干净的答案尤其值得先怀疑自己的代码。
* 全树普查（`--limit 0`，1057 行）现在的准确分桶是：
  `EXTEND_PROVIDER 954 / UNDECIDED_INSUFFICIENT_EVIDENCE 89 / REUSE_PROVIDER 6 / HELPER_ONLY 8`，
  `assigned` 仍 **0/1057**，`reconciliation problems: none`；
  族分布 other 317 / stock 384 / index 93 / fund 87 / bond 41 / option 46 / futures 64 / fx 20 / crypto 5，
  归属 owner:B 604 / owner:C 445 / review 8。同一输出再次打印
  `inventory sha agreement: no 891 / yes 166`，与 §21、#313 三处一致。
* **6 行的来路**：仪器 `evidence/…/verify_adapter_backed_functions.py` 只打那 8 个
  "被 OD fetcher 引用"的上游函数，参数取自 `inspect.signature`（**前一轮我有两个调用是因为
  自己传错参数而失败**——`option_sse_daily_sina` 我按 `date=` 传、它其实收 `symbol`；
  `stock_financial_analysis_indicator_em` 我传裸 `600519`、它要 `301389.SZ` 这种带市场后缀的形式；
  修正后两者分别得 23 行与 26 行，所以那两条不是"源不可用"而是"我用错了"，这个区分必须留下）。
  最终 **6 个非空**：`bond_zh_hs_cov_daily` 4806、`futures_zh_daily_sina` 260、
  `stock_financial_report_sina` 118、`stock_history_dividend_detail` 36、
  `option_sse_daily_sina` 23、`stock_financial_analysis_indicator_em` 26。
* **只有非空才算验证**——0 行或异常的记录故意不进 export，
  否则记录的含义就从"这条数据真的能取到"变成"我们试过"，等于用分子去掩盖失败。
  剩下 2 行的失败原因还做了主机级归因，不笼统写成"源无数据"：
  `fund_etf_hist_em` 抛 RuntimeError 并**直接点名** `https://push2his.eastmoney.com/...`，
  同批直连该主机 3/3 `ConnectionError`；`index_zh_a_hist` 在两组参数下返回 0 行，
  而它走的正是同一家族的行情主机。所以这 2 行的准确状态是**本机不可验证**，不是"源侧为空"。
* 把 6 条记录喂回 `--source-verification-export` 后，工具给出
  `EXTEND_PROVIDER 954 / REUSE_PROVIDER 6 / HELPER_ONLY 8 / UNDECIDED 89`，
  逐行 diff 恰好是**那 6 个文件** `EXTEND_PROVIDER → REUSE_PROVIDER`，其余一字未动——
  这是本迭代里第一次有行的 disposition 拿到真实源证据支撑，也是唯一一次由"记录"驱动的迁移。
* **它不构成任何闭合**：`assigned` 依然 0，§6 的分子仍须具名属主逐文件 hash 签字；
  REUSE_PROVIDER 只是提案。而且上限写死在这里——OD 的 akshare 侧只有 10 个 provider 模型、
  引用 9 个函数名，对 1057 行里 961 个 distinct `source_function`，
  所以即使把这 8 行全验证完，`REUSE_PROVIDER` 的理论上限也就是 8（其中 2 行本机够不着）。
  这不是进度慢，是 §AC01 那条"接收侧能力是 12 个函数对 1057 个脚本"的直接后果。

#### 28. 运行资产平面从"未入库"升级为"无处可取"：8 个 unit 的 ExecStart 目标既不在磁盘也不在任何 ref，其中 5 个仍在定时触发，一个已重启 4,738 次

这条比上一轮的"9 条无文件注册"更硬，因为方向相反：那一轮说的是"注册了但文件不在树里"，
这一轮说的是"systemd 正在按计划反复执行一个**这台机器上根本不存在、git 里也从来没有**的文件"。

仪器：`evidence/2026-11-06-wave29/unit_execstart_existence.py`（只读：`systemctl show` /
`list-timers` / `list-units` + `os.path.exists` + `git ls-files --error-unmatch`），
输出同目录 `unit_execstart_existence.2026-11-06T1635Z.json`。16:36Z 读数：

| 单元 | ActiveState | NRestarts | 是否仍有活定时器 |
|---|---|---|---|
| `dce-browser-capture` | failed | 0 | **是**（下次 Sat 11-07 19:36 CST） |
| `dce-option-daily` | failed | 0 | **是**（Sat 11-07 20:06 CST） |
| `dce-option-recovery` | inactive | 0 | 否 |
| `etf-nav-backfill@`（实例） | activating | **4,738** | 模板常驻 auto-restart |
| `option-history` | inactive（enabled=disabled） | 0 | 否 |
| `policy-expiry-watchdog` | failed | 0 | **是**（Sat 11-07 01:00 CST） |
| `stock-amount-daily` | failed | 0 | **是**（Sat 11-07 04:03 CST） |
| `stock-tail-daily` | failed | 0 | **是**（Sat 11-07 21:10 CST） |

汇总：**8 个单元的 ExecStart 目标全部缺失**，且**8 个目标路径全部不在 git 索引**（不只是不在工作树），
**5 个仍挂在活定时器上**按点触发，`etf-nav-backfill@0` 的重启计数**还在往上走**
（我第一次手工查是 4,733，仪器这次读到 4,738——它每 30 秒失败一次，这个数本身就是一个持续噪声源）。

这条对验收的准确含义，以及我特意**不**推出的结论：

* **AC01**：判据要的是"运行资产可枚举"。此前我把这一面写成"live unit 指向的文件不在工作树"，
  语气像是"文件在宿主上、只是没提交"。实测是更糟的一种：**磁盘上也没有**，
  所以它连"从本机恢复"的路径都没有，只能从别处找回或重写。
  `#283` 之后 9 条里入库 2 条的说法同时作废——按这份新仪器，8 个 unit 目标一个都不在索引里。
* **AC05 / AC12（补采与恢复面）**：这 5 条定时线覆盖的正是 DCE 期权恢复、ETF 净值分片回补、
  股票成交额回补、股票尾段切片、保单到期看门狗。它们**看起来是开着的**（enabled + timer 在跑），
  实际从未成功过。所以"全历史恢复在推进"这句话在这些线上不成立，
  而且成立的是 §19 的同一机理的另一种形态：**运行态与版本控制脱钩**。
* 我**没有**据此得出"这些任务的数据因此缺失了多少"——那需要逐表逐标的对账，
  本机既没有这些脚本的源码、也没有源原生日历，属于不可由本机闭合的部分。
* 我**没有**动任何一个 unit：停 / disable / mask 都是改变共享运行态，属主授权覆盖的是
  生产写与补采，不含关停服务。处置建议只有两条，都需要属主点头：
  (1) 找回这 8 个文件的来源并入库（配合 #285 的 ExecStart 目标审计）；
  (2) 若确认已废弃，就停掉对应 timer 并把 unit 从宿主移除，
  否则它们会一直以"enabled 但永远失败"的形态污染 AC01 的运行资产计数与 AC12 的部署判读。

#### 29. 那 8 个缺失目标的可恢复性分界：2 个有字节码、5 个彻底没有，而"有字节码"不等于"能恢复源码"

§28 停在"磁盘和索引里都没有"。这条只回答属主真正要的那个问题：**那还要不要找回来**。
方法（`evidence/2026-11-06-wave29/find_missing_runtime_assets.py`，只读 `find`，
覆盖 `~/Documents` / `~/afi204-evidence` / `~/.config/systemd` / `/var/tmp` / `/tmp`）：
7 个不同目标里 ——

* **5 个 `.sh`**（`run_dce_browser_capture.sh`、`run_dce_option_recovery.sh`、`run_etf_nav_shard.sh`、
  `run_option_history_loop.sh`、`run_stock_tail_slices.sh`）**在这台机器上任何地方都不存在**。
  shell 脚本也不会有字节码。这一类是**真没了**：要么从别的宿主/备份取，要么按 §28 的处置 (2) 连 timer 一起退役。
* **2 个 `.py`** 有 `cpython-313.pyc`：`backfill_stock_amount_sina`、`policy_expiry_watchdog`
  （且同一份字节码已作为取证副本存在 `~/afi204-evidence/2026-11-06-ghost-code-plane/pyc/ops/`）。
  用 `marshal` 直接读 code object 能看到相当完整的骨架：前者的模块 docstring
  （"Backfill raw A-share turnover from Sina into an amount sidecar table"）、12 个顶层函数名
  （`_fetch_sina_kline_amounts`、`_normalize_amount_frame`、`_sequence_sha256` 等）、
  连 DDL 与源标识字面量都在（`STOCK_ZH_A_HIST_AMOUNT`、`akshare.stock_zh_a_daily`、
  `sina.klc_kl.js#amount`）；后者给出 `PolicySnapshot`、`load_server_policy_catalog`、
  `chinabond-2026-reviewed-v1`、`Asia/Shanghai` 等。
* **但这里必须把话说窄，不能滑成"可以恢复"**：
  (1) `.pyc` 里没有注释、没有原始排版，且 **Python 3.13 的字节码目前没有可用的反编译器**
  （本机 `uncompyle6`/`decompyle3` 一类根本没装，它们本来也只支持到 3.8 代际）；
  (2) 所以能拿回的是**规格与结构**，不是**源码**。据此起草一份 `.py` 是**重新实现**，
  必须在 provenance 上标成"由字节码重建的新实现"，不能写成"找回了原文件"——
  这正是 §19/§28 那类"运行态与版本控制脱钩"最容易被我二次制造出来的地方：
  如果我把重建文件当作原文件提交，AC12 的"部署的就是仓库里的"会重新变成假话。
  一个佐证细节：两份字节码的 `co_filename` 一个是绝对路径、一个是相对路径
  （`src/backend/scripts/ops/policy_expiry_watchdog.py`），
  与 §28 里 unit 用相对 `ExecStart` + `WorkingDirectory` 的写法互相印证——
  这两份代码本来就跑在两种路径解析下。
* 因此给属主的判断面收窄成三件可做的事，我一件都不替你做：
  (a) 若存在别的宿主/备份，`.sh` 5 个只有这条路；
  (b) 若选择按字节码重建 2 个 `.py`，需要接受"实现而非恢复"的标注，并为它们补测试再入库；
  (c) 若都不做，就停 timer + 移除 unit，让 AC01 的运行资产计数变成"明确已废弃"，
      而不是"看起来 enabled"。
  本波没有创建任何重建文件，也没有改动任何 unit。

#### 30. #285 合入后，同一件事被第二个实现复核：7 个缺失目标逐字相同，而 `gitignored` 那 6 条不该追

`check_service_runtime_assets.py`（835 行，#285 于 16:38:37Z 合入 dev `1bab6a956b`）与我的
`unit_execstart_existence.py` 是**两份独立实现**。在 16:39Z 对它跑一次本机只读审计：

* 汇总行：`unit_files_scanned=19 units_audited=16 units_without_exec=6 green_units=5
  units_with_findings=11 missing_file=11 ok=3 outside_repo=4 gitignored=6`。
* **`missing_file` 去重后恰是 §28/§29 那 7 个目标**（5 个 `.sh` + `policy_expiry_watchdog.py` +
  `backfill_stock_amount_sina.py`），每条都注 "absent and in no branch index"。
  两个实现、两套解析路径（我按 `os.path.exists` + `git ls-files`，它按自己的 scope 判定），
  给出同一集合——这条因此不再是"我的工具说什么"。
* 它还补了一条我没测的 systemd 侧证据：**`ExecMainStatus=203`**（"无法 exec"），
  与 §19 里我区分过的 203/2 语义一致——文件根本不存在，所以连解释器都没起来，
  不是脚本自己退出 1。这条把"这些单元从未成功过"从推断升级为 systemd 的直接读数。
* **`gitignored=6` 与 `outside_repo=4` 不是债**，别去追：逐条看是
  `src/backend/.venv/bin/python`（4 处）、`node` / `vite.js` / `hermes-agent/venv/bin/python` /
  `/usr/bin/node` / `openclaw/dist/index.js` 这类解释器与外部宿主路径，
  外加一份生成物 `var/reports/iteration203/policy-expiry-watchdog/service-current.json`。
  venv 与 node_modules 按设计就不该入库。我把这条写下来是因为这类"工具报了 11 个 findings"
  很容易被读成"11 个都要修"，而真正的问题集合仍是 7。
* `ok=3` 里出现 `run_full_history_recovery_worker.py` 与 `run_with_core_environment.py`——
  即 §19 那个曾以未提交形态存在的 worker 现在确实被跟踪，与前文的更正一致。

**这个新工具本身的状态要写准。** 它**没有**被接进任何 workflow：我在合并后的 dev 上对
`ci.yml`、`pr-check.yml`、`nightly.yml`、`Makefile` 全文 grep `check_service_runtime_assets`，
**0 命中**；#285 只加了脚本 + 一份测试（835 + 672 行）。而且它默认退出码 0，
只有带 `--fail-on-findings` 才会红。这里不能套用 §16 的"没进 CI 就是债"：
它审计的是**这台宿主的 systemd 单元**，CI runner 上没有这些单元，接到 CI 里天然测不到东西。
正确的处置面是宿主侧：把它挂进宿主的周期性运维检查（或加一个只读 timer），
并用 `--fail-on-findings` 使结果可门控。§28 那三个处置选项因此不变，
只是现在"发现"这一环已经不再依赖我手搓仪器。

#### 31. 采集平面的真实刻度是 CI 的那一把：101 → 37 → 7，而本机一路用的 159/125/95/40 是另一个环境的读数

本波我反复说"CI 同命令"，命令确实同一条（`mypy_ratchet.py --scope collection --advisory`，mypy 1.20.2），
**但环境不是同一个**。这一条是本轮对类型平面最重要的一次自我更正，而且它同时纠正属主裁定的前提。

* **CI 侧读数（先拿到权威刻度）**：dev `0a4c5ab31` 的 push run 42224170243 里
  `Backend - Mypy Ratchet (collection scripts, advisory)` 作业日志原文是
  `advisory, no baseline yet - errors=101 checked=1108 (mypy 1.20.2 (compiled: yes))`。
  我的笔记本在同一 commit 上跑同一条命令得到的是 **159**。
* **差异的原因在依赖集里，不在代码里**。CI 装的是 `config/requirements-dev.lock`：
  Python **3.11**、pandas **3.0.3**、numpy 1.26.4、akshare 1.18.97、
  `types-pytz` / `types-pymysql`，**没有 pandas-stubs**（pandas 3 自带类型）。
  我这把尺子是 Python 3.13、pandas **2.3.3 + pandas-stubs 2.3.0.250703**、numpy 2.1.3、
  akshare 1.18.64（可编辑安装）、无 types-pymysql。
  差别直接落在本波主修的族上：`to_datetime` 重载、`TimestampSeries` 这些形状，
  pandas 2+stubs 与 pandas 3 自述类型给出的签名根本不是一套东西。
* **我建了 CI 的镜像环境并先证明它等于 CI**：`/tmp/it204/venv-ci`（Python 3.11.15 +
  全量 dev.lock + `pip install --no-deps -e .`），逐包核对
  mypy 1.20.2 / pandas 3.0.3 / numpy 1.26.4 / akshare 1.18.97 / types-pytz 2026.x /
  types-pymysql 1.2.x / **pandas-stubs ABSENT**。在它上面跑 dev `0a4c5ab31`：**errors=101, checked=1108**
  ——与 CI 逐字相同，镜像成立后我才用它测别的。
* **CI 刻度下的真实链条**：
  | 树 | CI 环境 | 本波笔记本环境 |
  |---|---|---|
  | dev `0a4c5ab31` | **101** | 159 |
  | + #305 + #308（`0be658dad`） | **37** | 95 |
  | + tranche 3（`f40a6e1da`，即 #314） | **7** | 40 |
  两端都保持 `checked=1108`，所以不是缩小检查面换来的下降。
* **两处必须承认的认知反转**：
  (1) 我说"残留 40 条全是 `import-untyped`（requests stub）"，在 CI 环境里**根本不存在这个族**——
  dev 的 101 里 `import-untyped` 只有 **2** 条，而且是 `dateutil.relativedelta` 不是 requests。
  那 40 条是我这把带 pandas-stubs/无 types-requests 的尺子造出来的读数。
  属主"不为 stub 动 types-requests"的裁定本身仍然成立（它同时解释了 app 面 0→+6 的代价），
  但**引用它时不能再说"CI 上会看到 40 条"**，因为 CI 看不到。
  (2) 更糟的方向：**我的环境把 4 条真实错误藏起来了**。
  `stock_hot_up_em / stock_hot_rank_em / stock_hk_hot_rank_em` 第 46 行与
  `macro_china_urban_unemployment` 第 88 行的
  `Argument "json" to "post" has incompatible type …; expected "JsonType" [arg-type]`
  在 CI 环境里从 dev 起就一直存在（我逐条比对确认**先于本波三刀存在**，不是 tranche 引入的回归），
  而我这把尺子因为 requests 是未类型化的 `Any`，压根不报。
  也就是说：一个环境把不存在的错误报给我，另一个把我该看的错误藏起来——两次我都只信了自己这一把。
* **dev 的 101 在 CI 环境里的族分布**（我此前从未按 CI 环境分过族）：
  `operator 23 / var-annotated 15 / return-value 15 / arg-type 14 / union-attr 9 / str-bytes-safe 7 /
  valid-type 5 / assignment 5 / override 3 / import-untyped 2 / index 1 / dict-item 1 / call-overload 1`。
  其中 `var-annotated 15` 与 `valid-type 5` 这两个族在本波任何记录里**从未出现过**——
  它们只在 CI 环境可见。这条直接说明：之前"剩余债务就是那 55 条"的说法是环境错位的，
  真实剩余面应以这 13 个族为准重排。
* **tranche 3 之后的 7 条残留**（CI 环境，逐条）：4 条上面已说明的 `JsonType` arg-type、
  2 条 `dateutil.relativedelta` 缺 stub（`types-python-dateutil` 不在 lock 里，属依赖决定而非代码债）、
  1 条 `assignment: str | AttributeValueList`。**没有一条是本波引入的**。
* **对基线冻结（本波未做的那一步）的直接影响**：将来冻结
  `config/mypy_collection_baseline.json` 时，唯一合法的数字是 **CI 作业自己打印的那一个**
  （今天 dev 是 101，#314 合入后应读 7），
  而不是笔记本在带 stub 的 pandas 2 环境里得到的任何一个数。
  这把 §22 里"基线只能由 CI 自身读数冻结"的抽象规则变成了一个具体可核对的数：
  **如果哪个 PR 声称基线是 40，它一定是拿我这把尺子量的，那就错了。**

补一条同批验证，因为它决定这三刀能不能就这么合：把三刀的测试放进 **CI 的环境**
（`/tmp/it204/venv-ci`，Python 3.11 + pandas 3.0.3 + akshare 1.18.97 + 无 pandas-stubs）里跑，
`test_collection_script_row_narrowing_wave3.py + test_collection_script_type_shapes.py +
test_collection_script_entry_points.py` = **100 passed / 26.20s**，与 pandas 2.3 环境下的 100 passed 一致。
这点原本不保证：tranche 3 的行为等价性论证里，None 分支 ternary 依赖的正是
"被钉住的 pandas 会把 `None` 强转成 NaN/NaT"这条库契约，而 pandas 2→3 恰好是最可能改这条的跨度。
实测两侧同结果，因此 #305/#308/#314 的形状钉不是只在我这把尺子下成立。
（仍要说清边界：这只覆盖那三个文件里 100 个用例的范围，不等于整个后端套件在 pandas 3 下绿——
那要等 CI 自己跑。）镜像构建脚本一并入库：`evidence/2026-11-06-wave29/build_ci_env_mirror.py`；
CI 环境逐条错误清单：同目录 `collection_plane_detail_CIenv_dev_0a4c5ab31.txt`。
### Wave 30（2026-11-07）：把 #306 部署上去，才发现"部署成功"本身要先跑迁移

#### 1. 部署：#306 已合入，但"更新代码 + 重启"会让服务起不来（exit 3），原因不是 #306

上一波记录过"部署了但没重启"。这一波真的重启了，于是撞上一个此前没人踩过的形状：

* 主工作树快进到 dev `eaf03cb56`（含 #306 的 UTC 时钟、#305/#308 的采集平面、#310 的治理声明文档），
  `systemctl --user restart ai-for-investor.service`。
* 结果：**6 次 `status=3/NOTIMPLEMENTED` 崩溃循环**，每 ~10 秒一次。`/docs` 全程 000。
* 日志里没有 traceback，只有启动走到了 `app.startup.database:register` 的
  `DB_AUTO_CREATE_SCHEMA=false: Verifying database migration revision...`，然后 **1 秒内**
  `lifespan:170` 直接 shutdown——即"迁移版本核对失败 → 主动退出"，不是导入错误、不是代码异常。
* 实测对照：代码 `alembic heads` = **`20261106_akshare_run_coordinator_claims`**（#289 昨晚合入的新迁移），
  库 `alembic current` = **`20261101_stock_analysis_report_evidence_vector`**。差一个 revision。
* 处置：先确认该迁移是**纯增量**（`op.create_table` + `create_index`，`drop_table` 只在 downgrade 里），
  再 `alembic upgrade head`（库内写入，属主已授权"生产写与补采"），随后 systemd 下一次自动重启即恢复：
  `active`、`/docs` **200**、`ExecMainStartTimestamp=2026-11-08 01:22:14 CST`。

**这条要进 AC12 的判断面**：一个"只更新代码不跑迁移"的部署会让 API 完全不可用，而失败形态是
一行 `status=3`，没有 traceback。把"部署定义"写成"代码 + 迁移 + 重启"三件套，是这台机器上可证的；
反过来，"代码已在 dev 上绿"绝不等于"生产可用"。同时说明我上一波的
"部署态跑的是旧代码"已作废——现在跑的就是 dev `eaf03cb56`。

#### 2. 时钟迁移：416 条 `last_execution_at` + 1048 条 `next_execution_at` 一次校正，写后归零

在**代码已部署且采集器已重启之后**才跑 `normalize_scheduler_clock.py`（脚本自己把这条顺序写在输出里）：

* dry-run：`last_execution_at` shift **416** / already-utc **613** / no-execution 0 / stale-column **19** / unclassified 0；
  `next_execution_at` shift candidates **1048**。
* `--apply`：shifted last **416**、shifted next **1048**；before-image 1048 行写入
  `/tmp/ac11-clock-before-20261107T172321Z.json`，已复制到
  `~/afi204-evidence/2026-11-07-deploy/` 存档。
* **写后重分类就是证明**：`shift` **0** / already-utc **1029** / stale-column **19** / unclassified 0。
  那 19 条不是时钟问题（列比最新执行还旧，是"列未被维护"的另一个缺陷），脚本按设计不碰它们。
* 416 比上一波读到的 214 大，是因为上一波之后旧代码又持续写了 ~17 小时——这个计数只会随旧写者运行而增长，
  引用必须带时刻；这也解释了为什么"先部署再迁移"的顺序不可颠倒。

#### 3. 部署后的写者验证：`last_execution_at` 不再比真实执行晚 8 小时

重启后新产生的执行行（只读比对）：

| task | `last_execution_at` | 该任务最新 `ak_task_executions.created_at` | 差 |
|---|---|---|---|
| 521 | 2026-11-07 17:30:00 | 2026-11-07 17:30:00 | **0.0 min** |
| 667 | 2026-11-07 17:28:02 | 2026-11-07 17:28:00 | **0.0 min** |
| 531 | 2026-11-07 17:24:30 | 2026-11-07 17:24:24 | **0.1 min** |

同一个连接里 `NOW()=2026-11-08 01:31:13` 而 `UTC_TIMESTAMP()=2026-11-07 17:31:13`，
确认库会话时区是 CST 而列里存的是 UTC。**#306 的双写时钟缺陷在新行上已经消失**；
旧行的偏移由 §2 的迁移补齐。这一格此前只能写"修复待部署"，现在可以写"已部署并实测"。

#### 4. AC13 的判定窗口到了：停用后的幽灵任务确实又跑了 48 次，然后随部署停止

上一波把可判窗口定在 2026-11-07 00:00–01:43 UTC。读数（只读）：

* 停用时刻 `2026-11-06 13:47:56` 之后，`No callable entrypoint found for script …` 仍有 **48 次**：
  `fund_monetary_income_history` 26（00:35–01:43）、`forex_hist_sina` 18（前一日 22:30–01:42）、
  `fund_reviewed_unit_nav_history` 4（00:45–00:51）。而 `is_active=1` 的 armed 数全程是 **1048**。
* 这**逐字证实**了 #306 修的那条机理：`reload_active_tasks` 只遍历 active、从不注销已失效 job，
  所以把行置 `is_active=0` 之后，**仍在运行的调度器会继续按旧注册触发**，直到进程重启。
* 因此"停用 50 个幽灵任务"这一动作的效果边界是**进程生命周期**，不是事务提交时刻。
  部署+重启后这些 slug 不再出现在注册里；**下一个可判点是今晚 22:00 UTC**（CST 06:00）的槽位——
  若届时 0 次执行，则 AC13 这一半从"未生效"翻为"已生效（且原因已定位）"；本波不预判。
* 顺带把"停用是有代价的"再钉一次：这 50 个任务的失败是幽灵注册唯一可见信号，停用后该信号消失，
  可见性净降；这条此前已登记，现在有了具体时间线。

#### 5. 队列：五支合入，两支因 ruff 版本漂移被打回，一支已重基

* 已合入 dev：**#305**（机械族）、**#306**（UTC 时钟 + 注销失效 job）、**#308**（逐站点按 DDL 收窄）、
  **#309**（AC11 运行证据仪器）、**#310**（治理声明文档 + 钉形状的测试）、**#311**（89 行分诊）。
* **#308 的合入带出一条经验**：它是叠在 #305 之上的，而 #305 先以 squash 合入，于是 #308 变 `dirty`；
  本地 `merge origin/dev` 后 8 个文件 `UU`，逐个取 `--ours`（我们这一侧是 #308+#305 的超集），
  再实测平面 **7/1108（CI 环境）** 未回退、96 个平面测试通过、ruff 干净，才推送并重绑自审。
* **#313/#314 的失败不是代码问题，是格式化工具版本**：CI 在 `ci.yml:397` 硬装
  **`ruff==0.16.2`**，而 `config/requirements-dev.lock:431` 钉的是 **`ruff==0.15.13`**。
  两个版本 `ruff format` 的输出不同，所以"本地 format 干净 → CI format 不过"会稳定复现。
  本波按 CI 的版本（0.16.2）重排并推送，两 PR 各自重跑；**仓库层面这两处 pin 应当对齐**，
  否则任何人本地按 lock 格式化都会被打回。这一条已记入债务表，修法（改 lock 还是改 workflow）属属主。
* #314 随后又因为 #308 合入而 `dirty`，同样用 `merge origin/dev` + 8 个冲突取 ours 处理，
  重测 **CI 环境 7/1108**、96 tests、ruff 干净后推送，head `306a9259a4`，自审已重绑到该 sha。

#### 6. 本波没有改写的判定

AC12 仍不是"通过"：本波只证明"代码+迁移+重启"三件套能让服务按 dev 的代码跑起来，
并把时钟写入侧从"待部署"推进到"已部署并实测"；AC12 要的部署可复现性与"迁移随代码走"的机制
（比如启动时明确拒绝而非静默 exit、或把迁移纳入部署脚本）还没有落地，仍按 PARTIAL 记。
AC13 的"停用是否生效"要等今晚 22:00 UTC 的槽位；AC05/AC10/AC14 不因本波改变。

#### 7. 把"已部署"写成可复跑的四问四答，并如实承认当前落后一个文档提交

上文的部署结论现在有一个只读仪器兜底：`evidence/2026-11-07-wave30/deploy_state_verification.py`
（`git rev-parse` + `alembic heads/current` + 只读 SELECT），17:41:14Z 输出：

| 问题 | 读数 | 含义 |
|---|---|---|
| 运行的是哪个提交 | `eaf03cb56253`，分支 `dev` | — |
| 它就是分支尖吗 | **`deployed_head_is_branch_tip: false`**（dev 尖 `97fd87801e12`） | 部署后 #311 的文档提交又进了 dev，所以运行树比 dev 落后一个**纯文档**提交。写"部署的就是 dev"会不准确，故如实标 false |
| 迁移对齐了吗 | `heads=20261106_akshare_run_coordinator_claims`、`current=20261106_akshare_run_coordinator_claims` | 两侧同名，启动的硬门槛满足 |
| 工作树干净吗 | 唯一条目 `?? var/` | 只有已知的未跟踪运行产物，无源码改动 |
| 时钟写对了吗 | `active_tasks_with_clock_skew_over_60min: 0` | 近期跑过的 active 任务里没有超过 60 分钟的偏差 |
| 停用生效了吗 | `ghost_entrypoint_failures_since_window: 0`、`armed_tasks: 1048` | 观测窗内 0 次（定论仍等 22:00 UTC 槽位） |

仪器第一版有两个自己的缺陷，都已修：把 `alembic current` 的 `INFO` 行当成了 revision（因为
stderr 与 stdout 混在一起，取末行会取到它）；以及只报"脏条目数量"而不报内容、也不报
"运行提交 vs 分支尖"。这两个都属于"看起来在报事实、实际在报噪声"，和本波反复遇到的是同一类问题。

#### 8. `last_execution_at` 的语义是"最后一次**成功**"，不是"最后一次尝试"——并顺手抓到一个 1 秒的假阳性

§2 的迁移把 19 条并列成 `stale-column` 并注明"列未被维护、不是时钟偏移"。本波把这条查到底，
结论成立，但**数字和我第一版的判断都错了**，两处都被工具纠正：

* 全库"`last_execution_at` 早于该任务最新 `created_at`"的行是 **72 条**（不是 19；迁移之后又跑了十几个小时，
  且迁移只看 armed 任务、这里看全表）。
* 按"最新一次执行的 status"分类（全 72 行精确统计）：**71 条的最新执行是 `failed`**，**1 条是 `completed`**。
* 那唯一的 completed 例外是 id=387（`Auto: Fund Codes`，已停用，最后活动 2026-07-03）：
  `last_execution_at = 19:09:15`、`created_at = 19:09:16`、而同一次执行的 `end_time = 19:09:15`——
  **同一次运行里"记录创建时间"比"完成时间"晚 1 秒**，于是"最新执行时间 > last_execution_at"恒真。
  **这不是漏写，是我的比较口径把完成时刻和创建时刻混用了。** 判"落后"应与最新一次**成功**执行的
  `end_time` 比，或加秒级阈值。仪器里我把 ≤2 秒的落后一律标成 `artefact_within_one_second`，
  于是 id=953（最新一次是 failed、只比上次成功晚 1 秒）也被标上——那个标记的意思是"落后量微不足道"，
  不是"漏写"，两件事不能混。
* 代码侧对应：`execution.py:85` 只在 **`mark_completed`** 里写 `last_execution_at = end_time`；
  `mark_failed` 不写。`scheduler.py:183` 的写在 `run_script` 正常返回之后，失败路径走不到。
* **部署后实测（两类各一例，17:22Z 之后）**：`task 902` 17:40 completed → `last_exec=17:40`（同秒）；
  `task 386` 17:39 failed（`triggered_by=scheduler`）→ `last_exec` **仍是 `2026-10-31 17:39`**。
  新代码保持"只在成功时前进"。

结论与用法约束：
1. `last_execution_at` = **last success**。把它当"最后一次运行"或"调度器存活"的证据都是错的；
   尝试与存活只能读 `ak_task_executions`（本波 §3、§4 用的都是后者）。
2. §2 迁移里那 19 条不是时钟缺陷，是"自上次成功以来一直在失败"，迁移不动它们是对的。
   但**判"落后"的口径要修**：用 `created_at` 比会引入 1 秒假阳性（本例已证），
   应与最新成功执行的 `end_time` 比。
3. AC13/AC14 里"某任务多久没跑"不能拿这一列算：一个每周任务失败 10 次，这一列只显示 10 周前。
   #306 统一的是**时钟**，没有统一这一列的**语义**；语义现在被实测钉成"成功"。

#### 9. AC11 的签字件已经做好，只剩一个名字

`assigned` 仍是 **0/1057**，但"还差什么"现在具体到一个字段。用 §25 的 6 条非空源验证记录生成
`--review-file`：每个文件一行，`disposition` 取工具自己的提案（`REUSE_PROVIDER`）、
`file_sha256` 取工具当场重算的 sha、`decision=approve` 都填好，**只留 `reviewer` 与 `reviewed_at_utc` 空缺**。

* 产出在仓库外（按 §23 的规矩）：`~/afi204-evidence/2026-11-07-ac11-review/`
  —— `review-file.reuse-6.unsigned.json`、README（含一条可直接执行的属主命令）、以及空白名跑出来的台账。
* **签核门是活的**：拿这份空名文件回灌工具，6 条全部 `review_missing_reviewer_name`，
  没有一条被误接受。这一步的意义是排除"签字通路坏了"这一种解释——不是证明已分派。
* 签字后的预期是 `assigned 6/1057`，其余 1051 条不动；上限仍受 OD 侧 9 个函数名约束（最多 8）。
* 我没有替属主签名，也没有把这份文件放进仓库：它是签字件，不是账。

#### 10. AC11 的分子在 26 小时内从 168 翻到 312——同一条仪器、同一个 `--since`，只是采集真的在跑

用**已合入的** #309 仪器在 `.wt-afi-ac11ev` 上复读（16:48Z，`--since 2026-11-05T14:00:00+00:00`）：

| 口径 | 15:36Z（wave 29） | 17:48Z（本波） | 变化 |
|---|---|---|---|
| `AC11_RUNTIME_EVIDENCED` | 168 | **312** | +144 |
| `completed_and_grew` | 168 | 312 | — |
| `completed_no_delta` | 40 | 108 | 完成但目标表未增长 |
| `failed_only` | 13 | 20 | — |
| `not_run` | 827 | **608** | −219 |

四类仍满足 312+108+20+608 = **1048**，分母没变。这条读数本身不是新发现，它的意义在**方向与速率**：
采集恢复后 26 小时里，"有证据"的脚本从 16% 升到 **29.8%**，而未跑过的从 79% 降到 58%。
也就是说 AC11 的分子是**活的**，随时间单调上升；任何引用都必须带 as-of，否则两天后就是错的。

同时要压住一个误读：`completed_no_delta` 涨到 108 **不等于**这 108 个在空转。它只说明目标表行数没增加
（幂等、或该任务当期无新数据），是不是空转要看逐表对账——本波没有做，不写成结论。
另：`not_run 608` 是 AC05/AC14 现在最该盯的数——采集活着，但 1048 个 armed 里仍有 58% 一次没跑过。

#### 11. 一次差点记账的错：我在"另一个同名分支"上解完了 #303 的冲突

为了让 #303 能合，我在 `.wt-afi-paging` 里把 dev 合进去、解掉 7 个冲突、跑过测试（96 passed / 79 skipped、
0 markers），本地提交 `a59dca628`。然后两次以为"已推送"——两次都被外证否掉：

* 第一次 `git push origin HEAD` 报 **`* [new branch]`**，说明远端**没有**这个分支名。
* 第二次 API 查 `pulls/303` 的 `head.label` 是 **`cloudQuant:fix/afi-table-pagination-total-order`**，
  而我本地分支叫 `fix/afi-table-pagination-determinism`。
* 继续核对：本地 `HEAD^{tree}=8b51291731`，PR 头的 tree=`23859701c6`，**不是同一条线**；
  用正确分支名再推被 **non-fast-forward** 拒绝。

结论：**我的 worktree 是一条同名但不同的旧分支，7 个冲突是在它上面解的，对 #303 无效。**
我做错的两件事：(1) 建 worktree 时只看"分支在哪个目录"，没有核对 `head.ref` 与 `head.sha`；
(2) 推送后先看 git 的 stdout（"done"/"up-to-date"）就准备记账，而不是先查 API 的 PR head 是否变化。
第二件更严重——`git push` 的静默成功只说明"某个 ref 更新了"，不说明"PR 动了"。

处置：删掉我误建的远端分支 `fix/afi-table-pagination-determinism`（204，已删）；
#303 **保持 dirty**，未合、未推送、未重做。要修只能从 `origin/fix/afi-table-pagination-total-order`
重新解一次冲突。本波不再声称 #303 有任何进展。
另一个副作用要说明：#303 的冲突解里包含一份对 `tables.py`/`data.py` 的合并结果，
它在**那条旧分支**上通过了 96 个测试——那只能证明"那份合并没坏"，不能证明 #303 可用。

补一条 §11 的收尾：这条冲突**不是无解的**，而是卡在分支身份上，且我不替属主做破坏性动作。

* 子代理给出的解是完整的：7 个 hunk 逐一说明取舍（两侧都保留）、`WarehouseTablePage` 增加
  `adjustment_basis=None`、`resolve_total_count` 增加可选绑定参数、dev 的 4 元组契约被 page 对象取代后
  它把 dev 的 7 个服务测试改成属性访问（值不变）。验证：ruff 0.16.2 干净、`test_akshare_management_api.py`
  96 passed/79 skipped、`test_akshare_script_service.py` 101 passed、无冲突标记。**但它在
  `fix/afi-table-pagination-determinism` 上，而 #303 的头是 `fix/afi-table-pagination-total-order`。**
* 我尝试在正确分支上重做：从 `origin/fix/afi-table-pagination-total-order` 建 worktree、合 dev，
  得到的**仍是同两个文件、同样形状的 7 个 hunk**，说明两条分支承载同一补丁、只是基线不同；
  但这边的 `WarehouseTablePage` 还没有 `adjustment_basis` 字段，data.py 的 3 个 hunk 也要重新按
  "page 对象 + 调整基准"重建，并且要重写 dev 的 7 个服务测试——这不是合并，是一次等价重构。
* 两条干净的路，都需要属主点头，我都没有做：
  (a) **重指 PR**：把 `fix/afi-table-pagination-total-order` 强制更新为已验证的 `a59dca628`（force-push，
      改写 PR 分支历史）——破坏性，需明确授权；
  (b) **重做**：在 `...total-order` 上按上面同一套取舍重新解一遍并重写那 7 个测试，再推（无非快进问题）。
  我倾向 (b)，但它是**非本迭代验收项**的队列工作，本波先记为 OPEN，不占用优先项的时间。
* 教训已入账：worktree 的分支名与 `head.ref` 不一致，是这次两度误判的直接原因；
  `git push` 成功只证明某个 ref 动了，不证明 PR 动了——之后一切"已推送"都以 API 的 `head.sha` 为准。
