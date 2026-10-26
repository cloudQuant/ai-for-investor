# 第七批 管理员 reviewed-run 离线接线状态

记录日期：2026-10-27（Asia/Shanghai）。状态：**IN_PROGRESS；前端、账本/身份、reviewed runtime/API/app定向门禁、120文件Ruff/format、64生产文件mypy/Bandit、974文件范围named gates、74文件组合、质量锚点A2、861提交secret scan及两个公开JSON的独立secret scan均已通过；106文件Wave 7私有归档已生成，独立归档审查待完成。NOT_PRODUCTION_ACCEPTED。** 本状态仅记录局部离线验证。计划、所有权、共享契约及验收边界见 [WAVE7_PLAN.md](WAVE7_PLAN.md)；第五、六批的冻结收据保持独立。

## 已通过的定向验证

| 范围 | 精确锚点与结果 | 限制 |
| --- | --- | --- |
| OpenData管理员前端 | OpenData提交 `c52663b2ec6e0070fe404ef10edb5e93bb53288c`；6个显式Vitest文件，**29 passed，6.44秒** | 仅页面API/store/polling、管理员路由、router与layout导航的离线fixture；不证明后端服务或生产权限配置 |
| OpenData前端构建 | 同一前端提交执行官方`npm run build`，`vue-tsc`与Vite build **PASS** | Vite报告一个minified JS chunk超过600 kB，最大`index` chunk为1,287.10 kB；这是构建警告，不是构建失败，也未在本批扩展性能结论 |
| Run身份与账本 | OpenData提交 `ad76bc7fb3a5de068d2d338d18901993f6f75605`；9个显式测试文件，**248 passed，20.83秒**；`run_identity.py`覆盖96.1749%，`run_ledger.py`覆盖90.6667%，均达到各自90%门槛 | 只覆盖所列离线身份/ledger目标；不替代worker/生产DB部署或完整整合门禁 |
| reviewed runtime、管理员API与独立app | OpenData提交 `b4a1f630ad48781d21440724971562ec946374d3`；4个显式文件，**70 passed，10.56秒**，无skip/warning，raw与verification exit code均为0。覆盖率：runtime 96.1390%、API 85.3186%、app 96.2025%，达到各自门槛 | API仅比85%门槛高0.3186个百分点；结果限于隔离allowlist、显式环境变量与临时SQLite/合成worker fixture |
| OpenData静态检查 | `b4a1f630ad48781d21440724971562ec946374d3`：Ruff与format检查**120个Python文件通过**；production mypy **61个core+3个client文件通过**；Bandit **64个production文件通过**。Python 3.10语法检查通过 | 仅列明工具和文件范围；Python 3.10 runtime、A2及整仓`make gate`未因此通过 |
| named gates | 质量锚点 `f7aec5da6c30de03b48e88e7abbdcd748bde0934` 上 `make brand-check zero-dep-check public-api-quality published-openapi-check` **PASS**：974文件扫描无新增上游引用，2,495个public callables的docstring与annotation覆盖均100%，OpenAPI v1 140路径、v2 6路径兼容 | 仅四个named gates；不代表A2或完整`make gate`通过 |
| 跨流combined | 质量锚点 `f7aec5da6c30de03b48e88e7abbdcd748bde0934`；74个显式文件，**2,627 passed、26 deselected，142.09秒**，无报告warning | 25个既有e2e及1个既有cache integration node按原选择明确排除；使用空owned CWD、74个绝对测试路径及仓库`pytest.ini`；无coverage报告，不代表完整`make gate` |
| A2 | 质量锚点 `f7aec5da6c30de03b48e88e7abbdcd748bde0934`：**1,200个resolver文件、786个mypy roots全部exit 0** | 333个docs/evidence文件按既有策略排除；149,323条历史Ruff发现仍NOT GREEN，5,130项support和16项active evidence缺口仍OPEN |
| Secret scan | 固定版本Gitleaks 8.30.1扫描**861个提交，0泄漏**；后生成的两个公开JSON在owned copy目录由同一固定版本单独扫描，exit 0、0 findings | 两个JSON的独立扫描收据位于冻结归档之外；冻结归档创建后不回写 |
| 私有归档与公开证据 | `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave7`：**106 files，10,544,281 bytes**；目录0700、文件0600；公开验证JSON与归档JSON分别有独立SHA | 私有归档已冻结，独立归档审核尚未完成；当前只确认归档生成，不把它描述为审核通过 |

定向与74文件组合结果可以说明本次覆盖的离线接口与fixture检查通过，不能推出上游来源、数据权利、真实任务、生产DB、部署或自然周期已验收。前端和OpenData后端分别在各自隔离checkout执行；组合收据也不替代A2、secret scan、归档或完整`make gate`。

精确测试文件：前端为`src/__tests__/reviewed-runs/{api,store,view-polling,router-auth}.test.ts`、`src/__tests__/router/index.test.ts`及`src/__tests__/layout-navigation.test.ts`；ledger/identity为`tests/test_run_identity.py`、`tests/test_run_identity_ledger_integration.py`、`tests/test_run_ledger.py`、`tests/test_run_ledger_atomic.py`、`tests/test_run_ledger_database_clock.py`、`tests/test_reviewed_run_chain.py`、`tests/test_run_identity_credentials_ledger.py`、`tests/test_reviewed_cli.py`及`tests/test_run_ledger_boundaries.py`；runtime/API/app为`tests/test_reviewed_runtime.py`、`tests/test_reviewed_runtime_boundaries.py`、`tests/test_reviewed_runs_api.py`及`tests/test_reviewed_app.py`。每次执行的完整argv、环境、source hashes与coverage JSON由root本地receipt保留。

