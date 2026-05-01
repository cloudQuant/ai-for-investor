# Seed Content and Editorial Templates Package

## Editorial Guardrails

### Allowed framing

- Educational explanation of open-source tools, concepts, and workflows.
- Research-demo walkthroughs that clearly state assumptions and limitations.
- Reproducibility notes, dependency notes, data-source caveats, and licensing notes.
- Risk-methodology education, including overfitting, look-ahead bias, data leakage, survivorship bias, transaction costs, liquidity, and operational risk.

### Prohibited framing

- Personalized investment advice.
- Return promises, win-rate promises, alpha promises, or guaranteed profitability language.
- Direct buy/sell/hold recommendations for any security, token, sector, or portfolio.
- Broker, exchange, custody, account-binding, or real-funds trading instructions.
- Claims that a demo result is production-ready without independent validation.

### Required disclaimer block

> 本文仅用于教育与研究讨论，不构成投资建议、交易建议或收益承诺。文中项目、数据、回测和示例可能存在偏差、延迟、错误或不适用于真实市场。任何投资或交易决策都应由读者自行判断并承担风险。

## Project Review Template

### Front Matter

```yaml
title: "[Project Name] 项目解读：一句话说明研究价值"
summary: "用 1-2 句话说明项目用途、适合读者和主要风险边界。"
category: "project-review"
tags:
  - ai-investing
  - open-source
  - research-demo
risk_level: "research-only"
license_to_check: "TBD"
repo_url: "https://github.com/..."
```

### 1. 项目一句话定位

- **项目名称:** `[Project Name]`
- **仓库:** `[owner/repo]`
- **适合读者:** `[AI/量化学习者、量化开发者、内容创作者等]`
- **研究用途:** `[数据分析、回测、Agent 投研、风险分析、可视化等]`
- **明确边界:** 这是研究/学习材料，不是可直接实盘的投资系统。

### 2. Use Case / 使用场景

- **主要问题:** 这个项目试图解决什么问题？
- **典型输入:** 数据、配置、模型、Notebook、API 或命令行入口。
- **典型输出:** 报告、图表、回测结果、特征、模型信号或解释文本。
- **不适合场景:** 明确说明哪些场景不应使用该项目。

### 3. Repository Signal / 仓库信号

- **Stars / Forks / Watchers:** 记录观察日期和数值。
- **最近维护:** 最近 commit、release、issue 活跃度。
- **文档质量:** README、示例、API 文档、教程是否足够。
- **社区风险:** 是否存在大量未处理 issue、过时依赖、争议性声明。
- **供应链初筛:** 是否需要容器隔离、是否下载外部模型/数据、是否请求敏感权限。

### 4. Setup Notes / 复现与部署笔记

- **环境:** Python/Node/Docker/GPU/CPU 要求。
- **最小运行路径:** 仅描述研究 demo 或只读分析路径。
- **数据要求:** 数据来源、许可、延迟、质量风险。
- **常见失败点:** 安装、依赖、API key、系统资源、版本冲突。
- **本平台接入建议:** 可做内容解读、可做工具卡片、是否适合沙箱 demo。

### 5. Risk Reminder / 风险提醒

- **研究风险:** 过拟合、数据泄漏、样本偏差、指标误读。
- **市场风险:** 历史表现不代表未来，交易成本和流动性可能改变结果。
- **工程风险:** 依赖安全、模型漂移、错误处理、监控缺失。
- **合规边界:** 不构成投资建议，不提供个性化资产配置或交易指令。

### 6. License Notes / 许可证笔记

- **许可证类型:** `[MIT/Apache-2.0/GPL/AGPL/Unknown]`
- **商用/分发限制:** 待核查。
- **模型/数据许可证:** 单独核查。
- **内容引用要求:** 链接原仓库、引用原作者、标注观察日期。

### 7. Editorial Verdict / 编辑结论

- **推荐内容形态:** `[项目解读 / 安装教程 / 风险教育 / 工具 Demo / 暂不收录]`
- **可信度:** `[high / medium / low]`
- **下一步:** `[补测试、补许可证核查、联系作者、做对比文章等]`

### 8. Disclaimer

粘贴必备免责声明。

## Weekly Report Template

### Front Matter

