# 第十一批 Sina instrument/capture快照发布状态

日期：2026-10-27（Asia/Shanghai）。状态：**SCOPED_OFFLINE_CLOSED / NOT_PRODUCTION_ACCEPTED**。13文件核心回归、OpenAPI专项、scoped static、A2、full-history Gitleaks、私有归档、公开JSON复扫及独立归档审查均已通过。本页保留历史失败，不把代码review、环境审查或外部guard结果冒充当前核心回归，也不把离线收口表述为生产接受。

实施计划与冻结合同见[WAVE11_PLAN.md](WAVE11_PLAN.md)。W10保持CLOSED；父级87项矩阵保持8 `DEV_DONE`、9 `IN_PROGRESS`、70 `PLANNED`。本批不改变分母或生产授权状态。

## 当前source与实施状态

W11 OpenData回归和归档runtime anchor均为`fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`。早期集成锚点`edfe1557adb0607945baab9678561fa3c82e7a69`中的七个production modules及新增测试经独立review后，root继续完成shared/helper、migration、producer、client与bridge修正和复核。最终13文件核心组合在该source通过；此前v2/v3失败仍作为历史证据保留，不覆盖或删除。后续AFI W12集成位于独立工作流，不代表W11在新AFI HEAD上重新运行。

首轮失败的修正已在最终source复验：四个migration fixture按pre-0012数据库形状准备；client `page_size` fixture对齐接口；producer wrong-query用例遵循响应未回显identity时的真实边界；bridge用例按实际token契约修正。canonicalizer此前已用JSON-mode dump；本次修正在该canonical boundary和selector helper的dump调用上设置`warnings="error"`，并将`PydanticSerializationError`转为固定安全错误，使未信任的畸形model-copy在warning内容输出前fail closed。没有过滤或忽略warnings；有效模型的canonical bytes未改变。最终核心运行0 warnings，首轮失败事实和修正链仍保留在下方历史表中。

## 执行证据

| 收据/锚点 | 结果 | 范围与说明 |
| --- | --- | --- |
| `wave11-core-first-root-command.json` · source `edfe1557adb0607945baab9678561fa3c82e7a69` | **FAIL — collection** | 首轮v2因测试环境缺少`email-validator`出现3个collection errors、1项deselected，8.87秒；没有测试body执行，也没有coverage结果。完整失败收据保留。 |
| v3 focused environment及`wave11-focused-env-v3-result-independent-audit.txt` | **PASS — environment only** | Python 3.13.5新建隔离venv，53个精确依赖pin、pip 25.1.1 bootstrap、`pip check`通过、无system site packages/上游SDK；安装与环境元数据经独立审计。此项不证明应用import或测试通过。 |
| `wave11-guard-probe-v3-root-command.json` | **PASS — guard only** | 独立DB guard probe为9 passed、0.10秒，无应用import；不计入W11核心测试通过数。 |
| `wave11-od-static-final-20261027-b-command.json` · source `e8b485284ccd2d6af992c832cdae1e11290ba620` | **PASS — stale after later edits** | 14个目标文件、8项scoped static checks通过。后续改动已进入`168fa430...`，须在当前source复跑。 |
| `wave11-a2-first-root-command.json` · source `e8b485284ccd2d6af992c832cdae1e11290ba620` | **PASS — stale after later edits** | Whole-resolver A2组件通过，1,222个complete-resolver文件。当前source变更后须重跑；这不是`make gate`。 |
| `wave11-core-v3-first-root-command.json` · source `e8b485284ccd2d6af992c832cdae1e11290ba620` | **FAIL — first actual 12-file run** | 332 passed、7 failed、1 deselected、6 warnings，165.35秒。`tests/test_snapshot_client.py::test_real_fastapi_sqlite_delta_snapshots_preserve_origin_publications`沿用既有unclosed-Engine隔离规则显式deselect。其余核心组合失败原因见下表。 |
| `wave11-core-second-root-command.json` · source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e` · receipt SHA-256 `9d76758e7072fcc7716fa2699c662d71e9a8015fdd810980a7883e2fe990da7f` | **PASS — 13-file core** | 469 passed、1 deselected、0 warnings，238.35秒；同source pins核验未变，八个production targets的statement+branch coverage全部达到各自floor。单个既有SQLite/Engine用例按既定隔离规则显式deselect；未降低阈值或增加排除。 |
| `wave11-openapi-gate-first-root-command.json` · source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e` | **PASS — focused OpenAPI** | 精确1文件24 passed、6.89秒；OpenAPI checker coverage 95.46925566343042%。v1 baseline SHA `2b738…`保持不变，reviewed v2 baseline SHA-256 `b5ef23a6d2c0910a900d886832ee2650d1cbbd3baf98816551eb07a655e612aa`。 |
| `wave11-od-static-final-20261027-c-command.json` · source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e` | **PASS — scoped static** | 9个production targets和7个新增测试文件、共16个文件的8项组件均通过；zero-dependency census为983个文件（655 runtime、325 vendor、3 client），2,507个public callables。此项不等同whole-resolver A2或`make gate`。 |
| `wave11-a2-final-root-command.json` · source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e` | **PASS — A2 component** | 1,222 complete-resolver files、796 unique mypy roots全部exit 0。既有archived-corpus policy下的149,323条历史Ruff findings、5,055个blocked archived candidates与19项manifest errors继续OPEN；不据此声称整仓`make gate`通过，也未改变排除政策。 |
| `wave11-secret-final-root-command.json` · source `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e` | **PASS — full-history component** | Gitleaks扫描976个commits，0 leaks；这是secret component结果，不等同`make gate`。 |
| W11私有归档 | **PASS — frozen and independently audited** | `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave11`：182 files、6,554,821 bytes、3 HTML ZIPs；目录0700、文件0600。归档runtime anchor为`fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`。归档含首轮失败core coverage HTML与归档预检失败记录。 |
| Public validation/archive JSON | **CREATED** | `docs/afi204-wave11-validation.json` SHA-256 `c24197c51ce619f6c85759647ff5a823bf4a179b40d9df55236fb7145581a4d5`；`docs/afi204-wave11-archive.json` SHA-256 `b7bf32064a3ffeee18a73c5effa518fb1d7030e43aa54aae9d4145970348f461`。OpenData metadata-only commit `aee076c83c1067a35da009fa2e8c061445401f72` contains these two public JSON files only; it is distinct from runtime/test anchor `fbec7066f9ea58e2e4dcdcf445a4af46b37a8b1e`。 |
| `wave11-public-docs-secret-scan-command.json` | **PASS — generated public documents** | Gitleaks 8.30.1在两个公开JSON的owned copies上exit 0、0 findings；归档文件未被更改。 |
| `wave11-archive-independent-audit.txt` / `.json` | **PASS — independent archive audit** | TXT SHA-256 `8744822541db4b36d42f67b8378bcd23bdc3fc951878b5e524e6e423adfded1b`；JSON SHA-256 `591d88e4fd6828eba734770ab26715e1c8ce8993050fd6f7798b80a59d3428bb`。核验182/182文件、6,554,821 bytes、3个ZIP CRC与索引路径安全；前序W7/W8/W9/W10共397个文件未变；当前fbec source的5/5运行receipt pins与归档字节一致。 |

