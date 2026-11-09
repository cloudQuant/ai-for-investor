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
