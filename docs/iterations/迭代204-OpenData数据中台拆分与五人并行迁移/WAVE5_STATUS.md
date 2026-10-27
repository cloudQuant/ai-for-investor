# 第五批：图表直读、MySQL worker与类型边界

记录日期：2026-10-27（Asia/Shanghai）。状态：**本批局部代码与隔离集成验证完成；OpenData验证状态为SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED，NOT_PRODUCTION_ACCEPTED。** root复核的fixture专用修复与最终静态结果均锚定提交31cfd70ba62dee6e1243d7ea9100a15532e49f95；证据归档已冻结。AFI与OpenData代码留在各自隔离分支，未push、未合入dev、未部署。第四批代码和归档保持冻结。

## 局部交付与证据

| 工作流 | 收据与结果 | 边界 |
| --- | --- | --- |
| AFI股票图表REST直读 | 图表直读提交6203d18ef及日期窗口修复b7514d444；7个定向测试文件230 passed（Python 3.13.5） | 只覆盖明确启用OpenData且符合既有股票1d合同的图表读取；原许可、身份及默认开关边界保留。不是所有AFI消费者迁移完成 |
| OpenData A2类型静态检查 | 最终静态收据在OpenData提交31cfd70ba62dee6e1243d7ea9100a15532e49f95上通过：1,189个A2 resolver文件、783个mypy roots且0个失败；Ruff、format、mypy、Bandit及命名gate按当前策略通过 | 333个docs/evidence Python文件依既有规则排除静态工具；没有改范围或豁免。149,323条历史Ruff发现仍为NOT GREEN（历史证据）；5,130项support及16项active-evidence缺失仍OPEN |
| DataFrame与日期类型边界 | OpenData cb3fbec5235f557fd212be4b63ceae141cf2859a上的7个定向文件366 passed、1 skipped；三个目标模块综合覆盖率95.3795%，高于90%门槛 | _sdk.py 99.0499%，stock_daily.py 100%，dwd_merge.py 90.1299%。三个目标文件在最终提交中哈希一致；最终58文件组合不采集覆盖率，覆盖率来自此前独立命令。保留源日期、自然日排序、复权NaN传播与重复列拒绝语义 |
| MySQL持久worker | OpenData cb3fbec5235f557fd212be4b63ceae141cf2859a上的专用MySQL命令41 passed；reviewed_worker.py分支/语句覆盖率91.2467%，高于90%门槛 | worker及相关目标文件在最终提交中哈希一致，但最终58文件命令没有包含MySQL专用测试文件，故41项结果仍锚定前次专用命令。16个ResourceWarning报告未关闭SQLite连接，仍待处理。仅验证隔离私有Unix socket上的自有MySQL 8.4实例；三个随机测试schema均清理，实例已停止。远程TLS握手NOT_RUN |
| 默认测试目标guard | 七个目标的20项专用命令在cb3fbec5235f557fd212be4b63ceae141cf2859a上通过；最终31cfd70命令也包含guard测试 | 保护连接、checkout、保留连接SQL及pool pre-ping路径；是目标级测试保护，不是操作系统沙箱或全局网络/文件隔离 |

上述OpenData测试与覆盖率命令使用Python 3.13.5。最终静态结果覆盖106个变更Python文件，production mypy检查56个core与3个client文件，Bandit检查59个生产文件；brand、zero-dep、public-api-quality与published-OpenAPI命名gate通过。OpenAPI v1/v2分别校验140和6条live paths，2,488个public callables的docstring与annotation覆盖均为100%。Python 3.10只完成AST语法检查，没有运行时矩阵结果。完整make gate仍NOT_RUN。

## 最终组合与整仓门禁

root对fixture专用修复31cfd70ba62dee6e1243d7ea9100a15532e49f95完成复核；修复只调整测试fixture，未改生产代码或削弱guard。相同58文件组合在该提交上2199 passed、25 deselected，耗时109.78秒，没有报告warning；两个fixture回归加20项guard回归另为22 passed、1.04秒。此前2197 passed、2项fixture失败的旧组合属于修复前结果，不作为最终结果。最终静态和A2复跑已在31cfd70ba62dee6e1243d7ea9100a15532e49f95通过（1,189个resolver文件、783个mypy roots、0个失败，范围与gate规则未变）；最终私有归档与公开验证manifest均已冻结。manifest将本批限定为局部代码和隔离集成验证通过，NOT_PRODUCTION_ACCEPTED。

完整make gate **NOT_RUN**。A2全量resolver静态检查通过不等于pytest、全仓质量门禁或生产验收通过；没有改变任务范围、质量阈值或历史证据豁免。

## 修正前失败的保留记录

首轮六文件frames覆盖率为86.36%，未达90%门槛；加入经过单独复核的financial_pit测试后，七文件定向命令达到95.3795%，首轮报告保留在归档中。MySQL worker首轮因AF_UNIX socket路径过长而39 passed、2 failed；保持代码、断言和deadline不变，仅缩短自有basetemp路径后41 passed，首轮失败也保留。组合测试首轮2197 passed、25 deselected、2个owned-SQLite fixture失败；仅修复两个测试fixture后在最终提交通过，guard与生产代码未变。

## 测试范围审计

两次先前未经批准的目录级测试执行已完成只读审计。第一次运行整个tests目录，留存结果为28,383 passed、236 skipped、22 failed及1项teardown error；日志记录一个取消用例尝试连接默认localhost MySQL并被拒绝。第二次目录级执行被中断，只留下约41个进度点，没有完整收集清单或最终摘要。审计没有证明这两次执行无副作用；未知数据库连接、外部数据库影响及文件副作用仍保持未知。没有擅自连接或回滚未知目标。

不可变审计归档位于`/home/yun/Documents/opendata/var/reports/afi204/2026-10-26-wave5-test-scope`，共6个文件、530,049 bytes，保持私有；审计已冻结，未知影响不因此转为已知。独立复核的默认目标保护仅覆盖前述七个目标，不覆盖任意Engine、原始DBAPI句柄、上游HTTP或文件系统。

## 最终归档与公开收据

冻结的同机忽略归档位于`/home/yun/Documents/opendata/var/reports/afi204/2026-10-27-wave5`，共121个文件、12,400,793 bytes；目录权限0700、文件权限0600。它是同机私有证据保存，不是外部备份或恢复演练。OpenData仓库的公开验证与归档manifest分别为`/home/yun/Documents/opendata-od204/docs/afi204-wave5-validation.json`和`/home/yun/Documents/opendata-od204/docs/afi204-wave5-archive.json`。验证manifest将本批状态限定为SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED、NOT_PRODUCTION_ACCEPTED；真实源未验证，rights/retention未知。

## 仍开放的迁移范围

1,103个旧任务（本批无真实任务导入、无ready任务）、真实源与许可/保留期核验、逐instrument全历史head/interior/tail、全部生产角色与CLI/UI接线、所有AFI消费者、自然调度周期、外部备份恢复和单写者切换继续开放。87个控制任务状态仍为8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；204-E03-01仍为局部完成。截至第五批冻结时点，第六批HTTP边界代码分支3d16400c有静态复核结果，尚未由root合入或测试；stock进程切片仍在开发，默认关闭且运行权限未知。后续第六批合入、回归及修复进展另行记录，不计入本页第五批验收收据。