```yaml
title: "AI 投资与量化开源周报 YYYY-WW"
summary: "本周值得关注的项目、教程、风险提醒和社区讨论。"
category: "weekly-report"
tags:
  - weekly-report
  - ai-investing
  - open-source
risk_level: "education-only"
```

### 1. 本周项目亮点

| 项目 | 类型 | 为什么值得看 | 风险边界 |
|---|---|---|---|
| `[Project]` | `[Agent/量化/数据/风险]` | `[新增功能、热度、教程价值]` | `[研究演示/依赖复杂/许可证待核查]` |

### 2. 本周更新摘要

- **仓库更新:** 重要 release、commit、issue、PR。
- **论文/文章:** 与 AI 投研、量化、风险方法相关的材料。
- **工具体验:** 本周尝试复现的 demo 和失败点。
- **社区信号:** 读者评论、论坛讨论、常见问题。

### 3. 推荐阅读

- **入门:** 适合新读者理解背景的资料。
- **实践:** 可复现教程或示例。
- **风险:** 关于回测陷阱、数据质量、合规边界的资料。

### 4. 讨论问题

- 这个项目最适合做研究 demo 还是长期工具？
- 哪些结果可能来自数据泄漏或过拟合？
- 许可证和数据源是否允许公开复现？
- 如果做沙箱体验，应该禁止哪些能力？

### 5. 下周观察清单

- `[Project / Topic]` — 观察原因。
- `[Project / Topic]` — 待核查风险。

### 6. Disclaimer

粘贴必备免责声明。

## Initial Seed Content List

| Priority | Topic | Draft Title | Content Type | Required Angle | Compliance Notes |
|---:|---|---|---|---|---|
| 1 | TradingAgents | `TradingAgents 项目解读：多智能体投研框架能做什么，不能做什么` | Project review | LLM Agent 投研流程、角色分工、演示边界 | 强调研究演示，不评价可盈利性，不给交易建议 |
| 2 | Qlib | `Qlib 入门路线：AI 量化研究平台的模块、数据和回测陷阱` | Tutorial / project review | 数据、模型、回测、工作流 | 强调回测偏差、交易成本、数据许可 |
| 3 | OpenBB | `OpenBB 项目解读：开源金融数据终端如何服务 AI Agent 研究` | Project review | 数据入口、分析终端、Agent 集成可能性 | 不推荐具体资产，不绕过数据许可 |
| 4 | QuantStats | `QuantStats 风险报告入门：如何读懂收益曲线背后的风险指标` | Risk methodology | 最大回撤、夏普、波动、暴露解释 | 明确指标教育，不用作投资决策依据 |
| 5 | vectorbt | `vectorbt 研究笔记：向量化回测为什么快，以及为什么仍会错` | Tutorial / risk education | 向量化回测、参数扫描、过拟合风险 | 强调研究工具，不承诺策略有效 |
| 6 | Risk methodology | `AI 量化内容的风险检查清单：从数据泄漏到实盘不可复现` | Risk methodology | 通用风险框架 | 作为全站合规与内容质量基准 |
| 7 | TradingAgents + Qlib | `Agent 投研和传统量化平台如何互补：TradingAgents 与 Qlib 的边界比较` | Comparative guide | Agent 解释与量化验证的差异 | 不排名投资优劣，只比较研究流程 |
| 8 | OpenBB + vectorbt | `从数据到回测：OpenBB 和 vectorbt 的研究链路示例` | Workflow guide | 数据获取、清洗、回测演示 | 明确示例数据和限制，不给实盘路径 |

## Editorial Checklist Before Publishing

- [ ] 标题没有收益承诺、荐股暗示或夸张营销词。
- [ ] 摘要说明教育/研究用途。
- [ ] 正文包含必备免责声明。
- [ ] 项目 review 包含 use case、repository signal、setup notes、risk reminder、license notes。
- [ ] 周报包含 project highlights、updates、recommended readings、discussion prompts、disclaimer。
- [ ] 文章区分 research demo、paper result、backtest result、production system。
- [ ] 没有个性化资产配置、买卖点、仓位建议或真实交易 API 指引。
- [ ] 所有仓库、论文、数据源均标注来源和观察日期。
- [ ] 许可证和数据使用限制没有被忽略。
- [ ] 如果涉及工具运行，默认要求沙箱、资源限制和人工审核。
