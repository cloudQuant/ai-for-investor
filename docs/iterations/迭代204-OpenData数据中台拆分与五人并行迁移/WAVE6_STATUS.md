# 第六批 HTTP 边界与进程隔离切片

记录日期：2026-10-27（Asia/Shanghai）。状态：**HTTP/request-budget、股票进程三文件和69文件显式组合测试均已在各自隔离边界内通过；Ruff、format、production mypy、Bandit、named gates、A2、821提交历史secret-check及两个新公开JSON的独立secret scan均通过；135文件私有Wave 6归档已冻结。结果限定为局部代码与隔离验证，整仓`make gate` NOT_RUN，NOT_PRODUCTION_ACCEPTED。** 第五批冻结收据保持不变，见 [WAVE5_STATUS.md](WAVE5_STATUS.md)。

## 已取得的局部结果

| 范围 | 收据 | 限制 |
| --- | --- | --- |
| HTTP客户端与request budget | OpenData提交 `0efe35f8b155461c401b06379f304b040340b322` 上执行11个显式测试文件：**288 passed、1 deselected，3.98秒**。覆盖率JSON显示 `http_client.py` 为90.1980%，`request_budget.py` 为98.4375%，合计92.9698%（1,100 statements；7条既有排除：HTTP 2条、budget 5条），满足原90%门槛 | 仅该HTTP/budget目标及列出的离线测试；1项integration被显式deselect。transport fixture/默认Engine guard不等于通用网络、数据库或文件系统沙箱，也不证明真实上游可用 |
| Worker资源清理 | 专用测试命令 **21 passed、16.74秒**；将`ResourceWarning`与`PytestUnraisableExceptionWarning`提升为错误，未报告warning | 仅覆盖测试自有资源清理路径；没有验证或新增生产worker shutdown API |
| 股票日线进程切片 | 生产实现review快照 `451458da2076bb27623f1621ecdcdd3b9d5880f9` 在P1/P2范围内STATIC GREEN；root合入 `a5078a90`、`285a1fad`、`81549aea`。测试fixture修正`5b8de0f2`经review后合入`bf4359d8b0f5c255fa76c59140217a86db4a9a1f` | 首轮root三文件命令161 passed、1 failed、7.54秒，覆盖率90.92%；失败来自正向fixture在固定合同guard之前替换`executor.run`，不作为最终通过结果。修正后三文件命令**168 passed、7.55秒**；wire覆盖91.3978%、job覆盖92.4786%、合计92.2179%，两个目标模块均达到90%门槛。保持默认disabled、未生产注册、权限UNKNOWN；不证明真实source rights、HTTP响应、stock Popen成功或历史完整性 |
| Wave 6显式组合 | root在`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`运行69个显式测试文件：**2,529 passed、26 deselected、112.02秒，无报告warning** | 只代表选定组合；其中1个cache integration node明确deselect，另25项是原有e2e排除。不能替代完整`make gate`、真实source/rights或生产验收 |

## 最终静态/A2与剩余证据

质量锚点为`2464dd13839acc00f4102d551601af2de8d72a60`。完整A2命令为**PASS**：1,192个resolver文件；783个mypy root均exit 0。333个`docs/evidence` Python文件依既有策略排除静态工具，未修改范围或排除。该A2结果只确认既定静态工具范围；149,323条历史Ruff发现仍为NOT GREEN，5,130项support缺口与16项active-evidence缺失继续OPEN，不因本次A2通过而关闭。

在同一锚点，Ruff与format覆盖112个Python文件通过；production mypy覆盖58个core及3个client文件通过，Bandit覆盖61个生产文件通过；named gates通过。3.10 AST语法检查通过，但没有Python 3.10 runtime矩阵。69文件测试锚点`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`与质量锚点之间，112个Python文件字节完全一致，仅HTTP精确source SHA manifest的一个字段变化。

## 归档与公开manifest

Wave 6私有归档已冻结于`/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave6`，**135个文件、18,198,311 bytes**，目录权限0700、文件0600。OpenData公开文档已生成：`/home/yun/Documents/opendata-od204/docs/afi204-wave6-validation.json`（SHA-256 `33691a1e07bb28dc636e037225afe78127b94c0ece096403f8ae1dcd38066697`）与`/home/yun/Documents/opendata-od204/docs/afi204-wave6-archive.json`（SHA-256 `cba8fdab160904e68d182821d31dd06a195cd28d248b788026b116f4d87f3996`）。

此前`make secret-check`使用Gitleaks 8.30.1扫描821个提交并通过，0泄漏；配置、manifest与scanner未改。该历史扫描早于两个Wave 6公开JSON生成，因此不覆盖这两个新文件。root随后对上述两个精确JSON文件单独执行固定版本Gitleaks directory scan，exit 0、findings 0。对应收据`/tmp/od204-receipts/wave6-public-docs-secret-scan-command.json`在私有归档冻结后生成，保存在归档之外。两次扫描覆盖范围分别为历史821提交及这两个新文件；均不覆盖未来新增或修改的内容。

## 静态门禁、质量锚点与历史扫描

