# 第五批：首条业务直读与MySQL worker

状态：四条核心开发流已产生可复核的局部代码与定向结果。root在提交31cfd70ba62dee6e1243d7ea9100a15532e49f95完成的fixture专用修复通过review后，同一58文件组合2199 passed、25 deselected，另有fixture与guard定向22 passed。最终静态、named gates及A2均已在31cfd70ba62dee6e1243d7ea9100a15532e49f95通过，冻结归档共121个文件、12,400,793 bytes；OpenData验证manifest限定状态为SCOPED_CODE_AND_ISOLATED_INTEGRATION_VALIDATED、NOT_PRODUCTION_ACCEPTED，整仓make gate NOT_RUN。第四批收据保持冻结，当前证据见[WAVE5_STATUS.md](WAVE5_STATUS.md)。没有修改本批范围、阈值或质量豁免。

| 执行流 | 输入基线与独占范围 | 交付与局部结果 | 保留边界 |
| --- | --- | --- | --- |
| AFI股票图表REST直读，204-E03-01局部 | AFI 69c5dcd08；query_service.py、api/data/base.py及新增direct-query测试；独立branch/worktree | 直读提交6203d18ef，日期窗口修复b7514d444；7个定向测试文件230 passed | 仅明确启用OpenData时的既有股票1d图表路径；E03-01完整消费者接线仍开放 |
| MySQL持久worker，204-D02-04局部 | OpenData 9979f7b7；pipeline/reviewed_worker.py与MySQL worker测试；独立branch/worktree | 自有私有Unix socket MySQL 8.4实际运行；41 passed，worker覆盖91.2467%，3个自有随机schema清理，实例已停止 | 16个ResourceWarning（未关闭SQLite连接）未解决；远程TLS握手未执行；生产worker未部署 |
| A2纯类型清理 | OpenData 9979f7b7；13个精确文件 | 全A2 resolver 1,189个文件、783个mypy roots无失败；Ruff、format、mypy、Bandit依现有策略通过 | 333个docs/evidence Python文件仍按原规则排除；历史Ruff、support与active-evidence缺失仍开放；不代表make gate |
| DataFrame与日期类型边界 | OpenData 9979f7b7；yfinance _sdk.py、stock_daily.py及pipeline/dwd_merge.py | 7个定向测试文件366 passed、1 skipped；综合覆盖率95.3795%，各文件99.0499%、100%、90.1299% | 保持90%门槛；覆盖仅针对三个改动模块，不代表整仓覆盖率 |

## 契约决定

原计划先修改通用/data/queries读路径。检查发现其固定响应要求AFI本地revision、commit、receipt和cursor锚点，而现有OpenData v1 Provider没有这些持久身份。不能将retrieved_at伪装成committed_at或编造receipt。因此首切片由public resolver正式签发既有stock.realtime查询，再投影为已有无cursor的legacy股票图表响应，保留原通用query DTO和显式local_only研究绑定语义。

本批只对审定stock/1d/CN合同、普通在线、有界窗口生效；不支持的频率/资产/超量请求不能静默降频、截断或回退旧SDK。默认OpenData开关不变。通用查询、搜索、回测、扫描器、分析、信号及多资产迁移仍按完整消费者矩阵推进。

MySQL工厂默认拒绝明文TCP，只允许显式验证证书/主机名的TLS或受控私有Unix socket；当前测试只验证自有私有socket实例，远程TLS握手仍NOT_RUN。工厂不读取默认settings或生产凭据，不自动建表；worker继续只接受ProcessFetchHandler。连接/读写超时不等于任意SQL或磁盘的硬资源保证。独立MySQL测试必须绑定随机自有库、明确实例身份并清理自建资源，禁止连接203恢复库。

## 测试保护、审计与最终重跑

root对七个已知应用默认数据库目标增加guard，20项定向回归通过。它覆盖默认Engine的连接、池checkout、pre-ping和保留连接SQL访问路径，以及精确授权的测试生命周期；它不是网络或文件系统沙箱，也不保护任意新Engine、原始DBAPI句柄或上游HTTP。

两次未经批准的目录级测试执行已完成只读审计，日志证据与未知影响见[WAVE5_STATUS.md](WAVE5_STATUS.md)。审计归档固定保存在本机私有路径。root复核并合入的fixture专用修复提交为31cfd70ba62dee6e1243d7ea9100a15532e49f95，未改生产代码或削弱guard。修复后同一58文件组合为2199 passed、25 deselected；两个fixture与20项guard命令为22 passed。修复前2197 passed、2项fixture失败的旧组合不作最终证据。最终静态、named gates及A2已在31cfd70ba62dee6e1243d7ea9100a15532e49f95通过；121文件的冻结私有证据归档和公开验证manifest记录见[WAVE5_STATUS.md](WAVE5_STATUS.md)。

完整make gate会触发目录级test-cov，目前NOT_RUN。已完成的定向验证不能替代完整门禁、生产/真实源验证或自然周期。两次范围越界的未知影响须继续保持未知，不能通过回滚未知资源或放宽阈值来取得绿灯。

## 集成纪律

各条分支分别提交，由其他代理独立review，root再合入对应仓库。共享schema、迁移序列、质量清单和总启动仍由root排队管理。进程deadline回归与CPU密集全历史扫描错峰执行，避免验证任务争用资源；失败日志保留，不能通过放宽超时或跳过断言取得绿灯。

本批不改变生产调度、systemd、API开关或原目录203业务代码。第四批收据保持冻结；本批各测试结果按自身提交与精确命令记录。
