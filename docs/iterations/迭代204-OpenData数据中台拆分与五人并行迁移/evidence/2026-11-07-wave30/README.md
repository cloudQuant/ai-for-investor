# Wave 30 取证（2026-11-07）

本目录的脚本产生记录 §7 里的每个读数。共同约定：只读（`git rev-parse` / `alembic heads|current` /
只读 SELECT 会话），不写库、不改服务状态。

| 脚本 | 产出 | 读写 |
|---|---|---|
| `deploy_state_verification.py` | 「已部署」的四问四答：运行提交 vs 分支尖、迁移 heads/current、近期任务的时钟偏差、停用后的幽灵入口失败数、armed 总数 | 只读 |
| `deploy_state_verification.2026-11-07T1741Z.json` | 上一条 17:41:14Z 的实际输出（`deployed_head_is_branch_tip: false`，落后 dev 一个纯文档提交） | — |

用法：`python3 deploy_state_verification.py [--since-minutes 30]`。它默认检查主工作树
`/home/yun/Documents/ai-for-investor`，也就是 systemd 单元实际运行的那棵树。

仪器第一版的两个缺陷（把 `alembic current` 的 `INFO` 行当 revision、只报脏条目数量不报内容与
"运行提交 vs 分支尖"）已修；修之前它给出的"看起来是事实"的两行读数都是噪声。