归档前有一次预检因错误predicate失败，未产生归档输出、源码改动或测试运行；修正后finalizer通过，失败收据仍保留。这是归档预检记录，不是代码或测试失败。

### v3首轮失败和覆盖（历史）

| 失败/缺口 | 数量 | 事实与处理边界 |
| --- | ---: | --- |
| migration fixture | 4 | fixture按pre-0012状态构造，却在upgrade前尝试写新selector列；root修复fixture，13文件最终回归通过且migration覆盖达到100%。 |
| client分页fixture | 1 | `page_size` fixture与接口契约不匹配；root已对齐fixture，最终核心回归通过。 |
| producer wrong-query oracle | 1 | 用例假定响应未回显identity时仍能由body判断错误query；该假设不成立；root修正预期，最终核心回归通过。 |
| producer-to-REST bridge | 1 | 首轮用例关于raw manual token重建/保留的假设与真实契约不符；后续修正经独立review，并由最终核心回归通过。 |
| Pydantic serializer warnings | 6 | 畸形model-copy触发serializer warning。canonicalizer原已使用JSON-mode dump；修正是在canonicalizer和selector helper的dump调用上设置`warnings="error"`，并安全捕获serialization error。有效模型canonical bytes不变，没有过滤warning；最终核心运行0 warnings。 |

v3运行记录七个production目标的statement+branch coverage：

| 模块 | 覆盖率 | 本轮结论 |
| --- | ---: | --- |
| `capture_selection.py` | 100.0000% | 达到模块门槛 |
| `publication_store.py` | 94.1392% | 达到模块门槛 |
| `contract_publication.py` | 99.5327% | 达到模块门槛 |
| `published_data.py` | 89.6552% | 达到模块门槛 |
| `snapshots.py` | 89.9645% | 达到模块门槛 |
| `financial_statement_publication.py` | 77.9412% | **低于模块门槛** |
| `20261027-0012_instrument_capture_scope.py` | 54.3860% | **低于模块门槛** |

aggregate覆盖率89.8577%达到总覆盖要求，但producer与migration两项模块覆盖未达到各自floor，故该receipt为FAIL；不以总数掩盖模块缺口。coverage JSON未降低阈值或增加排除。后续复跑覆盖如下：

| 模块 | 最终statement+branch coverage | 结果 |
| --- | ---: | --- |
| `capture_selection.py` | 100.0000% | 达标 |
| `platform_contracts.py` | 93.0612% | 达标 |
| `publication_store.py` | 94.1392% | 达标 |
| `contract_publication.py` | 99.5327% | 达标 |
| `published_data.py` | 89.6552% | 达标 |
| `snapshots.py` | 90.0533% | 达标 |
| `financial_statement_publication.py` | 90.8088% | 达标 |
| `20261027-0012_instrument_capture_scope.py` | 100.0000% | 达标 |

## 最终收口仍待完成

- 生产source rights、retention、实际cohort、完整财报历史/coverage、金融单位、revision/PIT和source identity继续OPEN。Python 3.10 runtime、完整`make gate`、remote CI和production acceptance均未完成。
- W10保持CLOSED；父级87项矩阵仍为8 `DEV_DONE`、9 `IN_PROGRESS`、70 `PLANNED`。1,103个旧任务、1,066个脚本候选、全历史、自然周期、备份恢复及单写者切换不因本批scoped结果改变。
- W12当前处于并行实现与集成阶段，执行验证尚待完成；本页不把W12 worktree或代码集成写作通过证据。
