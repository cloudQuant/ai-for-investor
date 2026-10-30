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
