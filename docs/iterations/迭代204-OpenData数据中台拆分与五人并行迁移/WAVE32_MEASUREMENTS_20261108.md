# 迭代 204 — Wave 32 实测（2026-11-08）

本轮起点是一个具体事件：dev 头 `7c8f6f2f12f9ac325a6a1608f340b4ea8c8a7b92` 的 CI 是红的。
本节记三件事：那条红实际是什么、OpenData 侧两行 `IN PROGRESS` 现在能否用 CI 自己的读数关掉、
以及本轮我自己读错并被推翻的一次。

**不改写任何 AC 结论。** AC13 仍 NOT_RUN，AC14 仍按小时 accrual，AC11 分子仍 318/1048。

---

## 1. dev 头那条红：门禁把"二进制没下来"报成"扫描失败"

run `42472229710` 27 个作业里唯一红的是 `Security - Secret Scan (177 §D)`（作业 `128705525478`），
启动 14 s 后 exit 2。作业日志尾部：

```
curl: (56) Connection died, tried 5 times before giving up
tar: Error is not recoverable: exiting now
##[error]Process completed with exit code 2.
```

它前一步 `Validate audited gitleaks history baseline` 已经打印
`Gitleaks history baseline check passed (accepted=281, unresolved=0, blocking_ready=true)`。
仓库里其它 26 个作业（py3.11/3.12 单测、四个 mypy ratchet 子集、前端五成员、集成、E2E）全绿。
原样 rerun 那一个作业（attempt 2，作业 `128754894980`）不改任何东西就 `completed success`。

分母（不是轶事）：仪器对最近 20 个 dev `CI - Quality Checks` run 逐个取
`Security - Secret Scan (177 §D)` 的**最新 attempt**，19 个为 success，第 20 个就是本头——它的最新
attempt 也是 success，但那是 rerun（`128754894980`），首尝试 `128705525478` 失败。
因此这句话能撑住的是"这 19 个 run 记录在案的是绿"，**不能**据此断言它们从未失败过：要断言
"首尝试"必须逐 run 取 attempt 列表，本轮没有做，所以不这么写。
整体 conclusion 为 failure 的 `801a4efa143 / f9a62106247 / 96741b8af8b / 3325626f969` 四个 run，
该成员同样绿——红在别的作业。

处置 = PR #331（下载先落盘再解包 + `--fail --retry` + `gitleaks_version` 第一次变成判据 +
`scripts/ci/tests/test_gitleaks_install_step.py` 6 条回归 + loopback 执行 workflow 原文的仪器）。

## 2. OpenData：判据半区两行改用 CI 自己的读数

### 2.1 台账棘轮的当前真实形状（dev `c02b136ab5`）

一次 dev push run 的 `gate-log` 工件（run `42396841706`，工件 `13585551963`，78,673 行）打印：

```
- 反事实面：130/130 个探针走到了判定，952 条 break 各被施加一次、每条都要求把干净读数打回 gap
- 台账↔读数：agrees=122, unflipped=0, open=0, deferred=3, stale-proof=5（共 130 格有读数）
  红格子 AC-11|04、AC-16|05、AC-16|06、AC-1|08、AC-5|03
- deferred（时刻面，等工作树干净再判）：AC-17|03、AC-17|06、AC-1|10
- 棘轮：基线钉 8 条存量 finding，本遍命中 5 条（deferred 3 格等干净树再判）
OK: 130 个条目级判定在门禁里跑了一遍（1317.7 s）；…六面全过。
===== gate: PASSED =====
```

钉住的 8 格（`origin/dev:docs/quality/acceptance-gate-ratchet.json` 的键，与 CI 工件逐字节相同）：
`AC-1|08, AC-1|10, AC-11|04, AC-16|05, AC-16|06, AC-17|03, AC-17|06, AC-5|03`；
`5 stale-proof + 3 deferred = 8` 与文件一致。

**AC-5|07 为什么不在账上**：同一份日志里它是 `VERDICT AC-5|07: proven`——台账与探针现在同意，
没有 finding 可钉。它曾在 11-05 把主干打红（见 2.3），那条红是被**修掉**的，不是被静音的。
这正是棘轮设计要的形状。

### 2.2 `#188` 那一行（AC-17|08 自指面，判据本身）可以关掉，且证据在 CI 侧

行 246 的保留条件是"入账必须等 CI 的 `--sync-ratchet`"。三条 CI 侧事实：

