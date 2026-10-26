# 第九批 Sina 资产负债表原始wire切片状态

日期：2026-10-27（Asia/Shanghai）。状态：**CONTRACT_FROZEN / SCOPED_OFFLINE_COMPLETE / NOT_PRODUCTION_ACCEPTED**。最终root两文件隔离测试85 passed，三个新增data modules的statement+branch coverage均达到90%门槛；同一source revision上的scoped static、A2与full-history secret组件也PASS。首轮失败保留；私有archive及独立审查均完成。Full `make`与remote CI未运行。本状态只表示W9 scoped offline gates通过，不表示整仓或生产验收。

计划与上一批基线：[WAVE9_PLAN.md](./WAVE9_PLAN.md)、[WAVE8_STATUS.md](./WAVE8_STATUS.md)。W8已完成其scoped offline验收及独立archive audit，但仍为NOT_PRODUCTION_ACCEPTED；W8证据不作为W9测试或来源权利证据。

## 范围与冻结合同

本批只交付未注册、source-native的Sina `fzb`解析与有界抓取seam。正向fixture是一份录制的上海`sh600519`响应，含103期；它不证明其他股票/市场覆盖、来源保留期限、来源权利、单位、revision或完整历史。报告值保留原始字符串，发布日期、源更新epoch及抓取时间彼此独立；空项目分组为结构标记，不是财务数据。

冻结wire contract：`wave9-frozen-sina-wire-contract.txt`，SHA-256 `e6da15d2ffc7edd61f2b0fbca89074f17122ab79cdbf59f30928d60c9a519859`，最终独立contract review为GREEN。取消语义修订：`wave9-frozen-cancellation-amendment.txt`，SHA-256 `a9042637b648facc50a5a04dc0260c3eebce965a3cb820be272cbb73b97aedd2`；独立review为GREEN。修订要求把`RequestExecutionCancelledError`映射为独立安全码`cancelled`，与`deadline_exceeded`分开；调用前、收到响应后及parse完成后检查取消/期限状态。取消是协作式的，不保证中断阻塞socket或同步parse。

保持以下限制：不注册Sina provider/capability，不添加生产`ALLOWED` grant，不产生`FinancialStatement`、浮点金额、revision、coverage、`verified`声明、DWD/PIT或route；不激活任务748。来源权利、单位/scale、历史revision、保留期限、全标的历史与任务启用仍OPEN。

## 当前集成位置与审查

当前root focused-test与final-static共同source revision为OpenData `9ff72ad668ce161f5132bf866b251acd3c80bbba`；四个隔离工作流从`ec831160dbf4bbe5b2b766e6d6f8d7e31db0922f`分支。root负责质量census、集成及精确测试选择。下列reviews分别固定在各自提交；root focused run和final static的生产/测试文件pins与同一`9ff72ad`一致，但不代表整仓combined suite或production acceptance。

| 部件 | 证据与状态 |
| --- | --- |
| 冻结合同 | 最终contract review `wave9-sina-wire-contract-review-final.txt`：GREEN；初始提案中的早期HOLD仍保留，不是最终处置。 |
| 合同模块 | commit `4d9e01513f8981d73176eefe4c2f9451ed0475e0`；`wave9-sina-contract-implementation-review.txt`：合同实现review GREEN。仅含source package与合同DTO/常量/错误。 |
| 纯parser | 初始实现review `wave9-sina-parser-review.txt` GREEN；重复group marker修正commit `012c0f496637dcbf9a3cc520cce22eba564e29d8`经`wave9-sina-parser-review-v2.txt` GREEN。修复exact duplicate marker合并后返回正常，使调用方不再误判为`invalid_value`；冲突marker仍fail closed。最终测试source parser hash为`c011f58b4a0c10b24304128690c4c0e333279c9d44b85dad029360f555ca8dc6`。 |
| bounded wire seam | commit `d5aa5d880c0a8ac2f81d59d59fc7a0f37b6b344e`；`wave9-sina-wire-review.txt`：wire review GREEN。审查覆盖注入client、精确Sina scope、deadline/cancellation传递、安全错误及bounded request。 |
| 两个测试文件 | `wave9-sina-test-isolation-review-v2.txt`：固定两文件选择的隔离review GREEN；stream-close assertions改为检查底层`BytesIO.closed`，避免使用测试包装器的非代表性close flag。review本身没有执行测试。 |
| Focused测试环境 | `wave9-focused-environment-review.txt`：GREEN。独立Python 3.13.5 venv，`include-system-site-packages=false`；17个精确固定依赖加bootstrap pip，pip check通过且无AkShare/OpenBB SDK。该结论仅覆盖focused环境，不是完整项目依赖或CI。 |

## 验证收据