Wave 6质量锚点为OpenData提交`2464dd13839acc00f4102d551601af2de8d72a60`。在`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`的69文件组合后，112个Python文件均与测试执行快照逐字节一致；随后只改变了HTTP精确source-SHA pin的一个字段。静态结果：Ruff与format覆盖112个Python文件通过；production mypy检查58个core与3个client文件通过；Bandit检查61个文件通过。三个source文件共93条精确SHA记录、12项AST例外保持不变；修正最初漏更新的HTTP pin后，named gates在该质量锚点通过。

同一质量锚点的`make secret-check`组件通过：Gitleaks 8.30.1扫描821个提交，0泄漏；未修改配置、manifest或scanner。Wave 6公开JSON是在该历史扫描之后生成，不属于821提交扫描输入；root之后对两个精确JSON单独执行固定版本Gitleaks directory scan，exit 0、findings 0。扫描收据在私有归档冻结后生成，位于归档外。先前因旧HTTP SHA pin导致的named-gate失败保存在15文件的初始失败收据中；最终pin修复只更新证据引用，不改Python代码、质量范围或AST例外。

HTTP最终命令覆盖11个明确文件：`test_http_client_streaming.py`、`test_http_client.py`、`test_fetcher_request_budget.py`、`test_request_budget.py`、`test_request_budget_profiles.py`、`test_provider_request_budget_errors.py`、`test_raw_response_cache.py`、`test_governed_http_post_json.py`、`test_macro_http_governance.py`、`test_http_client_boundaries.py`与`test_request_budget_boundaries.py`。命令以`-m not integration`运行，覆盖目标只有`opendata/data/http_client.py`与`opendata/data/request_budget.py`。Python运行时为3.13.5。

HTTP实现收敛在提交`7ee1ef25`、`d251ecd3`和`d51b645d`；测试fixture隔离修正为`1810af29`，边界测试迭代提交为`e0f98728`、`3738ee37`、`90241c8b`、`77a10c05`与`0efe35f8`。worker teardown改动`e4f46231`仅为测试文件。股票进程切片根合入`a5078a90`、`285a1fad`、`81549aea`；其测试专用修正`5b8de0f2`由root合入`bf4359d8`。合入时两条source SHA repin对应93条记录、12项AST例外，均未改变。上述短SHA用于定位局部工作；最终HTTP测试收据仍以完整source SHA `0efe35f8b155461c401b06379f304b040340b322`为准，局部提交清单不构成Wave 6整批集成验收。

## 修正历史与测试边界

最终HTTP组合前保留了几次未达标的中间结果：初始选择的边界组合为17 failed、86 passed、78.12%覆盖率；后续依次为103 passed/78.98%、217 passed/85.74%、286 passed/92.71%。其中286项虽然总覆盖已达标，HTTP模块为89.80%，仍低于该模块90%门槛；新增URL诊断脱敏用例后才得到当前288 passed、HTTP模块90.1980%的最终结果。没有降低阈值或增加覆盖排除。测试fixture修正针对transport/EOF建模与duck-compatible response边界，不改变生产合同或削弱权限/隔离检查。

股票slice首轮root三文件测试结果为161 passed、1 failed、7.54秒、报告覆盖率90.92%。失败是正向测试fixture在新的精确`ProcessFetchHandler`合同校验之前替换了`executor.run`；因此该结果不通过验收。随后只修改测试：正向fixture通过synthetic envelope decoder走父端normalization，不再调用`job.fetch`或伪称验证Popen/upstream；另加畸形HTTP响应、非法日历日期与实例级run override拒绝案例。修复提交`5b8de0f2`经review为GREEN并由root合入`bf4359d8b0f5c255fa76c59140217a86db4a9a1f`。修复后三文件测试168 passed、覆盖率wire 91.3978%、job 92.4786%、合计92.2179%。root对69个显式文件组合取得2,529 passed、26 deselected，无报告warning；这不是整仓gate。两条source SHA repin仍为93条source记录、12项AST例外，未借此改动范围或基线。

worker teardown专用测试使用其明确限定的测试资源；21项通过不覆盖生产worker生命周期。股票slice的修复审查检查固定`ProcessFetchHandler`、builder/decoder/timeout及executor合同、IPC容量和UNKNOWN子进程授权；合成正向fixture只证明适配器/capture/normalization接线，修正后三文件root测试168项通过。评审allowlist不包含会创建SQLite并运行Popen的纵向集成测试；本次不验证stock Popen或真实上游。作者自报的Ruff/mypy/Bandit/format未经stock切片reviewer重跑，root另以112文件静态门禁完成验证。

HTTP与worker命令的详细隔离环境、文件hash、coverage报告及stock review留在root本地收据。69文件组合、修复后三文件股票切片、Ruff、format、production mypy、Bandit、named gates、1,192文件/783 roots的A2、821提交secret-check及两个新JSON的单独secret scan均有通过收据。Wave 6私有归档135文件/18,198,311 bytes已冻结。**当前不得引用第五批A2作为Wave 6证据。** 完整`make gate`仍NOT_RUN。

## 保留开放的迁移范围

Wave 6不改变87个控制任务的全局状态：8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；204-E03-01仍为局部完成。1,103个旧任务、全历史head/interior/tail、真实来源与许可、生产角色/CLI/UI、全部AFI消费者、自然周期、外部备份恢复和单写者切换继续开放。此前越界目录级测试审计中，外部数据库和文件副作用影响仍为未知；该状态不因后续隔离测试而改变。第五批归档仍为121个文件、12,400,793 bytes，保持独立冻结，不并入Wave 6归档。
