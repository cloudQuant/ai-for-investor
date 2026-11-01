# 第六批 HTTP 边界与进程隔离切片

日期：2026-10-27（Asia/Shanghai）。本批在第五批冻结后继续推进，范围限于受治理HTTP请求预算、股票日线子进程边界和worker资源清理测试。各项结果按各自提交、命令与隔离边界记录；不得把局部离线验证提升为真实源、全历史或生产验收。

## 工作流与所有权

| 工作流 | 范围 | 交付 / 验收边界 |
| --- | --- | --- |
| HTTP与请求预算 | `opendata/data/http_client.py`、`opendata/data/request_budget.py`；统一有界超时、响应体预算、redirect/EOF/错误处理、host-slot deadline和诊断脱敏 | 保持HTTP与budget各自90%覆盖门槛及既有排除；新增离线边界测试使用固定transport/fixture，不访问真实上游。最终结果以root在精确source commit上的显式11文件命令和覆盖率JSON为准 |
| HTTP边界测试 | `tests/test_http_client_boundaries.py`、`tests/test_request_budget_boundaries.py`及既有HTTP治理回归 | 检查预算、重定向、读取终止、错误映射与安全诊断；测试隔离审查限定目标，不将已知默认Engine guard称作通用沙箱 |
| 股票日线进程切片 | 独立分支 `codex/od204-wave6-stock-process`，涉及 `opendata/data/providers/akshare/stock_daily_wire.py`、`opendata/pipeline/stock_daily_job.py`及专用测试 | 子进程仅接收规范化symbol/date；新建child-local `UNKNOWN`授权，严格校验IPC并在父端捕获和标准化。默认disabled、未经生产接线；真实上游权限、响应、Popen成功与历史完整性均不由合成测试证明 |
| worker资源清理测试 | `tests/test_reviewed_worker.py` | 对测试自有Engine/临时SQLite清理路径运行回归，并把`ResourceWarning`及pytest unraisable warning作为错误；仅验证测试路径，不等于生产worker已有shutdown API |
| 总集成和归档 | root持有共享合同、迁移序列、census、最终代码集成、合并回归和归档 | 任何工作流不得自行变更共享合同或生产激活边界。最终组合、静态/A2、私有与公开归档收据分别记录；整仓`make gate`仍单独报告 |

## 本批验收顺序

1. 先审查HTTP期限、响应上限、redirect和EOF语义，以及错误信息不泄露敏感URL参数；保留固定测试环境与准确测试文件清单。
2. 对HTTP与request-budget边界运行明确列出的离线测试，并分别和合计核对覆盖率。不得靠降低阈值、增加新排除行或把未选中的integration测试计作通过来取得通过状态。
3. 单独验证worker测试资源释放。结果不能外推到生产shutdown、任意Engine、数据库隔离或文件系统沙箱。
4. 对股票进程切片先核实静态合同与权限隔离，再由root决定是否运行经过审查的显式测试allowlist；不得执行会访问真实source、生产数据库或未经授权Popen路径的命令。
5. root完成组合测试、静态门禁/A2和私有证据归档后，按最终source SHA更新 [WAVE6_STATUS.md](WAVE6_STATUS.md)。缺任一证据时保留为未完成，不借用第五批结果。

## 不在本批关闭的事项

真实Eastmoney及其他source rights/retention、上市起点与自然交易日历、逐instrument全历史head/interior/tail、完整消费者接线、1,103个既有任务导入、生产角色/CLI/UI、自然周期、外部备份恢复、单写者切换和部署仍开放。股票进程worker默认disabled且权限状态为UNKNOWN；测试生成的合成授权不构成真实数据许可。范围、任务分母和生产变更门槛不因本批变化。
