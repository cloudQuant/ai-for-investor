# 第五批：图表直读、MySQL worker与类型边界

状态：**开发中，尚未整批验收**。代码仅合入隔离集成分支，未push、未合入dev、未部署。本页是第五批进度快照，第四批冻结代码和归档保持不变。

## 已集成的局部交付

| 执行流 | 提交与验证 | 保留边界 |
| --- | --- | --- |
| AFI普通股票日线图表 | 集成`6203d18ef`、日期修复`b7514d444`；7份明确测试文件共230 passed；独立复核无剩余P1/P2 | 只在明确启用OpenData且符合股票1d合同的已有kline路径直接投影REST；默认开关未改，其他消费者仍开放 |
| 10文件纯类型清理 | OpenData集成`10c9d012`；删除冗余cast/无效ignore与无用import，独立复核未见runtime改变 | 没有更改规则、依赖或质量豁免 |
| 3文件日期/DataFrame类型边界 | 集成`7b810652`；独立复核修复后无剩余P1/P2 | 明确拒绝非字符串及重复列名，复权NaN传播保持；覆盖率验收仍未通过，修复后pytest尚未运行 |

root在OpenData `7b810652` 对前次失败的13个根重新运行完整Ruff/format、逐根mypy和Bandit，全部通过。私有回执为`wave5-thirteen-typing-roots-static.json`。这是精确13根检查，不是整仓A2或make gate通过。实际运行时仍为Python3.13.5，Python3.10运行矩阵未执行。

AFI独立审查曾发现上海业务日窗口误映射前一天：原来的测试响应忽略URL参数而未暴露问题。现仅在legacy到public-query适配层转换日期轴，测试根据实际start/end过滤源数据；未更改OpenData源trade_date或全局normalizer。stock_daily类型修复也曾引入同日排序漂移，现按自然日键稳定排序，并增加同日15:00在09:00前的源序黄金用例。

## 审查和补充任务

MySQL worker草案已有临时私有Unix socket MySQL8.4的实际测试证据，但独立审查仍发现TLS信任材料漂移、timeout校验晚于身份查询、socket父目录0750不够私有三个问题。草案尚未合并；修复、独立复核和最终定向验证完成前不能声明该worker验收通过。远程TLS握手未执行。

数据模块触碰后的覆盖阈值仍按90%执行。保存的旧报告中三文件汇总80.75%，其中_sdk.py为67.46%；该报告发生在最终修复之前，且来自下述越界执行，不作第五批验收通过证据。正在编写仅使用fake transport与预计算期望的离线边界测试，不引入运行时SDK、不降低阈值。

## 测试范围越界与收敛

- 第一事件：typing代理在其隔离工作树执行整个tests目录，报告28383 passed、236 skipped、22 failed和1项teardown error，覆盖命令exit非零。日志包含scheduled pipeline取消用例尝试默认localhost MySQL、连接被拒；它没有使用root创建的owned MySQL URL。
- 第二事件：HTTP流式分支代理启动目录级tests后中断，旧会话退出2、无完整收集/执行摘要及落盘stdout；不能从约41个进度点推断所有实际执行节点。
- 两次运行均未在启动前显式设置APP_ENV、TESTING和REDIS_URL。测试标记not e2e不能证明每个非e2e节点均被fixture隔离。AccessDenied也不能证明其他测试没有成功连接或写入；默认DB、外部服务与持久文件的影响仍待只读审计，未擅自连接或回滚未知目标。

root已禁止开发代理继续pytest/coverage，集中审核后续精确文件命令。新增测试默认目标保护独立分支，拟在DBAPI connect前阻止普通测试使用两条应用默认Engine，并移除全局fixture清理共享Redis的路径；它不代表全局网络或文件隔离。后续完整gate会触发目录级test-cov，当前尚未重跑，不冒用静态组件或第四批结果宣布整仓绿灯。

## 后续范围

HTTP流式body cap和合作式预算另在第六批分支开发，尚未合并或最终验证。真实源、许可、全历史head/interior/tail、原1103任务导入、生产角色/调度/API/管理页面接线、全部AFI消费者、自然周期、外部备份恢复和单写者切换仍保持开放。完整87项任务状态不因本页局部交付而整体关闭。
