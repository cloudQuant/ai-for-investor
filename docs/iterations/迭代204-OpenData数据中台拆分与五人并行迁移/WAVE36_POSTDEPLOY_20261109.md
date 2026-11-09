# 迭代204 — Wave 36：部署后的实测（2026-11-09）

部署（`ce97f53f5 → 725fabacb`，10:08:37Z）之后做的三件事：验证 #332 的分页在真实服务上是否成立、
追查 full-history-recovery 两条腿的差别、以及量化数据管理界面「表预览」的实际可用比例。

---

## 1. #332 的分页在真实服务上成立（端到端实测，非单元测试）

用 `.env` 里的管理员引导凭据在程序内登录（**token 与密码均未打印**），调用部署中的服务：

| 请求 | 结果 |
|---|---|
| `POST /api/v1/auth/login` | 200 |
| `GET /api/v1/data/tables?page=1&page_size=5` | **200**，`total=1061`，`items` 5 条 |
| `GET /api/v1/data/tables/1049/data?page=1&page_size=2` | **200**，`total=1716250`，`total_source=cached`，`total_age_seconds≈10.9`，`ordering={'strategy':'primary_key','columns':['R_ID'],'direction':'asc','is_total_order':True}`，`rows` 2 条，`error=None` |

也就是说：新增的**显式全序**与**缓存总数**（不再每页 `COUNT(*)`）在部署后的服务里都真的生效了。
这是对 #332 的**服务级**验证，而不是只靠 `96 passed` 的单元测试。

## 2. 但「表预览」对 **98%** 的表是坏的：注册名与物理表名大小写不一致

同一端点对另外两张表返回 `error='Akshare data warehouse is unavailable'`
（`bond_zh_hs_cov_daily`、`stock_sh_a_spot_em`）。抽样 30 张表：**30/30** 都是这个错误。

根因（只读实测）：

| 事实 | 读数 |
|---|---|
| `@@lower_case_table_names` | **0**（区分大小写） |
| `ak_data_tables` 注册行 | **1061** |
| 与物理表名**完全一致**的行 | **18** |
| 仅**大小写不同**就能对上的行 | **1040** |
| 例 | 注册 `bond_zh_hs_cov_daily` ↔ 物理 `BOND_ZH_HS_COV_DAILY`；注册 `stock_sh_a_spot_em` ↔ 物理 `STOCK_SH_A_SPOT_EM`；而注册 `CRYPTO_HOURLY_MARKET` 恰好一致 → 这就是它唯一能用的原因 |

`tables.py:62-67` 的兜底把「表不存在」这类异常统一成 `Akshare data warehouse is unavailable`，
所以日志里看不出真实原因。**影响：数据管理界面里 1040/1061（98%）的表点开都拿不到数据。**

**处置：本轮登记不修。** 属主 2026-11-09 的方向是「先全量迁 OpenData、之后再修」，而这是 AFI 自己的管理 API；
在迁移方向未定前改它，可能是在修一条即将被替换的路径。候选修法记在这里：
(a) 服务层按 `information_schema` 解析真实表名（一次修好 1040 行）；
(b) 把 `ak_data_tables` 的 1040 行改成物理大小写（数据变更）。

## 3. full-history-recovery：crypto 腿成功、stock 腿的 pandas Index 缺陷已修

- 部署后 **crypto 腿** `status=completed, exit_code=0, Finished`（部署前每分钟失败）。
- **stock 腿**报 `controller_internal_error` / `ValueError: The truth value of a Index is ambiguous`；
  绕过兜底拿到精确栈：`stock_full_history_controller.py:1075` 的
  `list(getattr(frame, "columns", []) or [])`——`DataFrame.columns` 是 pandas `Index`，`Index or []` 触发布尔判断。
- 修复在 **#338**：改为显式 `None` 判断；补一条**走真实适配器**的回归测试（原测试全用协议 fake，
  所以这段代码从未被执行）。本机 `47 passed`；并做**只读**真库验证：修复前抛异常，修复后
  `symbols=5592, status=current, reasons=[]`（A 股表 44,513 行 → 5,592；北交所 2,757 → 354）。
- **仍未验证**：stock 腿要在部署新代码后有一次成功运行才算修好；bond 腿在这轮窗口里还没轮到。

## 4. 合并看守的「零检查即通过」缺陷（#339）

看守在 `10:15:13Z` **以 0 个 check-run 合并了 #337**（账本行 `MERGED 0`）。#337 是文档、无后果，
但这是通用漏洞：新建 PR 在 GitHub 注册检查之前，`pending=[]、red=[]` 会被判成「可合」。
与 #331 修的密钥门禁同类——**把「没有信号」当成「信号正常」**。
修法在 **#339**：空集合现在返回 `no-check-runs` 阻断理由 + 回归测试（9 passed）。
旧看守已停，换成打了 guard 的版本后才重启。

## 5. 顺带量到的迁移前置：搬运面比想象窄

对 1057 个采集脚本逐个统计 import：**1044** 依赖 `app.data_fetch.providers.akshare_to_mysql`（基类
`AkshareToMySql`，1043 个子类）、**1047** 依赖 `app.data_fetch.configs.db_config`；
包内助手只有十来个（最多 `common.daily._jin10_macro` 15 次）；第三方只有 `akshare`(28)、`bs4`(4)、`dateutil`(2) 等少量。
**因此「先全量搬运」的物理成本很低**：拷贝 1057 个文件 + 两个基础设施模块 + 十来个助手 + 机械的 import 重写，
不需要动 1000 多个脚本的逻辑。真正的工作量在搬运之后的 provider 化与验证（见迁移计划 B0–B6）。

