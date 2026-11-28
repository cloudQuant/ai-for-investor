# WP07 最终验收记录（2026-11-25）

## 结论

- 迭代 207：**24 / 24 COMPLETED，ACCEPTED_LOCAL**。
- 本地确定性门禁、前端全套、迭代 207 新增后端回归、受影响文件回归均通过。
- 本机全量后端未全绿；最终失败节点集合与基线 `4bdfab992fc4d0a0e169d2bba30d88bbe57509a8` 完全一致，没有残留的本轮新增失败。
- 未提交、未推送；证据保留本地。

## 最终回归

| 范围 | 结果 | 证据 |
|---|---|---|
| 迭代 207 新增后端测试 | 40 passed | `iteration207-regression.log` |
| 最终修复受影响测试文件 | 69 passed | `affected-regression.log` |
| AI 策略研究主链 | 220 passed | 本会话直接运行输出 |
| 前端 | 185 files / 2,228 tests passed；typecheck、lint、build 通过 | `../WP05/`、`../WP06/green-summary.log` |
| 浏览器 smoke | 回测、行情、新闻正文、股票分析页面通过 | `../WP05/browser-verification.log` |

## 全量后端归因

首次全量命令：

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/yunjinqi/opt/anaconda3/bin/python \
  -m pytest -q -n 4 --dist loadfile --tb=short
```

结果：`31 failed, 10972 passed, 185 skipped, 15 xfailed, 13 errors`，见 `backend-full.log`。

- 9 个 performance setup error：命令未使用 CI 的 `-m "not performance"`；基准在 xdist 下禁用，测试数据库未版本化。
- 3 个 collection error：仓外 SDK 缺 `GatewayOkxMarketBinding`、`FreezeActivationStatus`、`MonitorRiskControlOwner`，基线同样失败。最终 `collect-only -m "not performance"` 仍只有这 3 个错误，本轮导入错误已消失，见 `collect-final.log`。
- 1 个 collection error：本轮测试从旧模块导入已垂直切片符号；已改为新模块导入。
- 11 个回归：旧测试使用不存在的 JWT 用户、同步 WebSocket mock、过宽 `returns` 子串断言，以及未更新缺失/停用用户 401 契约；已只修测试夹具/断言。
- 1 个新增测试顺序敏感失败：日志 `propagate` 被前序测试关闭；测试内已显式恢复。
- `test_data_topic_hub_lru_eviction_and_tracked_task_cleanup` 的全量 caplog 顺序敏感失败在当前与基线隔离复跑均通过，未据此声称全量 PASS。

最终对原 31 个失败节点在当前分支复跑：`18 failed, 13 passed`；基线排除不存在的新增测试后：`18 failed, 12 passed`。`failure-set-diff.json` 记录：

```json
{
  "current_failed": 18,
  "baseline_failed": 18,
  "new_failures": [],
  "resolved_failures": [],
  "sets_equal": true
}
```

18 个共同失败为既有 fixture、仓外 SDK/环境或本机 httpx 代理 URL 问题，不是迭代 207 回归。

## 门禁

- Ruff：通过。
- 大文件棘轮：通过，baseline 未上调。
- 复杂度：`max_cc=91, count_cc_ge_50=31`，通过。
- mypy 1.20.2 / Python 3.11.8：app 0 错误 / 794 files；collection 0 错误 / 1108 files。
- collection CI baseline 保持 2；基线文件要求 CI provenance，未用本机结果伪造收紧。
- Alembic：88 revisions，单 head。
- ORM drift、依赖声明同步、敏感跟踪文件、文档链接、图标 A11y、生产锁唯一性：通过。
- 生成物检查、迁移安全 lint：通过。
- gitleaks 全历史：0 findings；audited baseline `418 / unresolved 0` 校验通过。
- 当前已跟踪严格扫描：133 个候选，未分类为已确认泄漏。
- 新增非证据文件单独严格扫描：28 files / 0 candidates，见 `untracked-secrets.json`。

环境边界：本机基础 Python 未安装锁定依赖，`check_lockfile_sync.py` 报 94 个版本差异和 26 个缺失包；这是 installed-vs-lock 环境检查，不是锁文件漂移。`check_deps_sync.py` 的声明/锁文件一致性检查通过。未把本机环境校验写成远端 CI PASS。

## E3 与发布边界

- SQLite 双进程纸交易：实际执行，仅一笔成交，现金/持仓/交易精确。
- SQLite 行情持久化取消与 fenced receipt 恢复：受控数据库实际执行。
- 外部 evaluator fixture：隔离 manifest 与 receipt 充分性实际执行。
- 浏览器 smoke：实际执行。
- MySQL/PostgreSQL：保留 `FOR UPDATE` 编译与契约回归；未冒充已连接真实 MySQL/PostgreSQL。
- 部署回滚演练、远端 CI、生产发布：未执行，仍属发布前闸门。

## 工作树

- 分支：`dev`。
- HEAD：`4bdfab992fc4d0a0e169d2bba30d88bbe57509a8`。
- 本轮代码、测试、文档留在工作树；`evidence/` 不纳入提交。
- 未创建提交，未推送。
