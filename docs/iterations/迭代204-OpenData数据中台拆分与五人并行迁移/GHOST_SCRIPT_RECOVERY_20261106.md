# 幽灵脚本恢复：七个只存在于字节码层的验收脚本（2026-11-06）

本文件记录迭代 204 的一次**恢复**动作及其**不完备性**。恢复不等于复原：本文档的首要目的，
是让后续读者能够判断"这七个文件到底是什么、离生产实际跑过的那个修订还有多远"。

结论先行：

- 七个脚本第一次进入版本控制（`git log --all -- <path>` 在恢复前对全部七个返回 **0 个提交**）。
- 它们的来源是审计备份树里的**归档副本**，不是生产源文件本身。
- **符号集一致不代表与生产实际运行的那个修订行为等价。**

---

## 1. 证据链

| 项 | 值 |
|----|----|
| 快照基线 | `origin/dev = 3e9f4a76e5a33a9493597d0e0fc4f77da87c6db0` |
| 工作树 | `/home/yun/Documents/.wt-afi-recover`（分支 `feature/afi-ghost-script-recovery`） |
| 字节码审计目录 | `/home/yun/afi204-evidence/2026-11-06-ghost-code-plane/`（`MANIFEST.tsv`、`CONTRACT_DUMP.txt`、`pyc/**`） |
| 幽灵总量 | 全仓 `app/`+`scripts/`+`alembic/` 下 5,629 个 `.pyc`，其中 **72 个**在任何位置都没有对应源文件 |
| 本次恢复 | 7 / 72；**其余 65 个磁盘上无可恢复副本** |
| 归档副本来源树 | `var/reports/iteration203/**` —— 该目录本身在仓库中是**未跟踪**的（`git status` 报 `?? var/`），即备份树不是 git 对象，只是一份文件拷贝 |
| 校验用解释器 | 仓库 venv `Python 3.13.5`（与 `.cpython-313.pyc` 的魔数一致；系统 `python3` 是 3.12，不能用于本校验） |

**三方哈希一致**：对全部七个，`活树 __pycache__ 里的 .pyc` == `审计目录 pyc/ 副本` == `MANIFEST.tsv` 第 3 列
的 sha256。也就是说审计清单描述的字节码，和这台机器上仍在生效的字节码，是同一批。

## 2. 校验方法

对每个文件：把归档 `.py` 用 `compile(src, path, "exec")` 编成模块码对象，把对应幽灵 `.pyc`
用 `marshal.loads(data[16:])` 解出模块码对象，**两侧用同一个抽取器**取顶层符号集
（模块体里的 `STORE_NAME`/`STORE_GLOBAL` 绑定名，排除双下划线名），再取 Jaccard：

```
score = |A ∩ B| / |A ∪ B|
```

同时解码 `.pyc` 头部的 `source_size` 与 `mtime` —— 这是**生产那份源文件**的字节数与时间戳，
比符号集更强的修订指纹，故一并记录。

## 3. 逐文件读数