## 失败与修复历史保留

未达标的中间结果仍保留在root收据目录，最终通过结果没有覆盖或删除这些记录：

- 前端首次4文件运行 **14 passed、2 failed**；随后重跑为 **15 passed、1 failed**。其中create调用为0的失败来自测试fixture：detached wrapper上的原生`button.click()`没有提交其未挂载的表单，测试遂改为显式提交form，并保留button enabled/type断言。logout测试改为等待router `afterEach`完成后再断言到达`/login`。两次早期失败均保留；修正后6文件结果为当前29 passed。
- 管理API第一次宽范围命令报告 **47 passed、10 skipped、10 warnings**，总覆盖79.11%；这不是有效验收：`pytest-asyncio`已安装，但命令的`-c`误指向`pyproject.toml`，没有读取`pytest.ini`中的`asyncio_mode=auto`，10个未显式标记的async用例因此被skip。后续4文件执行有 **67 passed**，但API目标覆盖84.7645%，低于85%门槛，仍判FAIL。补充3个media-type/不读取请求body边界用例后，当前接受结果为70 passed，API覆盖85.3186%。
- ledger/runtime/app也保留早期失败、warning或覆盖不足结果；这些W7定向运行使用了显式环境变量allowlist与owned SQLite。历史问题包括CLI phase fixture不匹配、覆盖不足或pytest配置选择错误；一次ResourceWarning审计只定位到可能的test-owned cleanup候选，具体归因未证实。当前248项ledger/身份定向结果和70项operator定向结果分别以各自精确source SHA与coverage JSON为准；不得将早期85.83%或这些中间结果作为最终通过证据。

## 运行语义与隔离限制

本批新增OpenData侧独立reviewed runtime、JWT管理员API、`create_reviewed_app()`及OpenData管理前端。reviewed app只挂载认证和reviewed routes；旧`opendata.main`、legacy API routes和调度默认行为没有借此关闭或替换。Worker与`RunLedger`使用同一被注入metadata Engine对象；该identity约束只在受审查的显式组合路径中成立，不代表任意Engine或数据库访问受沙箱保护。

调用`RunLedger.cancel`后，活动run立即变为`CANCELLED`并fence旧worker token；最终状态为`CANCELLED`（包括重复取消）时返回`outcome=cancelled`，`SUCCEEDED`/`FAILED`终态返回`outcome=terminal`。`outcome`描述最终ledger状态，不表示这次请求刚刚完成状态转换；没有“已请求”中间状态。worker进程的物理停止仍为协作式行为，`close()`只停用新adapter，不会取消已经运行的job。旧token不得在取消fence后写入终态或事实数据。

Python导入链仍是重要边界：运行时可能eager-load pipeline/model/core settings并构造默认Engine；API package initializer可能加载legacy API router。显式调用reviewed app factory不等于无导入副作用，也不等于环境隔离。root测试需从无`.env`的cwd启动，并使用显式环境变量allowlist和临时owned SQLite；default-Engine guard不是通用网络、文件系统或任意DBAPI沙箱。当前验证没有真实source请求或生产数据库操作。

质量锚点 `f7aec5da6c30de03b48e88e7abbdcd748bde0934` 仅将zero-dependency census从643项更新为646项（vendor 325、client 3、合计974）；独立review收据为`wave7-zero-dep-census-review.txt`。该锚点相对operator静态检查提交`b4a1f630ad48781d21440724971562ec946374d3`无Python代码变化；scanner、93条source pins及12项AST例外未改。root确认operator/ledger定向测试涉及源码hash仍与对应通过收据匹配。Ruff/format/mypy/Bandit静态范围及A2均已通过；A2报告1,200个resolver文件、786个mypy roots全部exit 0，333个docs/evidence文件按既有规则排除。149,323条历史Ruff发现、5,130项support缺口及16项active-evidence缺失仍OPEN。

真实股票候选继续默认disabled且来源权利为UNKNOWN；UI不能运行该候选，coverage保持UNKNOWN。合成worker fixture不授予真实来源权限，也不证明Popen真实上游调用、完整历史或上市/日历边界。

## 第七批整体收口待办

下列root级收据**待完成**，不能用Wave 5/6结果或单流review代替：

- root对已生成106文件私有归档的独立审核；在审核结果返回前，不宣称归档审核通过；

完整`make gate`仍为**NOT_RUN**，不因局部root门禁通过而改变。Python 3.10 runtime未执行，作为保留的验证限制记录。两个公开JSON由OpenData本地提交`df8bf9b51ac634e2d55863127077ef37292ead4e`生成：`docs/afi204-wave7-validation.json` SHA-256 `017a69ea56a87c7ff3b09b472ba7464447683923707e8ea01e928f40d842f685`，`docs/afi204-wave7-archive.json` SHA-256 `6125ec2ae14432d8c3b22497edcf0b8f850817a8baea88fb4324d9285a3e096a`；独立secret scan通过，收据在私有归档之外。未收到独立归档审核结果前，不给第七批整体PASS、生产接受或任务关闭结论。

## 保留开放的迁移范围

本批不改变控制任务状态：87项仍为8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；204-E03-01仍为局部消费接线。1,103个旧任务、1,066个旧脚本候选、真实source权利与验证、逐instrument全历史head/interior/tail、所有AFI消费者、自然周期、外部备份恢复、生产角色与单写者cutover仍OPEN。父工作包验收必须按各自类型另取证据；代码提交和隔离测试不关闭真实源、部署或历史完整性要求。
