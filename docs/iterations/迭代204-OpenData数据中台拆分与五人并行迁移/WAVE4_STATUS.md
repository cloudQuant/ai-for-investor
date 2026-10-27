# 第四批：股票日线离线运行切片

日期：2026-10-26。状态：五条开发流、公共请求凭据保护、metadata迁移及纵向联调已合入本地集成分支；50文件最终组合1813项通过。整仓gate仍因既有mypy失败，不能宣布迭代完成。尚未push、合入dev或部署。

## 并行交付与边界

| 执行流 | 交付 | 当前边界 |
| --- | --- | --- |
| 主数据与覆盖 | 版本化生命周期、别名与日历证据接口；coverage绑定dataset/source/instrument/publication和查询窗口 | 限期或复用别名必须提供as_of；未知上市起点仍UNKNOWN。日历和生命周期为显式注入证据，尚无真实主数据持久化或coverage REST接线 |
| 股票reviewed job | 默认disabled的股票日线任务工厂、原始响应捕获、请求范围hash核对、标准化及证据权限检查 | 只注入明确合成JSON；未完成真实HTTP源适配，source verified仍False |
| 单任务导入原型 | 冻结计划、审核mapping、目标指纹和hash重算；禁用定义幂等落metadata | 只支持静止、无sidecar的rollback-journal SQLite目标；调用者必须串行化写入。未导入真实任务，不迁执行/checkpoint/事实数据；原1103任务仍全部BLOCKED |
| 持久worker | 自有Engine工厂、持久ledger、受控子进程fetch、heartbeat及fenced结果发布 | 仅SQLite；拒绝外部Engine、内存库、换库及fork复用。未实现生产MySQL worker、全局并发或OS硬资源配额 |
| CLI与角色规划 | 严格JSON输入、统一RunDispatcher提交、显式worker SPI、角色互斥验证 | 未配置入口在读取stdin或连接DB前退出78；角色规划尚未接到main lifespan或部署服务，不会改变legacy默认启动 |
| 公共RunRequest保护 | 拒绝连接配置字段、JDBC/ODBC、URI userinfo、敏感query及畸形URI；固定验证错误路径 | 服务边界重验证，包括model_construct路径；不能把任意伪装字符串识别器当作秘密管理系统 |

每条开发流使用独立branch/worktree和独占文件。独立review保留首次发现与修复后的两组收据；root逐项cherry-pick并负责总合同、迁移序列及组合验收。公共请求保护是审查产生的额外小任务，不把五人职责理解成只能创建五个长期分支。

## 审查修复

- 限期别名缺少as_of可能误报完整覆盖；现要求显式解析时点，并用索引避免别名与生命周期全表交叉扫描。
- 原始证据与请求窗口可能不一致；现重算请求摘要，并在读取前后验证artifact根及managed目录/文件的owner、私有权限和无symlink身份。
- 外部或预热SQLite Engine可能继续指向被替换的旧文件；现只接受自有工厂并绑定文件身份与创建PID，拒绝fork复用。
- 目标指纹检查可能借用旧pool，或因WAL转换创建sidecar；现使用新建受限只读连接，拒绝已存在WAL/sidecar。nolock只适用于调用者保证静止的目标，不提供并发一致性保证。
- CLI和公共RunRequest曾可能让JDBC、ODBC或畸形URI中的凭据入ledger；现提交前拒绝，并验证错误和回执不包含canary。

## 最终组合与门禁

OpenData冻结代码提交为 `9979f7b7daa990c3f68f734e643a2646d1b582a6`。本批AFI没有源代码改动；下一批独立分支不属于本批收据。

- 最终组合：**1813 passed、24 deselected、23 warnings，168.19秒**；选定50份测试、34个覆盖目标，并非整仓测试。
- 语句与分支综合覆盖 **91.46%**；data组 **92.66%**（1756/1895），pipeline组 **94.23%**（5700/6049）。XML、HTML及原始coverage数据归档。runtime_inventory当前unit组合低于85%，其同代码旧只读验证91%为历史收据，本批未冒充重跑或关闭该局部缺口。
- 86份变更Python的Ruff/format与Python3.10语法检查通过；43个core及3个SDK生产文件定向mypy通过，46份生产代码Bandit通过。实际运行Python3.13.5，3.10运行矩阵未执行。
- brand、zero-dep、public API文档/注解、actual main OpenAPI四项定向门禁通过：971份runtime文件、0外部上游依赖引用，2487/2487公开callable文档与注解完整；v1仍140路径、v2仍6路径兼容。
- metadata0007的4项隔离测试及独立review含graph共9项通过；与store互通、升级/降级/再升级保留邻表。MySQL仅DDL编译，真实运行未验。

第一次组合与Gitleaks高负载扫描并行，出现14项执行器失败（1799通过、304.18秒）；日志、命令、覆盖和HTML完整保留。扫描完成后，相同代码、断言、超时和测试范围重跑取得1813通过；这支持资源争用解释，不把它包装成代码修复或所有负载下的保证。后续全历史扫描和进程deadline验收错峰。23条SQLite连接ResourceWarning另保留，未宣称已消除。

完整 `make gate` exit2，当前实际停在A2 mypy：783个逐根目标中13个根失败、25条诊断，均与输入61800c18逐字节相同，和本迭代46个变更生产文件交集为0。此前brand、zero-dep、761提交Gitleaks、ledger、evidence-traceability、js-points、loguru均通过；A2 Ruff/format/Bandit通过。聚合后续项NOT_RUN，不能用四项定向门禁替代。既有archive scope规则未改；缺失历史证据仍开放，但不是这次make gate退出的直接原因。第五批已单独分派这13根的修复。

机器记录见 OpenData `docs/afi204-wave4-validation.json`，持久收据索引 `docs/afi204-wave4-archive.json`。各分支局部通过不替代以上最终组合或整仓gate。

固定Gitleaks 8.30.1已恢复并核对官方校验值。前一次全历史扫描的三个命中均为公开收据hash的格式误报；独立复核后，仅修订自己尚未发布的文档提交，将basename hash键改为真实archive-relative路径。没有更改扫描规则、allowlist、既有历史或归档字节。随后719个提交的扫描通过；这是当时版本的收据，最终source版本另扫描761个提交、0泄漏，聚合门禁仍在A2 mypy失败。第三批“工具缺失、0提交扫描”的历史收据原样保留。

参考OpenBB精确pin已在隔离/tmp checkout恢复，仅用于AST清单验证，未安装或引入运行时SDK。32个provider声明、350个model、202个唯一model的清单探针通过；这不证明350项均可采集或落库。历史证据仍缺5130个支撑路径和16个活动入口，不能伪造审核或改pin消除这些缺失；当前A2对archive的既有范围判定未改变。

## 保留开放的验收

真实源请求、许可、独立上市起点/日历、全历史head/interior/tail、自然发布周期、生产权限、全局限流、raw崩溃回收/保留策略、外部备份恢复、单写者切换及AFI所有消费者迁移均未完成。子进程继承父进程环境和OS权限，是可信函数执行隔离，不能用来运行任意Python。

现有API中coverage无独立证据仍返回UNKNOWN；本批库内coverage能力不会自动改变线上API。AFI行情读路径仍有REST取数后落本地仓库，以及扫描器/分析/信号/多资产等直接源路径，详见 [CONSUMER_MIGRATION.md](CONSUMER_MIGRATION.md)。本批不关闭完整87项控制清单，也不缩小1103个任务或1066条脚本的分母。