| # | 目标路径（相对 `src/backend/`） | 归档源 | 行数（归档→提交） | 符号一致 | 幽灵 `.pyc` sha256（前 12） | `.pyc` 记录的源字节数 vs 归档 | `.pyc` mtime（UTC） |
|---|---|---|---|---|---|---|---|
| 1 | `scripts/cffex_option_range_controller.py` | `var/reports/iteration203/cffex-option-range-controller-v6-deployment/proposal/scripts/` | 1632→1633 | **1.0000**（88/88，无差集） | `54fde98a8171` | 66170 vs 66163（**差 7**） | 2026-10-20 02:32:28 |
| 2 | `scripts/cffex_option_native_range_verifier.py` | `.../cffex-option-range-controller-proposal-v2/proposal/src/backend/scripts/` | 558 | **1.0000**（42/42） | `f94deb4099ce` | 22051 vs 21952（**差 99**） | 2026-10-20 17:26:12 |
| 3 | `scripts/sina_index_daily_managed_acceptance.py` | `.../sina-index-managed-acceptance-root-review/frozen-final-v3/` | 2192 | **0.9922**（128 vs 129） | `7480c78aa475` | 94113 vs 93795（**差 318**） | 2026-10-20 12:30:19 |
| 4 | `scripts/probe_sina_index_daily_wire.py` | `.../sina-index-history-v2-root-review/frozen-proposal/files/src/backend/scripts/` | 290 | **1.0000**（32/32） | `a193d86ffd68` | 10036 vs 10036（**逐字节等长**） | 2026-10-20 02:34:00 |
| 5 | `scripts/deploy_sina_index_daily_history_schema.py` | 同上目录 | 200→201 | **1.0000**（23/23） | `4254814b713c` | 7529 vs 7529（**逐字节等长**） | 2026-10-20 02:40:11 |
| 6 | `scripts/deploy_forex_eastmoney_daily_history_schema.py` | `.../forex-canonical-foundation-deployment/proposal/src/backend/scripts/` | 259 | **1.0000**（23/23） | `d649677be569` | 10520 vs 10520（**逐字节等长**） | 2026-10-20 01:50:18 |
| 7 | `scripts/ops/cfets_daytime_managed_acceptance.py` | `.../fx-cfets-producer-v4-root-review/v3-before/scripts/ops/` | 1597 | **0.9703**（98 vs 101） | `46899f1901d7` | 72459 vs 68020（**差 4439**） | 2026-10-20 03:07:06 |

七项全部 ≥ 0.95，与前置测量一致，因此继续执行恢复。

### 已知的不一致（必须读，不要跳过）

- **#3** 生产字节码里有一个模块级常量 `DATABASE_DISPOSE_TIMEOUT_SECONDS`，归档副本**没有**。
- **#7** 生产字节码里有 `MAX_OBSERVATION_STORAGE_LAG_SECONDS`、`_datetime_precision_evidence`、
  `_observation_time_checks` 三个符号，归档副本**没有**，且源字节数差 4439 字节 —— 这是七个里偏差最大的一个，
  归档副本极可能是一个**较早的变体**（其目录名 `v3-before` 本身就说它是评审前的版本）。
- **#1 / #2** 符号集全等，但源字节数不等（差 7 / 99 字节）—— 即存在**不产生新顶层符号的改动**
  （注释、字符串、函数体内部）。符号一致在这里掩盖了实质差异。
- **#4 / #5 / #6** 只有这三个的源字节数与 `.pyc` 头部记录**完全相等**，加上符号集全等，
  是最接近"就是生产那一份"的三个。注意即便如此也没有哈希级证明（`.pyc` 不保存源哈希，
  且校验和是 16 位补码，弱）。

### 恢复内容与归档副本的偏差（本次唯一的编辑）

为通过 CI 的 `ruff check .`（`ci.yml:404`），对 **#1** 与 **#5** 各应用了一次 ruff 的 `I001` 自动修复
（仅重排/分隔 `sys.path` 引导之后的 `from ... import` 块）。已用 `diff` 确认改动**只落在导入块**，
未触及任何语句、常量或控制流；导入仍在 `sys.path.insert` 之后，语义不变。

| 文件 | 归档 sha256 | 提交后 sha256 |
|---|---|---|
| `scripts/cffex_option_range_controller.py` | `904138e8454c566749a8c29f81f82ab70ab70e50e787bc6915f380ec75a1b89e` | `7b2cda8e5e122fec7112618aa7c37097e87e7807bf1ded670fd8bcabe8960026` |
| `scripts/deploy_sina_index_daily_history_schema.py` | `8bb1084b8b0cafd9db8202e3db2b17cd2096410c69096dadfc8a29d6e614652d` | `21899ccd213d40631db7040794507ca9be8e4d8e840e1e65138b3628fea8bfbd` |

其余五个提交内容与其归档副本**逐字节相同**：

