# 迭代204 — Wave 35：部署到 dev 头，与随后看到的两件事（2026-11-09）

本轮做了一件此前一直没做的事：**把运行树部署到当前 dev 头**（属主当日批准），并立刻用它检验
#333 的债券修复与 #332 的分页改动。结果一半符合预期、一半暴露了新问题。

---

## 1. 属主 2026-11-09 的三项决定

| 决定 | 内容 |
|---|---|
| 部署 | **批准**把服务部署到当前 dev 头（`eeebf5f2` / `3be018da`）。 |
| 迁移范围 | **先全量迁移**：把所有相关脚本先搬到 OpenData，**之后再修**；OpenData 暂时**允许破坏性开发**。 |
| 7 个任务的参数代差 | **实现这些参数**（接受 `_ingest_mode`、`start_date/end_date`、`overlap_days`、`source` 等），承认这是行为/范围变更。 |

这三条把此前挂在计划 §7 的 D1/D5 侧问题往前推了一步：迁移不再按「先 top-N」走，而是**全量搬运 + 后续修复**；
参数代差选「实现」而不是「过滤/清理」，因此 7 个任务的取数窗口与数据源会发生变化，需要按产品变更验证。

## 2. 部署 provenance（三件套：代码 + 迁移 + 重启）

| 项 | before | after |
|---|---|---|
| 运行树 HEAD | `ce97f53f5`（2026-11-08 16:22:49 CST 启动） | **`725fabacb`** |
| alembic current | `20261106_akshare_run_coordinator_claims` | 同（`current == heads`，**本次无迁移**） |
| 重启时刻 | — | **`2026-11-09T10:08:37Z`**（18:08:37 CST） |
| 服务状态 | active / NRestarts=0 | **active / Result=success / NRestarts=0** |
| 健康 | `/docs` 200 | **`/docs` 200、`/health` 200** |

本次上线的运行时变更只有两处：`#332` 分页（`api/akshare/tables.py`、`services/akshare/data.py`、
新增 `table_policies…table_pagination.py`）与 `#333` 债券控制器；其余是文档/CI/测试。
回滚路径：把运行树指回 `ce97f53f5` 并重启（本次未用到）。

## 3. 部署后立刻看到的：full-history-recovery 一半好、一半坏

unit `ai-for-investor-full-history-recovery` 的 timer 是 `OnCalendar=*:*:00`（每分钟），轮转顺序
`stock → crypto → bond → etf → option`。部署后两分钟内的两次运行：

**18:09:06 CST（stock 腿）—— 失败，但错误换了一个**

```
"asset": "stock", "status": "invalid_or_missing_cli_report", "exit_code": 2
stdout: {"status": "controller_internal_error", "error_type": "ValueError",
         "error": "The truth value of a Index is ambiguous. Use a.empty, a.bool(), a.item(), a.any() or a.all()."}
stderr: … 成功从 STOCK_INFO_A_CODE_NAME 获取 44513 行数据 …
run_dir: var/reports/iteration203/full-history-recovery-worker/runs/20261109T100907Z-f8dfdefcfab8
```

即：控制器在加载完 44,513 行股票清单后、进入批次前就抛了 **pandas Index 真值判断**错误，
被 `stock_full_history_controller.py:1209-1221` 的兜底捕获成 `controller_internal_error`（**不带 traceback**）。

**18:10:06 CST（crypto 腿）—— 成功**

```
"asset": "crypto", "status": "completed", "exit_code": 0,
"attention_required": false, "process_returncode": 0
Finished ai-for-investor-full-history-recovery.service
```

所以：**unit 的 `Result` 从 failed 变成 success**，crypto 腿完成；但 **stock 腿仍失败**，
且 failure 的形态与 #333 修的债券 `%` 完全不同。

## 4. 新登记的缺陷：stock 腿的 pandas Index 真值判断

- 现象与证据如上：`run.json`/`stdout.log`/`stderr.log` 在
  `var/reports/iteration203/full-history-recovery-worker/runs/20261109T100907Z-f8dfdefcfab8/`。
- 控制器 `stock_full_history_controller.py` **自身不 import pandas**，`resolve_exit_code()` 里的
  `present` 是 Python `set`，不是问题点；错误来自它调用的 warehouse/source 组件，
  在「加载完股票清单之后、产出 outcomes 之前」。
- **为什么本轮不修**：控制器把异常吞成一行 JSON（`:1209-1221`），没有 traceback；要拿到栈必须在
  `--apply` 下复现，而那是会写库的路径。属主当日方向是「**先迁 OpenData、之后再修**」，
  所以本轮只登记，不冒险在采集路径上试错。
- 下一步（可执行）：给该控制器加一个 `--reproduce`/`--dry-run` 的等价路径，或在兜底里记录
  `traceback.format_exc()`（不改行为、只增日志），再用一次 apply 运行取栈——**这是 S 级改动**。

## 5. 仍未验证的事

- **债券腿自部署后还没有轮到**：轮转顺序里 bond 在 crypto 之后，本轮观察窗口只到 crypto。
  因此「#333 让债券腿转绿」仍未证实；判定标准依旧是一次成功运行。
- stock 腿的缺陷与 #333 无关（错误类型不同），不要用 #333 合入来解释它。
- #325/#335 的文档 PR 仍在 CI（4 个长检查），未合入。
