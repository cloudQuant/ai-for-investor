# 采集平面最后 2 条 = dateutil stub：加 stub 的成本实测为零

测量时间：2026-11-07T18:20Z。环境：`/tmp/it204/venv-ci`（Python 3.11.15 + `config/requirements-dev.lock`，
pandas 3.0.3、无 pandas-stubs，与 CI 的 `Backend - Mypy Ratchet` 作业同构；该环境在 dev `0a4c5ab31`
上复现过 CI 的 101/1108）。树：`.wt-afi-tranche4`（dev `3325626f96` + PR #319 的 5 处修复）。

| 步骤 | collection | app |
|---|---|---|
| 装 `types-python-dateutil==2.9.0.20261104` 前 | **62** / 1108 | **0** / 757（baseline 0，delta +0） |
| 装后 | **60** / 1108 | **0** / 757（delta +0） |
| 卸载后复核 | **62** / 1108 | — |

结论：加 `types-python-dateutil` 的代价是**零**——collection 正好 −2（两条
`Library stubs not installed for "dateutil.relativedelta"`），blocking 的 app 面不新增任何错误。
与 `types-requests` 的实验（159→119，但 app 0→+6）形成对照：那一个有代价、需要先修 3 个 app 真错；
这一个没有代价。

处置：把 `types-python-dateutil` 加进 `config/requirements-dev.lock` 属于**依赖变更**（risk map 把依赖
判为 R3 级），因此不由本会话擅自改 lock；需要属主点头后由 `./scripts/ops/generate_lockfiles.sh`
重新生成并同 PR 提交。做完后，dev 在 #308/#314/#319 全部合入时collection 应读 **0**，
而不是 2。