```
e7967869d783442502eee7ac981b354be922624f1b83d4940e8fea8d800d219a  scripts/cffex_option_native_range_verifier.py
7b49fc5474ab8bcf8679db42d92cce1ed593b3e4ca0daa4d6f9b1bbf9185dc49  scripts/sina_index_daily_managed_acceptance.py
07a3b6f22f62a9a336d2057c03b51969392bd45a52d67e2b4783ad021c3db82b  scripts/probe_sina_index_daily_wire.py
0d42c420df1ab06830ed7ddc7ca291054bf9b966fe302275a13b5e1d67eb2418  scripts/deploy_forex_eastmoney_daily_history_schema.py
50ba476377eaf0886650c2612d350e2e8151bda307363c8866335ab3ae7b0e65  scripts/ops/cfets_daytime_managed_acceptance.py
```

## 4. 关于"来源"的明示（本文件存在的理由）

**符号集一致不是行为等价。** 上述评分只证明"这个 `.py` 编译后绑定了与生产字节码相同的顶层名字集合"，
它不比较函数体、不比较常量取值、不比较默认参数、不比较 SQL 文本。因此：

1. 这七个文件来自审计备份树中的 `proposal/` 与 `v3-before/` **快照**——按定义，它们是**评审提案或评审前状态**，
   而不是"从生产取回的原件"。任何一个都可能是**变体（variant）**。
2. 因此，**不得**把这七个文件当作生产行为的可信复现依据，也不得据它们产生的结果主张 AC13/AC17 类验收。
   它们进入版本控制的价值在于：让这段代码从此**可被 diff、可被评审、可被删除**，而不是继续只存在于
   `__pycache__` 里。
3. 若要取得行为级等价，需要的是生产主机上原始 `.py` 的哈希，或与之等长的 `.pyc` 头部记录 + 全量反编译比对；
   本次**没有**做到这一点。#3 与 #7 已经明确证明存在缺失符号。
4. 一个具体的风险：**源文件一旦存在，就取代原字节码。** Python 会按 mtime/size 判定 `.pyc` 失效并依据 `.py` 重新编译，
   所以这段代码今后会以**恢复出的变体**执行，而不是以曾经执行的那一版执行。这比"没有源文件"更需要在评审时警惕。

## 5. 无法恢复的部分（缺口没有关闭）

- **65 / 72** 个幽灵模块在磁盘上找不到任何可恢复副本（完整名单见 `MANIFEST.tsv`）。
- 两个最吃重的模块**完全不可恢复**：`app/services/akshare/run_coordinator.py` 与
  `app/models/akshare_scheduler.py`。本次独立复核：
  - `git log --all -- <path>` → 0 个提交（含所有远端分支）；
  - `git fsck --lost-found` 得到 **176** 个悬空提交，逐个 `git ls-tree -r` 扫描，
    对 `run_coordinator.py` / `write_fence.py` / `models/akshare_scheduler.py` 命中 **0** 次。
  - 二者的契约只能从 `CONTRACT_DUMP.txt` 读到符号层：`AkshareRunCoordinator.try_claim/renew/complete/fail/cancel/
    cancel_unreturned_claim/recoverable_claims`、`RunLease`、`ClaimOutcome`，以及模型 `AkshareTaskRunClaim`、
    `AkshareSchedulerControl`。**行为语义不可恢复。**
- 依据既定原则：**不手写一个假的 claim/fence 层去让门禁闭嘴**。伪造的 `upgrade()` 或协调器会让每一个后续环境静默漂移。

## 6. 编译与导入结果

`python -m py_compile`（venv 3.13.5）：七个**全部通过**。

`import` 测试（venv，独立进程，`env -u DATABASE_URL`，cwd=`src/backend`）：