| 验证 | 当前结果 | 范围与限制 |
| --- | --- | --- |
| OpenData final scoped static | **PASS** | `wave9-od-static-final-command.json`，source commit `9ff72ad668ce161f5132bf866b251acd3c80bbba`。Ruff、format、mypy、Bandit、zero-dep self-test/check、public API及brand均exit 0；quality census记录979 runtime files、2,499 public callables覆盖率100%。 |
| Python 3.10语法 | **PASS** | final static receipt记录grammar PASS；仅语法检查。 |
| Parser与wire精确测试（最终） | **PASS** | `wave9-sina-focused-root-command.json`：85 passed，159.20秒；仅两个指定文件、`--noconftest`，source commit `9ff72ad668ce161f5132bf866b251acd3c80bbba`。此项是focused fixture/fake-transport验证。 |
| Statement/branch coverage（最终focused run） | **PASS** | 同一receipt：contract 95.97315436241611%、parser 93.34719334719335%、wire 90.80459770114942%，均达到90%门槛；总coverage 93.584379%。阈值和exclusions未降低或增加。 |
| Parser与wire精确测试（首轮，保留） | **FAILED — FIRST RUN** | `wave9-sina-first-root-command.json`：76 passed、3 failed，68.09秒；source commit `5822b74bfd6516371cd7a2b8a0b9c7715be989f3`。首轮失败保留，不改写为通过。 |
| 首轮失败修复记录 | **修正后复测PASS** | 首轮一个parser failure源于exact duplicate group marker有效合并后返回`None`、被调用方误判为无效；窄修复经parser review v2 GREEN，最终focused run通过。另两项是stream-close测试instrumentation断言问题；测试review v2改为检查实际底层stream closed状态，最终focused run通过。 |
| 首轮statement/branch coverage（历史失败） | **FAILED — FIRST RUN** | 首轮parser 88.8889%低于90%；contract 95.97315436241611%、wire 90.80459770114942%达到门槛。最终coverage数字见上行；保留原失败收据。 |
| Focused测试环境 | **PASS** | `wave9-focused-environment-review.txt`审查通过；最终测试在Python 3.13.5独立venv（无system site packages）运行，17个精确pin依赖加bootstrap pip，`pip check`通过，无SDK。首轮测试环境不同且可见system site packages，不作为最终通过环境依据。 |
| Focused source-pin alignment | **PASS — SCOPED** | 最终focused test与final static receipts均pin到`9ff72ad668ce161f5132bf866b251acd3c80bbba`，涉及生产模块、两测试文件及fixture的SHA一致。分项reviews仍按各自commit记录；不构成full project combined suite。 |
| Full-history secret scan | **PASS — COMPONENT ONLY** | `wave9-final-secret-command.json`：Gitleaks 8.30.1扫描894 commits，0 leaks。此为既有secret-check组件，不代表full `make` gate；后续新public evidence需按需独立扫描。 |
| A2 whole static | **PASS — COMPONENT** | `wave9-final-a2-command.json` / `wave9-final-a2-summary.json`：source `9ff72ad668ce161f5132bf866b251acd3c80bbba`，1,209 complete resolver files，791 mypy roots全部exit 0。333个docs/evidence Python文件仍按原有archived-corpus policy排除；本次无scope或exclusion policy变化。此组件PASS不代表full `make` gate。 |
| 继承的历史证据与归档语料缺口 | **OPEN — POLICY UNCHANGED** | 149,323条历史Ruff findings仍NOT GREEN；5,055个blocked archived candidates、19项manifest errors及missing active-evidence/support gaps继续OPEN，按既有archived-corpus policy处理，不作为W9 focused code通过的证据。 |
| 私有归档 | **CREATED / FROZEN** | `/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave9`：80 files，2,064,005 bytes；目录0700、文件0600。 |
| 公开验证与archive JSON | **CREATED** | OpenData metadata commit `fbb57d546cf149bb8990dcf2088c6b4d1ec2bcaf`；`docs/afi204-wave9-validation.json` SHA-256 `df9c87a2f5b0ae46bab0cbb18d517f03872a3972c01a00bdd248961e9ca3ea1d`；`docs/afi204-wave9-archive.json` SHA-256 `90687816ae88eee3b41a202c6b285eea3f12675102da333a4202d4ec75e87c2c`。 |
| 新公开JSON secret scan | **PASS** | 两个Wave9 public JSON在归档之外由固定Gitleaks runner二次扫描，0 findings；JSON bytes未改变，扫描不会回写冻结archive。 |
| 独立archive review | **PASS** | `wave9-archive-independent-audit-v2.json`：24/24 checks；80/80文件、2个ZIP CRC/path checks、2,064,005 bytes均核对通过，W7/W8归档不变。receipt SHA-256 `4e73a64c412349e0931321079935c98aa0e638e97a684d7bac6653c77211be5a`。 |
| Full `make` gate | **NOT_RUN** | 不是本批已执行项。 |
| Remote CI | **NOT_RUN** | 无remote CI结果。 |
| Python 3.10 runtime | **NOT_RUN** | grammar PASS不代表3.10解释器运行。 |
| 生产权利、授权与启用 | **OPEN / NOT_APPROVED** | 无来源许可、生产grant、注册、下游映射或任务748启用批准。 |

首轮测试在混合环境中运行，虽然相关依赖floor满足，但system-site packages可见；该次失败记录不作为最终环境验证。最终85项测试改在独立Python 3.13.5 venv运行，禁用system site packages、使用17个精确pin依赖与环境白名单，禁用plugin autoload，空owned CWD及`--noconftest`，只传入两个绝对测试路径。隔离review确认其没有导入应用启动、连接数据库或访问live Sina网络。Python 3.10 runtime、full project extras与系统级隔离未由该focused运行证明。

## 父迭代范围

本批不改变87项父矩阵，也不改变1,103项任务和1,066个脚本候选的分母或状态。W9 focused测试虽已通过，但只证明这份记录响应上的离线合同与fake transport行为；来源权利、财报单位/科目映射、真实source覆盖、全历史头/内/尾、自然周期、生产注册和任务748仍须单独取证与批准。Wave9归档审计通过只核验离线证据包，不构成来源或生产接受；A2 component PASS不替代full `make` gate。
