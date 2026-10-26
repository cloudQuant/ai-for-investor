# 第五批：首条业务直读与MySQL worker

状态：四条独立开发流已启动；10文件纯类型清理已交付并独立复核，尚未合并。本批整体未验收。第四批最终组合与整仓门禁单独留证，不被本批开发覆盖。

| 执行流 | 输入基线与独占文件 | 交付与验收 |
| --- | --- | --- |
| AFI股票图表REST直读，204-E03-01局部 | AFI `69c5dcd08`；`query_service.py`、`api/data/base.py`和新增direct-query测试；独立branch/worktree | 明确启用OpenData时，已有`/api/v1/data/kline`普通股票日线查询直接投影REST返回；身份/许可/访问门禁不变。测试证明该消费路径不写入或重读AFI市场事实库，不调用旧SDK；空结果、非法日期/标的、错误和超限显式处理 |
| MySQL持久worker，204-D02-04局部 | OpenData `9979f7b7`；`pipeline/reviewed_worker.py`和新增MySQL worker测试；独立branch/worktree | 保留SQLite身份/PID保护；新增自有MySQL Engine工厂，核验实际server UUID与schema，约束pool/driver超时并使用数据库时钟。仅owned临时MySQL可写，必须实际验证后才能声明支持；skip或DDL编译不算通过 |
| A2纯类型清理 | OpenData `9979f7b7`；10个精确文件（示例、mapping、两个yfinance模型、dump/retry及4份脚本） | 仅删冗余cast/无效ignore，逐文件mypy与既有unit行为验证，独立复核后合并；不改规则或运行语义 |
| DataFrame与日期类型边界 | OpenData `9979f7b7`；yfinance `_sdk.py`、`stock_daily.py`和`pipeline/dwd_merge.py` | 处理其余三个mypy根；禁止通过Any/cast/ignore、静默改列名或丢键压债，复权/日期/PIT/空值黄金向量与负例必须保持 |

## 契约调整

原计划先修改通用`/data/queries`读路径。检查发现其固定响应要求AFI本地revision、commit、receipt和cursor锚点，而现有OpenData v1 Provider没有这些持久身份。不能将retrieved_at伪装为committed_at或编造receipt。因此首切片由public resolver正式签发既有stock.realtime查询，再投影为已有无cursor的legacy股票图表响应，保留原通用query DTO和显式local_only研究绑定语义。

本批只对审定stock/1d/CN合同、普通在线、有界窗口生效；不支持的频率/资产/超量请求不能静默降频、截断或回退旧SDK。默认OpenData开关不变。通用查询、搜索、回测、扫描器、分析、信号及多资产迁移仍按完整消费者矩阵推进。

MySQL工厂默认拒绝明文TCP，只允许显式验证证书/主机名的TLS或受控私有Unix socket；实际TLS握手须另留证，不能仅凭配置校验宣布部署安全。工厂不读取默认settings或生产凭据，不自动建表；worker继续只接受ProcessFetchHandler。连接/读写超时不等于任意SQL或磁盘的硬资源保证。独立MySQL测试必须绑定随机自有库、明确实例身份并清理自建资源，禁止连接203恢复库。

## 集成纪律

各条分支分别提交，由其他代理独立review，root再合入对应仓库。共享schema、迁移序列、质量清单和总启动仍由root排队管理。进程deadline回归与CPU密集全历史扫描错峰执行，避免验证任务争用资源；失败日志保留，不能通过放宽超时或跳过断言取得绿灯。

本批不改变生产调度、systemd、API开关或原目录203业务代码。第四批收据保持冻结，本批测试结果另行归档。
