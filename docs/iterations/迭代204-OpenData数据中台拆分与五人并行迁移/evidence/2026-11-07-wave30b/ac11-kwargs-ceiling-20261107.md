# AC11 的 886 条 "accepts_var_kwargs" 不是"不可验"，是"只验了一层"

测量：2026-11-07T18:21Z，只读 AST 扫描 `app/data_fetch/scripts`（1108 个 .py），
脚本 `/tmp/it204/kwargs_ceiling.py`。

## 形状计数

| 类 | 数量 | 含义 |
|---|---|---|
| `no_kwargs_entrypoint` | 220 | 入口不接 `**kwargs`，不在本桶 |
| **`forwards_to_single_external_name`** | **827** | 把 `**kwargs` 转发给**唯一字面名**，几乎全是 `self.fetch_ak_data(...)` |
| `accepts_kwargs_but_forwards_nothing` | 52 | 收了 `**kwargs` 却不用——参数对行为无影响 |
| `forwards_to_multiple_callees` | 8 | 多处/多名转发，按形状不可判 |
| `forwards_to_single_local_callee` | 1 | 同文件内可直读签名 |

## 关键一步：那 827 条的"外部名"其实是**仓内的共享层**

`AkshareToMySql.fetch_ak_data(self, function_name, *args, **kwargs)`（`akshare_to_mysql.py:88`；
另一份 `akshare_provider.py:214` 同形）——它只 `pop("_call_timeout")`，其余 kwargs 原样转给
`getattr(ak, function_name)(*args, **kwargs)`。

因此这 827 条的准确状态是：
* **在驱动层 binds**：`fetch_ak_data` 自身接受任意关键字，所以"任务参数能否绑到入口"这一问在 AFI 侧是**成立的**，
  不是"无法判定"；
* **在源函数层未知**：会不会 TypeError 取决于被 `getattr(ak, …)` 取到的 akshare 函数签名。
  这正是运行时那 7 条 `_ingest_mode` / `source` / `end_date` 意外参数错误的形态——它们通过了驱动层，
  死在源函数层。

## 因此 AC11 的上界应该重写

原文（#284 的 caveat）："`accepts_var_kwargs` tasks are unverifiable statically, not proven safe"。
按本次形状分析，更准确的说法是：

* **可判的是 1057−60 = 997 条的两层问题**（827 单名转发 + 52 收了不用 + …），其中第二层对
  `source_function` 已解析的脚本（961 个 distinct）**可以**用已安装的 akshare 签名判定；
* **按形状不可判的只有 60 条**（52 收了不用 + 8 多转发），加上 `source_function` 未解析的 89 行。

也就是说，AC11 的"未验"面从"886 条黑箱"缩小为"**60 条形状不可判 + 89 行源函数未解析**"，
其余 827 条是"驱动层已绑定、源层待签名核对"——这是一个可执行的核对任务，不是先验不可知。

本文件只给形状与上界，**没有**把任何一条改判为 binds；真的改判需要把第二层逐条核对并留证。