1. #188（OD `0e5f1f33c2`，merged 2026-11-04T12:50:34Z）对 `acceptance-gate-ratchet.json` 的
   diff **只删一个块**：`AC-17|08` 的 `stale-proof` 钉（sha `ca500c6f…`）——即旧判据那 11 个
   误报产出的存量。删完后剩 8 格。
2. `workflow_dispatch` run `42404291048`（`SYNC_ACCEPTANCE_RATCHET: true`，头 `c02b136ab5`）的作业
   `128498543878` 打印
   `wrote docs/quality/acceptance-gate-ratchet.json：judge 存量 0 条、stale-proof 5 条、deferred 按同样文本钉 3 条`，
   紧随其后的 `git --no-pager diff -- docs/quality/acceptance-gate-ratchet.json` **输出为空**；
   上传的工件与 `origin/dev` 上那个文件 sha256 相同（`9e57cf7ed44f43096da5b7c7f96954e0a60955fa9cbf664584788c1e3470307f`）。
   也就是说：**今天的钉集合就是 CI 自己算出来的**，包括 `AC-17|08` 不在里面这件事。
3. 反例判据本身在主干上执行：同一份 `gate-log` 里
   `tests/test_shell_audit_self_reference.py` 有 **35 条 distinct 用例，全部 PASSED，0 FAILED/ERROR**
   ——与 #188 自陈的"反例测试 35 passed"对上，但这次是 CI 的读数而不是笔记本的读数。

`AC-17|08` 在 `acceptance-probe-faces.json` 里只有 `moment_faces: ["index(ctx.tracked)"]`；
判据不再产出可钉存量，所以它不进棘轮——这是结论，不是缺账。

### 2.3 `#194` 那一行（quality gate 偶发红一条的真实位置）也可以关掉

行 249 说的是红来自 `_write_test_worker()` 生成的子脚本源码把 marker 写成"存在但为空"，
父进程 `int(read_text())` 报 `ValueError: invalid literal for int() with base 10: ''`。
#194 merged 于 `051824bd38`（2026-11-05T00:07:35Z）。

仪器：把 #194 之后每一个产出 `gate-log` 的 dev run 的工件全部取回，数该签名出现次数。

| run | 头 | 结论 | `invalid literal for int` | `not properly terminated` | 红在哪条腿 |
|---|---|---|---|---|---|
| `41938977648` | `051824bd38` | success | 0 | 0 | — |
| `42093628720` | `1815e2a2a6` | failure | 0 | 0 | `acceptance-probe-check` |
| `42123183827` | `28607e186c` | success | 0 | 0 | — |
| `42160349563` | `f1a82bca86` | failure | 0 | 0 | `test-cov`（`test_sina_fzb_process_job.py::test_run_ledger_cancel_…` sqlalchemy Timeout） |
| `42224189357` | `02fb79a2fc` | success | 0 | 0 | — |
| `42241328622` | `34be0a1b9c` | failure | 0 | 0 | `acceptance-probe-check` |
| `42396841706` | `c02b136ab5` | success | 0 | 0 | — |

（另有两个 dispatch run `42253353600`、`42404291048` 不产 `gate-log`，只有
`acceptance-gate-ratchet` 工件，不在分母里。）

签名复发 **0/7**。三条红都能指名到别的腿，其中两条是棘轮正常工作：

- `1815e2a2a6` 红在 `棘轮新增（AC-5|07 / stale-proof）：基线没有这条存量…要么修掉，要么由 owner
  裁定后 --sync-ratchet 显式进账`；
- `34be0a1b9c` 红在 `棘轮新增（AC-1|08 / stale-proof）`——这一格后来正是走 owner 裁定的
  `--sync-ratchet` 显式进账路径关掉的（见 2.2 与 wave 31）。

`f1a82bca86` 那条 `test-cov` 的 sqlalchemy Timeout 属于行 242 记的 sina e2e 偶发族，与本行无关，
保持在那一行。

## 3. 本轮我读错并被自己的复核推翻的一次

先看 console 日志会得出一个错结论：run `42404291048` 的 `quality gate` 作业日志里 `passed`
出现 0 次、`test_shell_audit_self_reference` 出现 0 次，于是"OD 主干 CI 根本不跑 pytest、
#188 的 35 条反例只在笔记本上跑过"看起来成立。**这是错的**：

