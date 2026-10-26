# 第七批 管理员 reviewed-run 离线接线计划

计划日期：2026-10-27（Asia/Shanghai）。状态：**IN_PROGRESS（计划与隔离实现中，尚无第七批验收结果）**。本文件定义工作分工、依赖与root验收边界；不报告任何第七批测试、覆盖率、静态检查或整合门禁已通过。第五、六批的冻结结果分别见 [WAVE5_STATUS.md](WAVE5_STATUS.md) 与 [WAVE6_STATUS.md](WAVE6_STATUS.md)，不得借用作第七批通过证据。

## 目标与范围

在离线、显式注入的fixture环境中，建立一条管理员手工提交 reviewed run、查看安全状态并请求取消的薄纵向路径：独立管理员页面 → reviewed-run API → 已有 `RunDispatcher` / `RunService` / `RunLedger` 与 one-shot worker。新 `create_reviewed_app()` 工厂用于显式组装此能力；生产入口 `opendata.main` 的旧应用、旧路由和旧调度默认行为保持原样。本批不启用任何真实股票任务、生产角色或生产调度器。

运行路径只用测试专属的合成、启用 job 检查队列和失败/成功边界。生产股票日线候选继续默认 disabled，真实源权限仍为 UNKNOWN；页面不得提供其运行操作，也不得把观测到的行数、日期极值或局部coverage当成历史完整性证据。展示覆盖时保留 `UNKNOWN`，除非未来提供独立生命周期、日历及来源证据。

## 并行工作流与文件所有权

四条流在隔离分支按独占文件推进。共享DTO、错误/状态语义及其变更由root先协调；不同流不得各自定义不兼容的请求、响应或取消状态。

| 工作流 | 隔离分支 | 独占范围 | 交付边界 |
| --- | --- | --- | --- |
| 管理API | `codex/od204-wave7-admin-api` | `opendata/api/reviewed_runs.py`、`tests/test_reviewed_runs_api.py` | 只实现安全的job元数据、手工提交、状态读取和取消API；使用注入的catalog/dispatcher/ledger和JWT管理员依赖。测试不导入全局`main`或默认Engine。 |
| reviewed运行时 | `codex/od204-wave7-runtime` | 新增`opendata/pipeline/reviewed_runtime.py`及其专属运行时测试 | 将显式role plan、dispatcher和worker SPI组成可注入的一次性运行路径；不改`main.py`、`api/__init__.py`、CLI、settings或生产默认值。 |
| AFI管理员界面 | `codex/od204-wave7-frontend` | 新的reviewed-runs API/store/admin view及其测试；该流独占`frontend/src/router/index.ts`和`frontend/src/views/LayoutView.vue`的必要路由/菜单变更 | 新建独立管理员页和受`requiresAdmin`保护的入口；不改旧`TasksView`或其API/store，不在浏览器构造任意脚本、源参数或SQL。界面显示disabled候选、UNKNOWN覆盖和明确的提交/取消/轮询状态。 |
| 独立应用工厂 | `codex/od204-wave7-app` | 新增`create_reviewed_app()`工厂模块及其专属测试 | 只组合显式传入的reviewed依赖和受保护router，形成独立app对象；不得改写或替代legacy `main`，不得借工厂选择暗中关闭旧路由/写入口，也不得激活真实源。 |

root独占共享契约、最终OpenAPI及其pin/baseline、`opendata/main.py`、`opendata/api/__init__.py`、CLI/settings/默认值、旧路由与scheduler接线、任务矩阵和跨流集成。root负责合并顺序、最终审查、准确测试allowlist、静态/A2门禁和最终证据。若实现需要超出以上所有权的共享文件或改变旧入口，先交root裁定，不在并行分支扩范围。

## 契约与安全边界

建议的首版HTTP面保持狭窄：

- `GET /api/v1/reviewed/jobs`只返回允许公开给管理员的静态字段，如job/version/dataset/provider/model标识及enabled/reviewed状态；不返回handler路径、秘密、任意source配置或SQL。
- `POST /api/v1/reviewed/runs`只接受严格、有界的手工请求和显式幂等键，委托现有dispatch入口；disabled或unreviewed job必须在写ledger前拒绝。客户端重试相同幂等键应得到一致run身份，不能因网络重试重复提交。
- `GET /api/v1/reviewed/runs/{run_key}`仅序列化安全状态字段、允许的时间戳和安全错误码；不输出`job_snapshot_json`、原始异常文本或source响应。
- `POST /api/v1/reviewed/runs/{run_key}/cancel`区分已请求、已终态和不存在。运行中取消是协作式的，页面继续轮询权威状态，不声称请求发出即已停止。
- 首版页面持有本次返回的run key并轮询。现有`RunLedger`没有最近运行列表接口；本批不自行发明持久列表合同或未评审的查询语义。