## 6. 搬运的真正边界：不是 2 个模块，是 21 个

脚本层只 import 两个入口（`akshare_to_mysql`、`db_config`），但这两个入口的**传递闭包是 21 个 `app.*` 模块**：

```
app.ai_provider_registry
app.config / app.config_parsing
app.data_fetch.configs.db_config
app.data_fetch.core.database / app.data_fetch.core.mysql_base
app.data_fetch.providers.akshare_to_mysql
app.data_fetch.utils.akshare_network_proxy / common_utils
app.services.market_data.openbb_runtime
app.settings.{ai_assistant, ai_research_v2, application, asset_research,
              broker_accounts, database, market_data, operations, paths,
              security_auth, service_deployments}
```

两处耦合值得单独记：

- **`app.settings.market_data → app.services.market_data.openbb_runtime`**：设置包反向依赖服务层，
  意味着「先搬两个文件」在依赖上并不成立；
- `app.settings.ai_assistant → app.ai_provider_registry`：同类。

**含义**：把 1057 个脚本搬进 OpenData 之前，必须先把这 21 个模块（或替身/解耦版本）一起搬过去。
这不是「拷两个文件」，但仍然是一份**有限且可枚举**的清单——比逐脚本改造小两个数量级。

## 7. 部署后 full-history-recovery 的五资产轮转实况（10:13–10:24Z）

轮转顺序 `stock → crypto → bond → etf → option`，每分钟一个资产。最近 12 次运行：

| 资产 | 状态 | 说明 |
|---|---|---|
| **stock** | `invalid_or_missing_cli_report`（"expected CLI report was not created"） | **仍是 pandas Index 崩溃**——#338 的修复尚未部署 |
| **crypto** | **completed** | 部署前每分钟失败，部署后稳定完成 |
| **bond** | `attention_required` | **不再崩**：#333 的 `%` 修复生效；报告写出 290 KB |
| **etf** | `attention_required` | 同上（报告产出，worker 判需关注） |
| **option** | `attention_required` | 同上 |

**bond 的具体原因**：`bond-report.json` 有 5 条 outcomes，**5/5 都是 `post_write_mismatch`**
（`mode: managed_bounded_convertible_history_reconciliation`）。也就是说：控制器已经能连接、抓取、写入，
但**写后校验发现自己写进去的内容与校验读回的不一致**——这是数据一致性缺陷，与 #333 修的格式化异常是两件事。

**因此「#333 修好债券腿」要分两层说**：崩溃（`TypeError`）已经消失并可复现地证实；
但这条腿仍未产出可信结果，因为下一步卡在 `post_write_mismatch`。判定该 unit 健康的标准依旧是一次
**没有 mismatch 的成功运行**，而不是「不再抛异常」。

## 8. 对「实现这些参数」这条决定的一个反证：`_ingest_mode` 不是脚本参数

属主 2026-11-09 对 7 个任务的参数代差选择了「实现这些参数」。按这个决定动手之前，我查了每个键的来历：

| 键 | 全历史（`git log --all -S`） | 现状 |
|---|---|---|
| `_ingest_mode` | **有**：出现在 `run_full_history_recovery_worker.py`、bond/cffex/crypto 各控制器与 cfets 验收脚本 | **派发层标记**：worker 在 `:1688` 校验 dispatch 的 `parameters["_ingest_mode"] == "backfill"`；控制器构造调用时写 `"backfill"` 或 `"live"` |
| `calendar_review_by_market` | **无任何提交** | 只存在于任务参数 JSON |
| `trading_days_by_market` | **无任何提交** | 同上 |
| `overlap_days` | **无任何提交** | 同上 |
| `start_date` / `end_date` / `source` / `source_timeout_seconds` / `sleep_seconds` | 各自在脚本里有同义实现或近义参数 | 脚本级参数，语义可从现有代码读出 |

**含义**：至少 `_ingest_mode` 不该「在脚本里实现」——它是**派发层的元数据**（worker 拿它区分 backfill 与 live），
把它实现进 `FuturesDailyMarket.run()` 反而会把一个调度概念塞进采集脚本。正确的分层应是：
**派发边界消费/剥离派发元数据，脚本只接脚本参数**。

而 `calendar_review_by_market`、`trading_days_by_market`、`overlap_days` 三个键**在任何提交里都没有定义**，
无法从代码反推语义——它们要么来自未入库的一次性实验配置，要么是为尚未落地的接口预留的。
对这三个键「实现」等于**由实现者发明语义**，这会改变取数窗口且无从验证。

**因此建议把「实现」拆成两半**（需要属主确认，本轮不动代码）：
1. `_ingest_mode`：在派发边界消费，不传给脚本（并加一条测试禁止它出现在脚本 kwargs 里）；
2. `overlap_days` / `trading_days_by_market` / `calendar_review_by_market`：**先定义语义**（属主或产品），
   再按定义实现；
3. `start_date`/`end_date`/`source`/`source_timeout_seconds`/`sleep_seconds`：可直接按现有代码的同义逻辑实现。
