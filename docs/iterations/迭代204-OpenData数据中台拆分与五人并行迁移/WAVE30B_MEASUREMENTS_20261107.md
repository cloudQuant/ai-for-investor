# Wave 30b 测量记录（2026-11-07）：四个"已量化但未定夺"的项

本文只记录四件在本机测出来、且**每一项都能改变某个待定决策**的事实。它不替代
`DEVELOPMENT_STATUS.md` 的 wave 30 段，也**没有把任何 AC 判定改成通过**。
所有测量都在 CI 同构环境（`/tmp/it204/venv-ci`：Python 3.11.15 +
`config/requirements-dev.lock`，pandas 3.0.3、无 pandas-stubs；该环境在 dev `0a4c5ab31` 上
复现过 CI 的 `errors=101 checked=1108`）或只读 SQL 上完成。

## 1. 采集平面最后 2 条 = dateutil stub，加 stub 的代价实测为**零**

树：dev `3325626f96` + PR #319 的 5 处修复（`.wt-afi-tranche4`）。

| 步骤 | collection | app（blocking，baseline 0） |
|---|---|---|
| 装 `types-python-dateutil==2.9.0.20261104` 前 | 62 / 1108 | 0 / 757，delta +0 |
| 装后 | **60** / 1108 | **0** / 757，delta +0 |
| 卸载后复核 | 62 / 1108 | — |

结论：正好 −2（两条 `Library stubs not installed for "dateutil.relativedelta"`），
blocking 的 app 面**不新增任何错误**。与 `types-requests` 的实验（159→119，但 app 0→+6）相反：
那一个要价，这一个免费。

处置：`config/requirements-dev.lock` 属依赖声明（risk map 把依赖判为 R3 级），
需属主点头后由 `./scripts/ops/generate_lockfiles.sh` 重新生成并同 PR 提交。
做完后 #308/#314/#319 全部合入时 collection 应读 **0**，而不是 2。

## 2. AC11 的 886 条 `accepts_var_kwargs` 不是"不可验"，是"只验了一层"

只读 AST 形状扫描 `app/data_fetch/scripts`（1108 个 .py；脚本与输出见
`evidence/2026-11-07-wave30b/kwargs_ceiling.py`）：

| 形状 | 数量 |
|---|---|
| 把 `**kwargs` 转发给唯一字面名 | **827** |
| 收了 `**kwargs` 但什么都不转发 | 52 |
| 转发给多处/多名 | 8 |
| 同文件内可直读的本地被调 | 1 |
| 入口不接 `**kwargs` | 220 |

关键一步：那 827 条的"外部名"是**仓内的共享层**
`AkshareToMySql.fetch_ak_data(self, function_name, *args, **kwargs)`
（`app/data_fetch/providers/akshare_to_mysql.py:88`；`akshare_provider.py:214` 同形），
它只 `pop("_call_timeout")`，其余 kwargs 原样转给 `getattr(ak, function_name)(*args, **kwargs)`。

因此这 827 条的准确状态是：**驱动层 binds（`fetch_ak_data` 接受任意关键字）**，
未知的是**第二跳**——被取到的 akshare 函数是否接受这些键。运行时那 7 条
`… got an unexpected keyword argument` 正是这个形态：过了驱动层，死在源函数层。

于是 #284 的 caveat 应改写为：真正"按形状不可判"的是 **60 条**（52 + 8），
加上 `source_function` 未解析的 89 行；其余 827 条是**可执行的签名核对任务**，不是先验不可知。
本文没有把任何一条改判为 binds，只改写了上界。

## 3. §6 的 `missing_axes`：960 行没有任何待补轴——但需要用**完整调用**才算得出

`assign_script_dispositions.py` 用**含 `--registration-export`** 的调用跑 1057 行：

| `missing_axes` | 行数 |
|---|---|
| （无） | **960** |
| `source_function` | 66 |
| `single_source_function` | 17 |
| `source_function;target_table` | 14 |

**坑**：不带 `--registration-export` 时，1057 行**全部**会显示 `registration` 这一轴
（第一版台账就是这样，960 条看起来"全都缺注册信息"）。实测补上该导出后
`registration` 从每一行消失、而 **disposition 一个都没变**（0 diff）——那条轴是调用参数造成的假象。
AC11 的签字命令必须带它，否则签出来的台账会带一个不存在的缺口。
（签核件与说明：`~/afi204-evidence/2026-11-07-ac11-review/`。）

## 4. 一次被我叫停并完整回滚的生产写：不要为了把检查变绿而删掉操作者的数据

普查报 7 个任务 `unexpected_param: _ingest_mode`，而全树 `grep _ingest_mode app/` **0 命中**，
于是按 20 个 armed 行删掉该键，并用"普查驱动循环"继续删后续被点名的键——
三轮后 `unexpected_param 7 → 0`、`binds 155 → 162`。

**随后聚合被删的值才发现其中不只是开关**：`calendar_review_by_market` 带着逐交易所的
已复核日历证据（覆盖区间、官方规则/公告 URL、`verification: official_exchange_primary_source`、
工程发布截止时刻、以及"官方日历未完整/临时休市未知"的如实披露），`trading_days_by_market`
是每个市场 **240 个交易日**的完整列表；另有 `end_date=20991231`、`start_date=19000101`、
`overlap_days=7`、`source_timeout_seconds=45`、`sleep_seconds=0`、`source=auto` 这类**范围/超时/节流意图**。

用最早那份 69 行 before-image 逐行按 `id` 原样写回（`CAST(%s AS JSON)`）：**20 行恢复**。
复核：armed 里 `_ingest_mode` 回到 20、`trading_days_by_market` 回到 5 行；
重跑普查得 `binds 155 / unexpected_param 7 (_ingest_mode)`——**与实验前逐字一致，净变化为零**。

两个会让这类操作**静默失败**的技术点：

* `parameters` 是 **JSON 列**，`WHERE parameters = '{"…"}'` 永远不匹配（JSON 值对字符串），
  before-image 守卫必须写 `parameters = CAST(%s AS JSON)`；第一次 `--apply` 正是因此
  `rowcount=0` 触发中止、整批回滚——守卫救了一次。
* `LIKE '%key%'` 会把 **inactive** 行也算进来（69 行 vs armed 20 行），
  清理前必须先决定是否包含停用行。

正确的处置不由本机静默完成：`_ingest_mode` 单独删大概率安全（无消费者、且是普查唯一点名的键），
但仍会改变任务行为；日历两键是**数据**，应让脚本显式接收或迁到日历表；范围/超时类键要么脚本支持，
要么属主明确宣布作废。

## 与验收的关系

* 以上四条都不改变任何 AC 判定：AC01 仍 PARTIAL、AC11 仍 0/1057 已分派（分子 312/1048 为运行证据）、
  AC05/AC10/AC14 仍未达判据。
* 第 1、3 条把两个待定决策变成可执行的一步（加 stub；带 `--registration-export` 签字）；
  第 2 条把 AC11 的"未验面"从 886 收窄为 60 + 89，并指出第二跳是可核对的；
  第 4 条是一次被完整撤回的操作与一条方法学教训（先看值，再决定删不删）。