管理员端点使用现有JWT `CurrentAdmin` 授权边界；普通用户应被拒绝，API key/一般principal不能替代JWT管理员身份。不得声称此功能“无需配置”：认证设置、管理员身份及应用依赖仍由宿主显式提供。审计若由宿主提供，必须能关联操作者、对象、动作和request ID，避免记录secret、原始job快照或不安全错误文本。

应用工厂和运行时只释放自己创建且明确拥有生命周期的资源。对调用方借入的Engine/连接不得在子应用或worker清理时擅自dispose/close；测试应使用隔离的临时SQLite和显式资源所有权。既有default-Engine guard只限制已覆盖的访问路径，不构成通用数据库、网络、进程或文件系统沙箱。若worker的borrowed Engine所有权和关闭时序不能明确验证，则保持显式注入与测试路径，不扩展生产生命周期承诺。

## 依赖顺序与任务矩阵锚点

1. root先冻结请求/响应DTO、路由前缀、幂等键、取消与错误语义、JWT身份边界及依赖注入点；API、运行时和工厂按同一合同并行开发。
2. API与reviewed运行时依赖现有Run dispatcher/ledger接口；独立工厂依赖已定义的运行时注入SPI。前端依赖冻结后的API字段与状态枚举，不以猜测字段驱动交互。
3. 各流提交后由root检查所有权、状态转换、身份边界、资源关闭与覆盖率，再按精确文件清单运行审核后的定向验证。OpenAPI pin、主应用或共享设置变更只由root集成。

本批推进与下列现有控制任务相关，但不自动关闭其父工作包或整行验收：

- [204-D04-01](SUBAGENT_TASKS.md)：管理员job/run/DQ/coverage接口、scope、审计及取消。
- [204-D04-02](SUBAGENT_TASKS.md)：运维界面和操作反馈；本批只做AFI独立reviewed-run页，不等于完整控制台。
- [204-D03-03](SUBAGENT_TASKS.md) 与 204-D02-04：统一提交入口及worker/ledger路径；本批单次fixture流不证明APScheduler、systemd、崩溃恢复或多进程竞争已完成。
- [204-A05-03](SUBAGENT_TASKS.md)：有界请求、权限/scope、错误语义；本批管理员手工API不等于全部导出/许可门禁。
- [204-A06-02](SUBAGENT_TASKS.md)：数据质量规则；`UNKNOWN`必须保持未知，本批不新增真实coverage证据或quality pass声明。

## root验收门禁

以下是待执行的验收方案，不是已运行结果。**仅root**可运行审核后的backend精确文件allowlist；不运行整仓pytest、广覆盖`--cov`或其他宽泛命令。allowlist至少覆盖现有reviewed CLI/worker/vertical-flow路径及本批API、runtime、factory测试；实际命令及环境由root在审查后记录。使用fixture与`tmp_path`自有SQLite/artifact目录，不读`.env`、默认Engine、生产库或真实源。应检查401、普通用户403、API key拒绝、管理员允许、disabled/unreviewed无ledger写入、重复幂等提交、安全状态序列化、取消状态，以及fixture成功/失败时publication fence行为。

覆盖率阈值沿用项目门槛：data/pipeline目标模块各自至少90%，API/app目标至少85%；不得靠降低阈值、增加覆盖排除或换成未执行文件取得通过。HTTP及其他现有覆盖排除不因本批自动增加。

Frontend仅在root审查后运行新API/view及router/layout相关的定向Vitest；按仓库已锁定依赖/CI配置核对，不能把依赖安装或生产构建当作测试通过。是否另跑build由root按审查结果决定。完整`make gate`应独立报告，当前计划不把它列作本批默认命令；未实际运行时明确标`NOT_RUN`。

root静态审查应覆盖JWT管理员依赖、响应字段白名单、秘密/异常脱敏、幂等冲突行为、取消状态准确性、资源所有权、legacy入口无变化和股票任务仍disabled。最终记录代码SHA、精确测试文件、覆盖报告、静态范围及未运行项；测试通过只确认相应离线合同，不提升为source/部署验收。

## 继续开放的事项

本批不改变任务分母与状态：87个控制任务仍为8项DEV_DONE、9项IN_PROGRESS、70项PLANNED；204-E03-01仍是部分消费接线。1,103个既有任务及其完整导入、1,066个候选脚本处置、真实source权利和历史保留、全历史head/interior/tail、所有AFI消费者迁移、自然发布周期、外部备份恢复、生产角色与单写者cutover均保持OPEN。库存数字不是就绪度或可迁移性的证明。

reviewed UI/API/factory处于离线开发计划阶段；即使定向fixture门禁以后通过，真实股票仍默认disabled、来源权限UNKNOWN，不能启动生产调度、上游抓取、warehouse写入或部署切换。父工作包验收、全历史完整性、部署及自然周期必须分别取得其定义要求的证据。
