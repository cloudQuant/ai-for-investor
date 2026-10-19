# Iteration10：组合授权与独立账户快照

在现有 AFI/dev 上，live 组合 POST 对未绑定/越权策略先按 ServiceReadAccessDirectory 拒绝，禁止在校验前写入成员版本。历史版本的 GET 保留既有未绑定成员，不隐式改账。

账户投影增加既有公开 source/session/cursor/观测时间/覆盖字段；汇总明确为独立 cut、atomic=false，给出精确纳秒 skew、同刻/异刻/字段不全状态。缺字段不伪造零值，也不自设过期阈值；账户私密键不进入响应。FX/合约乘数等完整 AFI03 行为仍待实现/验收。

Root 固定输入验证分轮保留：新增授权 1 项和 cut 3 项在最初 API suite 全通过；同轮旧 membership 节点因缺少既有审批 epoch 表失败。只修测试 SQLite schema 及历史 seed 后，旧 API 节点 1 passed/4.65s，两个真实 HTTP→SDK→ServiceHost 节点 2 passed/13.66s；各轮2135 source pins与AFI/SDK HEAD不变，stderr为空，各有2条既有弃用warning。合并运行的 collection 失败源于两测试模块使用不同 synthetic Settings 缓存，已用独立解释器分开，未弱化 JWT 断言；该失败原件也保留。此前4个通过节点没有重复。

Host 用固定 P9B SDK export 与真实本机服务、合成 provider，未声称覆盖当前 SDK MIG03 实现或真实账户。独立静态审核 review_afi_financial 接受生产改动与最终两处 fixture delta。formal用例按SDK状态表逐条裁定，7项测试通过不直接等于7个formal PASS。

精确5个源码/测试路径加本记录提交；父30797a3901060b7476ce5717d9ae218e5cd54c8d，提交哈希见Git历史。SDK归档保存4次执行的command/stdout/stderr/JUnit/spec/result及前后pins，原路径D:/temp/iteration10-afi-auth-cuts-http-root-20261016-r1和D:/temp/iteration10-afi-auth-cuts-root-20261016-{r1,r2-api,r2-host}。
