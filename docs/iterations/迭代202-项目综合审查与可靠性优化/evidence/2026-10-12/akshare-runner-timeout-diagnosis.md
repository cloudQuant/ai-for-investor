# AkShare runner timeout diagnosis

> Git 交付时仅将本机链接转换为仓库相对链接；历史判断和复验结论保持不变。[原始记录（gzip）](akshare-runner-timeout-diagnosis.original.md.gz) 保留修改前字节与哈希。

**状态：** 已确认本轮 Linux 回归容器内的 hang 路径；未重跑测试。本文是只读证据记录，不修改 AkShare 清理算法。证据仅覆盖 AkShare subprocess runner 与 pytest 超时行为，不对 OpenData provider 或其未来接入范围作判断。

## 结论

卡住的 node 是 `test_akshare_runner_success_reaps_descendants_before_return`。其测试 runner fork 出来的子进程已被杀死，但在没有 init/reaper 的回归容器中成为 PID 1 名下的 zombie。应用清理代码回收直接 runner 后，仍通过 `killpg(pgid, 0)` 等待整个进程组消失；zombie 仍留在进程表和原 PGID 中，轮询没有结束条件，因而事件循环一直等待。

测试容器的 PID 1 是 `sleep infinity`，Docker `HostConfig.Init` 检查结果为 `<nil>`。现有现场同时显示 runner PID/PGID/SID `2056`，其后代 PID `2057` 的 PPID 已变为 `1`、状态为 `Z`。这与测试写出的 runner PID、ready marker 相符，且没有写出 `success-child-survived` marker。证据支持“后代已退出但未被收养者回收”，而不是后代仍在运行。

## 代码与日志证据

