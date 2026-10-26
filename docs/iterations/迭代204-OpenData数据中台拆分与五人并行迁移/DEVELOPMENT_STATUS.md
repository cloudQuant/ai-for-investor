# 子代理开发与集成记录

## 当前集成状态

两仓使用下表的隔离集成分支，未push、未合入dev、未部署。第二批11条分支完成契约、账本、持久发布与快照、授权、v2 REST/SDK和AFI输入边界；其1,120项组合、AFI157项、独立MySQL7项和SDK安装5项结果见 [WAVE2_STATUS.md](WAVE2_STATUS.md)。这些是第二批的历史收据，不冒充第三批重跑。

第三批按6个控制任务拆成7条执行任务，已集成子进程执行、raw证据、主机清单、统一提交、迁移dry-run、OpenAPI门禁及股票wire身份校验。分支、审查修复、组合回归及限制见 [WAVE3_STATUS.md](WAVE3_STATUS.md)。35个工作包细分为87个控制任务，各域适配仍继续按不超过20个源条目的批次拆分；本批局部能力不会自动关闭完整任务。

真实只读库确认1,103个任务、1,066条脚本注册和1,042张旧仓库表。主机报告保留权限/截断与writer身份未知，迁移预演保留1,103个BLOCKED、0个ready。完整gate、真实源、全历史迁移、生产worker、自然周期和恢复切换仍未验收。

## 首批历史

日期：2026-10-26（Asia/Shanghai）。执行方式：主代理拆分、分派、审查与集成；6个开发子代理分别在独立worktree/branch提交，另安排独立代码审查。现有35个工作包已细分为87个子任务，本批完成6项代码与离线验证，81项仍待推进。完整迁移尚未完成。

## 隔离基线与交付分支

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

## 第十批 Sina 七项候选投影（进行中）

W10冻结合同SHA-256为`2ec501ad7d20e9802a4dc1aef3911ec7e6a9b0d8f5af231072e780fdf75b9c9a`。合同DTO（commit `954e79c9`）和projector（commit `d0abab97`）均静态review GREEN并集成到root OpenData source `fd151a46c44fe044f00b3386a6e032a3bc52252a`。唯一隔离测试文件（author commit `be057bb0`）已准备，独立隔离review pending；root尚未运行W10测试，没有test或coverage通过结论。投影只按七组精确source ID/title输出namespaced候选，始终`partial`并保留原始值/state/metadata/时间/ordinal；不得据此推导会计单位、修订、PIT、source rights或生产资格。

该批不注册Sina provider、不创建生产grant、不持久化候选、不修改`FinancialStatement`/DWD/PIT或启用任务748。父级87项矩阵仍为8 DEV_DONE、9 IN_PROGRESS、70 PLANNED；1,103项旧任务、1,066个脚本候选、完整历史、自然周期与切换继续OPEN。工作包、依赖和验收顺序见 [WAVE10_PLAN.md](WAVE10_PLAN.md)。