| 模块 | 结果 |
|---|---|
| `scripts.probe_sina_index_daily_wire` | IMPORT_OK |
| `scripts.deploy_forex_eastmoney_daily_history_schema` | IMPORT_OK |
| `scripts.cffex_option_native_range_verifier` | IMPORT_OK |
| `scripts.sina_index_daily_managed_acceptance` | IMPORT_OK |
| `scripts.ops.cfets_daytime_managed_acceptance` | IMPORT_OK |
| `scripts.deploy_sina_index_daily_history_schema` | IMPORT_FAIL `ModuleNotFoundError: app.data_fetch.providers.sina_index_history_schema` |
| `scripts.cffex_option_range_controller` | IMPORT_FAIL `ModuleNotFoundError: app.data_fetch.providers.cffex_option_history_source` |

两个失败都**不是**脚本自身的缺陷，而是它们依赖的 provider 模块仍是幽灵（见 §7）。

导入期副作用检查：用 AST 只检查**模块体的直接语句**（不下钻 `def`/`class` 体内），
七个文件在导入期**都不调用本文件里定义的函数**，也没有 `os.environ` 读取；可执行工作只发生在
`if __name__ == "__main__"` 守卫的 `main()` 里。因此这五个可导入的模块导入是安全的，
**没有发现"导入即执行工作"的缺陷**。（过程中第一版扫描器错误地下钻进了函数体，
一度报出 `os.environ["DATABASE_URL"]` 等"模块级调用"；已用直接 `grep` 证伪——七个文件里根本没有
 `os.environ` 引用。）

## 7. 这些恢复文件引用了哪些同样缺失的东西（26 处未解析引用 / 17 个唯一目标）

不为它们创建任何桩。此清单用于**量化剩余缺口**。

**仍是幽灵（只有字节码，没有源文件；在 72 项名单内）**

- `app.data_fetch.providers.cffex_option_history_source` ← `SOURCE`、`SOURCE_URL_TEMPLATE`、
  `normalize_date`、`parse_monthly_archive`（#1，模块级导入 ⇒ 直接 ImportError）
- `app.data_fetch.providers.sina_index_history_schema` ← `BUSINESS_KEY`、`EXPECTED_COLUMNS`、
  `EXPECTED_INDEX_NAMES`、`TARGET_TABLE`、`ZERO_DEFAULT_COLUMNS`、`validate_predeployed_schema`
  （#5，模块级导入 ⇒ 直接 ImportError）
- `app.data_fetch.scripts.options.daily.cffex_option_daily_history`（#1，运行期）
- `scripts.cffex_option_history_controller`（#1，模块级 `from scripts import ...`）

**在 git 里连字节码线索都没有对应模块的名字（即生产源比 `origin/dev` 更新，或该名字只活在别处）**

- `app.services.akshare.scheduler.get_akshare_scheduler` —— 被 #1、#3、#7 引用；已提交的
  `scheduler.py` 里只有 `class AkshareScheduler`，**没有**这个工厂函数。
- `app.services.akshare.scheduler._identity_key`、`._parameter_hash` —— 被 #1、#7 引用。
- `app.models.akshare_mgmt.AkshareTaskRunClaim` —— 被 #1、#3、#7 引用；全 `app/` 范围内
  `grep 'class AkshareTaskRunClaim'` 为空。该类实际只存在于**不可恢复**的幽灵
  `app/models/akshare_scheduler.py` 中（见 §5）。
- `app.data_fetch.scripts.common.hourly.fx_spot_quote.CFETS_MAIN_PAIRS` —— 被 #7 引用；
  该文件存在但没有这个名字。

含义：即使这七个脚本已经入库，**它们仍然跑不起来**。要跑通需要 (a) 两个 provider 幽灵可恢复，
且 (b) claim/scheduler 那一层（`AkshareTaskRunClaim` + `get_akshare_scheduler`）有真实来源——
而 (b) 恰恰是 §5 里判定完全不可恢复的部分。

## 8. provider 文件的入库是否改变活调度器的发现结果

**答：不会。** 依据代码路径（本次阅读，非推测）：