测试在 [test_akshare_runner_provider.py:570](../../../../../src/backend/tests/market_data_platform/test_akshare_runner_provider.py#L570) 标记 POSIX process-group 场景；[test_akshare_runner_provider.py:586](../../../../../src/backend/tests/market_data_platform/test_akshare_runner_provider.py#L586) 起的 fake runner fork 子进程，子进程先写 `success-child-ready`，延迟后才写 `success-child-survived`，测试要求 provider 返回且 runner 已不存活，见 [test_akshare_runner_provider.py:616](../../../../../src/backend/tests/market_data_platform/test_akshare_runner_provider.py#L616)。现场 ready 文件存在、survived 文件不存在。

runner 由 `subprocess.Popen(..., start_new_session=True)` 启动，见 [akshare_provider.py:1362](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1362)。收到 receipt 后，`execute` 的 `finally` 调用 `_cleanup_owned_runner_group`，见 [akshare_provider.py:1447](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1447) 和 [akshare_provider.py:1460](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1460)。清理先向组发送 `SIGKILL`，再 `waitpid` 回收直接 runner，见 [akshare_provider.py:1134](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1134) 与 [akshare_provider.py:1228](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1228)。之后 [akshare_provider.py:1296](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1296) 调用 `_confirm_runner_group_terminated`；该函数在 [akshare_provider.py:1171](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1171) 至 [akshare_provider.py:1188](../../../../../src/backend/app/services/market_data/akshare_provider.py#L1188) 无限执行 `os.killpg(process_group_id, 0)` 探测，只在收到 `ProcessLookupError` 时返回，没有识别 zombie 或有限等待分支。

现存回归日志按 collection 顺序记录到 `test_akshare_runner_provider.py`：前两个 `F` 分别对应 receipt normalization 用例和 protocol-version tamper 用例；后续进度显示 25 个节点已有结果，随后打印 Timeout。第 26 个节点正是上述 descendant-reap 测试，collection 记录见 [backend-collection-v2-linux-parent.txt:558（本地原件索引）](../../EVIDENCE_MANIFEST.json)，进度与 timeout 栈见 [backend-full-v2-linux-parent.txt:78](backend-full-v2-linux-parent.txt#L78) 和 [backend-full-v2-linux-parent.txt:79](backend-full-v2-linux-parent.txt#L79)。主线程栈落在 asyncio selector 的 `select()`，见 [backend-full-v2-linux-parent.txt:222](backend-full-v2-linux-parent.txt#L222) 至 [backend-full-v2-linux-parent.txt:233](backend-full-v2-linux-parent.txt#L233)，与清理函数每 5ms `asyncio.sleep()` 的持续轮询相符。

pytest 配置文件 [src/backend/tests/pytest.ini:21](../../../../../src/backend/tests/pytest.ini#L21) 至 [src/backend/tests/pytest.ini:22](../../../../../src/backend/tests/pytest.ini#L22) 默认 `timeout=30`、`timeout_method=thread`。本轮命令把 timeout 覆盖为 180 秒，但没有覆盖 method；日志确认 `timeout: 180.0s`、`timeout method: thread`、`timeout func_only: False`，见 [backend-full-v2-linux-parent.txt:6](backend-full-v2-linux-parent.txt#L6) 至 [backend-full-v2-linux-parent.txt:8](backend-full-v2-linux-parent.txt#L8)。容器所装 `pytest-timeout` 的 `timeout_timer` 在转储栈后执行 `os._exit(1)`（容器内 `/usr/local/lib/python3.11/site-packages/pytest_timeout.py:505-542`），所以这不是仅将当前用例标红并继续：pytest 进程直接退出，未完成 session finish，JUnit 文件也未成功复制；receipt 的 `junit_copy_exit_code` 为 1，见 [backend-full-v2-linux-parent-receipt.json:31](backend-full-v2-linux-parent-receipt.json#L31) 至 [backend-full-v2-linux-parent-receipt.json:47](backend-full-v2-linux-parent-receipt.json#L47)。

两个先行 `F` 的 nodeid 可由进度符号和 collection 顺序定位，但该日志没有保留 pytest failure summary/JUnit，不能据此确认它们的 assertion、异常或根因。应以单独定向诊断产生的完整 traceback 为准，不把它们归因于本节 zombie 问题。

## 测试容器与部署配置的边界

本轮回归容器的只读检查结果：`docker inspect` 的 `.HostConfig.Init` 为 `<nil>`，容器 PID 1 是 `sleep infinity`。Docker inspect 的 init 启用项位于 `HostConfig.Init`；`.Config.Init` 并非该容器对象中的字段。回归容器 PID 1 不负责回收被 orphan 的进程，正是本次现场条件。

仓库提供的生产 Compose 路径也没有声明 `init: true`：部署脚本默认选择 `docker/docker-compose.yml` 与 `docker/compose/prod.yml`，见 [docker_deploy.sh:70](../../../../../scripts/ops/docker_deploy.sh#L70) 至 [docker_deploy.sh:72](../../../../../scripts/ops/docker_deploy.sh#L72)，并在 [docker_deploy.sh:406](../../../../../scripts/ops/docker_deploy.sh#L406) 组合文件、启动 backend，见 [docker_deploy.sh:425](../../../../../scripts/ops/docker_deploy.sh#L425) 至 [docker_deploy.sh:426](../../../../../scripts/ops/docker_deploy.sh#L426)。生产 backend 定义位于 [prod.yml:54](../../../../../docker/compose/prod.yml#L54) 至 [prod.yml:118](../../../../../docker/compose/prod.yml#L118)，没有 `init` 声明；backend 镜像的启动命令是 `sh -c gunicorn ...`，见 [Dockerfile:57](../../../../../src/backend/Dockerfile#L57) 至 [Dockerfile:60](../../../../../src/backend/Dockerfile#L60)，也没有指定 tini/init 入口。

因此，**按仓库当前生产 Compose 配置启动且没有部署侧覆盖时，不能假定容器有 init reaper；同类 orphan-zombie 条件有可能出现。** 这只是配置级风险判断，不证明某个实际生产容器已复现该 hang：本次未检查远端或线上容器的 PID 1/`HostConfig.Init`，且生产 PID 1 进程与回归容器中的 `sleep infinity` 不同。部署平台若另外启用 init/subreaper，结论会不同。仓库中的 trusted research explorer/holdout Compose overlay 显式设有 `init: true`，见 [trusted-research-explorer.yml:25](../../../../../docker/compose/trusted-research-explorer.yml#L25) 和 [trusted-research-holdout.yml:25](../../../../../docker/compose/trusted-research-holdout.yml#L25)；它们不是生产 backend Compose 配置，不能作为生产已启用 init 的证据。

## 建议的验证边界

当前可行的测试环境验收修复是以 Docker `--init` 启动回归容器（Compose 等价项为服务级 `init: true`），由 init 进程作为真正 PID 1 收养并回收 orphan。随后重跑 descendant-reap 用例，保留原来的“后代已退出、runner 已 reaped、清理返回”断言，并检查 zombie 不再残留。不要通过把 zombie 视为已 reaped、删除进程组清理断言或延长产品超时来掩盖这一容器前提。

生产配置是否也需要 `init: true` 应另行按实际部署容器验证：只读记录 `.HostConfig.Init`、PID 1 与其子进程回收行为，再决定部署配置验收。此记录未改 Compose、Dockerfile、AkShare 算法或 OpenData 接入范围，也未运行测试或服务。

## 主审补充复验

2026-10-12 19:21，原无 init 容器的 signal timeout 定向诊断完成：8 passed / 1 failed，187.18 秒。两个早前失败点及协议篡改参数全部通过；后代回收用例仍触发 180 秒 watchdog。保留 [定向诊断日志](akshare-runner-failures-v3-parent.txt) 和 [JUnit](akshare-runner-failures-v3-parent.xml)。主审随后将相同受测容器文件系统制作临时测试快照，并以 `--init --network none` 启动新验收容器；未修改产品清理算法，运行结果另记。前述部署配置风险为修复前静态证据，后续 Compose 的 init 改动和实测不改写此历史记录。