- 该 dispatch run 跑的是 `make security-bundle-rebuild` + `--sync-ratchet`，本来就不含 test 腿；
- dev **push** run 的作业有 22 个 step，其中一条把完整输出写进 `gate.log` 再上传，console 只打印
  `grep -aE '^===== gate:|^Required test coverage|^TOTAL|passed.*[0-9]+s$|Test failed'` 的过滤尾巴；
- 打开那个工件才有 78,673 行真日志，里面 35 条反例全部 PASSED，全量 test-cov 是
  `35620 passed, 243 skipped, 11 subtests passed in 1154.93s`。

教训按验收协议写死：**OD 侧一个作业的"跑没跑"只能从它的工件读，不能从 console 读**。
本节所有 OD 数字都来自工件本身。

## 4. 仍未闭合（保持诚实登记）

- `42160349563` 的 `test-cov` sqlalchemy Timeout（行 242 一族）没有被本轮任何改动触及。
- `gitleaks` 二进制在本机仍装不了（`github.com` 不可达，行 256）；#331 用 loopback 复现故障形状，
  没有复现扫描本身。
- 本机不可闭合的旧项不变：#257 集成税形状、#268 OD 重复触发、#269 源主机不可达、
  #266/#267 测量环境、#277 部署三件套机制、#260 的 7 个脚本、AC11 属主签字、
  AC13 单写者实现与七连测、#303 分支决定、#262 dependabot。

## 5. AFI 侧两条 accrual 的新读数（2026-11-08，只读）

两条都是同一个可复跑仪器在同一参数下的新读数，不是新判据。**都不构成任何 AC 判定闭合。**

### 5.1 AC11 运行时证据分子：318 → **417/1048**

```
python3 src/backend/scripts/task_param_audit.py --out-dir /tmp/it204/param-audit-1108 --env-file src/backend/.env
python3 src/backend/scripts/ops/ac11_runtime_evidence.py \
  --census /tmp/it204/param-audit-1108/task_param_bind_audit.json \
  --out-dir /tmp/it204/ac11-1108 --since 2026-11-05T14:00:00+00:00
```

普查 `tasks_audited=1048`、`registered_script_rows_audited=1066`、
`registered_script_rows_without_file=9`（0.79 s 跑完，session read-only）。读数
`as_of_utc = 2026-11-08T14:46:49+00:00`，`census_generated_at_utc = 2026-11-08T14:46:41+00:00`：

| outcome | 数量 |
|---|---|
| `completed_and_grew`（= 分子） | **417** |
| `completed_no_delta` | 139 |
| `failed_only` | 27 |
| `not_run` | 465 |
| 合计 | 1048 |

逐静态族：`accepts_var_kwargs 356 + 77 + 11 + 442`；`binds 61 + 62 + 9 + 23`；
`unexpected_param 0 + 0 + 7 + 0`——那 7 行仍然只有失败执行，与行 265 的"7 行全 MISMATCH"一致。
自 2026-11-07T19:02Z 的 318 以来 +99，全部来自采集器继续跑，不来自任何新裁定。

`assigned` 仍是属主的签字，仪器自己就拒绝替人算：报告里
`assigned.value = "not computed here"`，并写明
`runtime_evidenced != assigned: no human sign-off is implied by a growing run`。
AC11 的 6 行 `REUSE_PROVIDER` 签字面（`reviewer` + `reviewed_at_utc`）没有变化。

### 5.2 AC14 小时链：**19/48** 连续 completed，无断点

`evidence/2026-11-08-wave32/ac14_hourly_chain.py`（只读，`SET SESSION TRANSACTION READ ONLY`），
锚在 #316 部署瞬间 `2026-11-07T19:26:47Z`，task 1049 `3 * * * *`：

```
db clock: utc=2026-11-08 14:45:43  local=2026-11-08 22:45:43
executions since deploy: 19      （11-07 20Z … 11-08 14Z，每小时一个槽位）
consecutive completed hourly slots from 11-07 20Z onward = 19 (target 48, 18.8 h available)
first non-completed slot: none so far
```

19 个槽位全部 `completed`，0 个失败、0 个缺行。距 48 还差 29 个自然小时；按当前速率约 11-09
晚间到齐，但这条只能到时候再说，不能现在预告。表里第 299 行（"小时加密线 task 1049"）上一读数记的是
部署后连续 **10** 个槽位，本节把它推进为连续 **19** 个——**同一个"没有断点"的陈述，长度变了，
性质没变：既不是 AC14 判定，也不因为数变大就自动变成判定**。