1. `app/services/akshare/interface_loader.py:58-68` `_discover_akshare_functions()` 做的是
   `import akshare as ak` 后遍历 `dir(ak)`——发现对象是**已安装的第三方 akshare 包**，
   与 `app/data_fetch/providers/` 目录毫无关系。
2. `app/data_fetch/providers/factory.py`：注册表 `_PROVIDER_REGISTRY` 只能通过显式调用
   `register_provider(source, cls)` 填充；`_auto_register()`（第 58-64 行）只导入
   `app.data_fetch.providers.akshare_to_mysql.AkshareToMySql` 这一个类。
3. 全 `app/` 范围不存在按目录发现 provider 的机制：`grep 'pkgutil\|iter_modules\|scandir\|listdir'`
   只有 `app/services/gateway/manual_ctp_proxy.py:225` 的 `os.listdir(app_support)`（与此无关）。
4. 活调度器取任务也是数据库驱动，不是文件系统驱动：`app/services/akshare/script.py:101`
   `select(DataScript)`，运行期解析在 `script.py:366-368`
   `importlib.import_module(str(interface.module_path or "akshare"))`——模块名来自
   `data_interfaces` 行的 `module_path` 字段。

所以，把 `forex_eastmoney_history.py` 或 `sina_index_history_schema.py` 放进目录，
**不会**让调度器多发现任何东西；两个 provider 文件日后可以安全入库（就"发现"这一维而言）。

需要保留的告诫是另一条：入库会**触发重新编译**，从而把当前正在生效的字节码换成恢复出的源。
因此"可以安全入库"仅指不改变发现面；对已经通过 `module_path` 指向这些模块的数据库行，
执行内容会从"曾经那一版"变成"这一版"。#3/#7 的偏差证明恢复源可能与生产修订不同——
provider 文件入库前应先做同样的 `.pyc` 头部 `source_size`/符号比对并记录结论。

## 9. 门禁

| 门禁 | 命令 | 结果 |
|---|---|---|
| 语法编译 | venv `python -m py_compile` ×7 | 7/7 通过 |
| Lint | `ruff check`（**0.16.2**，与 `ci.yml:397` 的 pin 一致；仓库 venv 内**没有** ruff 可执行文件，故用 `/tmp/ruff162` 里新装的 0.16.2；`/home/yun/anaconda3/bin/ruff` 0.14.11 也跑过，结论相同） | 修复后 All checks passed |
| Lint 基线 | 同一 ruff 扫 `scripts/` 去掉这七个 | All checks passed（即这 2 个 `I001` 完全由恢复文件带入，不是既有噪声） |
| 格式 | `ruff format --check` ×7 | 7 files already formatted |
| 大文件棘轮 | `python scripts/ci/large_file_ratchet.py` | `large_file_ratchet: passed`，exit 0 |
| 棘轮覆盖面 | 读 `large_file_ratchet.py:23` `SOURCE_ROOTS = (src/backend/app, src/frontend/src)` | **确认不扫 `src/backend/scripts/`**（非假设）；故 2192/1633/1597 行不受 `NEW_FILE_LINE_LIMIT=1000` 约束 |

未做：`mypy`（这七个文件按 `pyproject.toml:131-133` 的类型面是 opt-in，且 `scripts/` 不在 `app` 类型面内）；
未运行任何会连数据库或采集的脚本入口。

## 10. 下一步（属主裁定）

- 65 个剩余幽灵的处置：逐个给出"可恢复/不可恢复"判定，不可恢复的按 §5 原则**记录为不可复现**，
  而不是补写占位代码。
- `get_akshare_scheduler` 与 `AkshareTaskRunClaim` 是这七个脚本的运行前提，也是 AC13 的空洞所在；
  需要属主决定是"重写这一层并评审"还是"维持文档化的不可复现"。
- #7 偏差最大（缺 3 个符号、少 4439 字节），建议优先在生产主机上找原始 `.py` 或用反编译做行为比对。
