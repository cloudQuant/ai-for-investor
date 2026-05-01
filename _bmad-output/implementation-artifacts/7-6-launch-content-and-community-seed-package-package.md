# Launch Content and Community Seed Package

## Editorial Guardrails

All launch content is for AI trading and investing education, open-source research, reproducibility, and safe tool exploration. It must not provide personalized investment advice, return promises, buy/sell/hold instructions, broker or exchange account-binding guidance, real-funds trading workflows, or claims that demos are production-ready.

Required disclaimer for launch articles and weekly reports:

> 本内容仅供教育与研究讨论，不构成投资建议、交易建议或收益承诺。文中项目、工具、数据、回测和示例可能存在偏差、延迟、错误或不适用于真实市场。任何投资或交易决策都应由读者自行判断并承担风险。

## Homepage Selected Launch Content

| Slot | Title | Destination | Purpose | Status |
|---|---|---|---|---|
| Hero primary | AI 投资与量化开源研究导航 | `/open-source` | Direct new users to curated open-source project discovery. | ready |
| Hero secondary | 安全体验 AI 投研工具 Demo | `/tools` | Introduce sandboxed, reviewed tools with risk reminders. | ready |
| Featured article | TradingAgents 项目解读：多智能体投研框架能做什么，不能做什么 | `/blog/tradingagents-research-boundaries` | Anchor launch narrative around agentic research boundaries. | draft-ready |
| Featured guide | AI 量化内容的风险检查清单：从数据泄漏到实盘不可复现 | `/blog/ai-quant-risk-checklist` | Highlight compliance and research safety. | draft-ready |
| Community prompt | 你最近看到的 AI 投研开源项目，最值得验证的假设是什么？ | `/forum` | Seed first discussion loop. | ready |
| Weekly report | AI 投资与量化开源周报 2026-W18 | `/blog/weekly-ai-investing-open-source-2026-w18` | First publishable weekly report. | ready-to-publish |

## Launch Blog Drafts

| Priority | Slug | Draft Title | Content Type | Launch Status | Required Angle | Compliance Notes |
|---:|---|---|---|---|---|---|
| 1 | `tradingagents-research-boundaries` | TradingAgents 项目解读：多智能体投研框架能做什么，不能做什么 | Project review | draft-ready | LLM Agent 投研流程、角色分工、演示边界 | 研究演示，不评价可盈利性，不给交易建议 |
| 2 | `qlib-ai-quant-research-roadmap` | Qlib 入门路线：AI 量化研究平台的模块、数据和回测陷阱 | Tutorial / project review | draft-ready | 数据、模型、回测、工作流 | 强调回测偏差、交易成本、数据许可 |
| 3 | `openbb-ai-agent-data-terminal` | OpenBB 项目解读：开源金融数据终端如何服务 AI Agent 研究 | Project review | draft-ready | 数据入口、分析终端、Agent 集成可能性 | 不推荐具体资产，不绕过数据许可 |
| 4 | `quantstats-risk-report-intro` | QuantStats 风险报告入门：如何读懂收益曲线背后的风险指标 | Risk methodology | draft-ready | 最大回撤、夏普、波动、暴露解释 | 指标教育，不作为投资决策依据 |
| 5 | `vectorbt-research-notes` | vectorbt 研究笔记：向量化回测为什么快，以及为什么仍会错 | Tutorial / risk education | draft-ready | 向量化回测、参数扫描、过拟合风险 | 研究工具，不承诺策略有效 |
| 6 | `ai-quant-risk-checklist` | AI 量化内容的风险检查清单：从数据泄漏到实盘不可复现 | Risk methodology | draft-ready | 通用风险框架 | 全站合规与内容质量基准 |
| 7 | `tradingagents-qlib-boundary-comparison` | Agent 投研和传统量化平台如何互补：TradingAgents 与 Qlib 的边界比较 | Comparative guide | draft-ready | Agent 解释与量化验证的差异 | 不排名投资优劣，只比较研究流程 |
| 8 | `openbb-vectorbt-research-chain` | 从数据到回测：OpenBB 和 vectorbt 的研究链路示例 | Workflow guide | draft-ready | 数据获取、清洗、回测演示 | 明确示例数据和限制，不给实盘路径 |
| 9 | `llm-research-hypothesis-template` | 如何把 LLM 生成的投研想法转成可检验假设 | Methodology | draft-ready | 假设、特征、基准、失败标准 | 不把模型输出当作交易信号 |
| 10 | `safe-open-source-quant-first-run` | 看到一个开源量化项目，如何安全地第一次运行 | Beginner guide | draft-ready | 只读环境、依赖审查、API key 管理 | 禁止连接真实账户或实盘 API |
| 11 | `weekly-ai-investing-open-source-2026-w18` | AI 投资与量化开源周报 2026-W18 | Weekly report | ready-to-publish | 项目、教程、风险提醒、社区讨论 | 周报不提供投资建议或收益承诺 |

## Forum Seed Topics

The launch package uses the 24 prepared seed discussion topics from `backend/app/content/forum_seed.py`, covering:

- Project Discussion
- Strategy Research
- Tools
- Data & Backtesting
- Beginner Q&A
- Site Feedback

Minimum launch count: 24 prepared topics.

Priority topics for beta day one:

1. 你最近看到的 AI 投研开源项目，最值得验证的假设是什么？
2. 如何判断一个量化开源仓库是否仍然值得学习？
3. 一个策略研究帖至少应该说明哪些假设？
4. 如何把 LLM 生成的研究想法转成可检验假设？
5. 回测结果看起来很好时，第一步应该怀疑什么？
6. 一个投研工具上线前需要哪些安全说明？
7. 你希望平台先支持哪类研究工具？
8. 工具输出如何避免被误解为交易信号？
9. 新手最容易忽略的数据质量问题有哪些？
10. 看到一个开源量化项目，如何安全地第一次运行？

## Launch Tool Entries

| Tool Key | Name | Entry Type | Launch Status | Risk Boundary | Suggested CTA |
|---|---|---|---|---|---|
| `repo-scorecard` | 开源项目评分卡 | documentation-only | ready | Explains scoring dimensions; does not rank assets or recommend trades. | 查看评分维度 |
| `risk-reminder-generator` | 风险提示生成器 | runnable | ready | Generates generic risk reminders for content review; no personalized advice. | 生成风险提示 |
| `backtest-config-reviewer` | 回测配置审查清单 | external | ready | Reviews assumptions and missing risk controls; does not validate profitability. | 查看审查清单 |
| `weekly-candidate-pool` | 周报候选项目池 | documentation-only | ready | Supports editorial discovery and human review only. | 查看候选流程 |
| `safe-first-run-checklist` | 开源项目安全初跑清单 | runnable | ready | Guides dependency/API-key/sandbox checks; prohibits real-account connection. | 开始安全检查 |

Configured launch count: 5 tool entries.

## First Weekly Report Ready to Publish

### Front Matter

```yaml
title: "AI 投资与量化开源周报 2026-W18"
slug: "weekly-ai-investing-open-source-2026-w18"
summary: "本周关注 TradingAgents、Qlib、OpenBB、QuantStats、vectorbt，以及社区关于研究边界和安全工具体验的讨论。"
category: "weekly-report"
tags:
  - weekly-report
  - ai-investing
  - open-source
risk_level: "education-only"
status: "ready-to-publish"
discussion_thread_title: "本周 AI 投研开源项目，你最想复现哪一个？"
```

### 本周项目亮点

| 项目 | 类型 | 为什么值得看 | 风险边界 |
|---|---|---|---|
| TradingAgents | LLM Agent 投研框架 | 适合讨论多角色 Agent 如何组织研究流程 | 研究演示，不代表可实盘盈利 |
| Qlib | AI 量化研究平台 | 覆盖数据、模型、回测和工作流 | 注意数据许可、回测偏差和交易成本 |
| OpenBB | 开源金融数据终端 | 可作为 AI Agent 研究的数据入口案例 | 不绕过数据许可，不提供资产建议 |
| QuantStats | 风险报告工具 | 适合解释回撤、波动和风险指标 | 指标教育，不直接决定投资动作 |
| vectorbt | 向量化回测工具 | 适合讲解高效研究和参数扫描 | 警惕过拟合、样本选择和实盘不可复现 |

### 本周更新摘要

- **仓库观察:** 优先检查 README、许可证、最近 commit、issue 质量和示例可复现性。
- **教程准备:** 首批文章围绕项目边界、数据/回测陷阱、风险指标和安全初跑流程。
- **工具体验:** 首批工具限定在文档型、清单型和低风险生成型体验，避免任意代码执行或真实账户连接。
- **社区信号:** 启动讨论聚焦可检验假设、工具风险说明、数据质量和新手复现问题。

### 推荐阅读

- **入门:** AI 量化研究中的训练集、验证集、测试集和 walk-forward 概念。
- **实践:** 如何为开源项目创建只读、隔离、可删除的首次运行环境。
- **风险:** 回测中的数据泄漏、幸存者偏差、交易成本和流动性假设。

### 讨论问题

- 这个项目最适合做研究 demo 还是长期工具？
- 哪些结果可能来自数据泄漏或过拟合？
- 许可证和数据源是否允许公开复现？
- 如果做沙箱体验，应该禁止哪些能力？

### 下周观察清单

- TradingAgents 与 Qlib 的研究边界对比。
- OpenBB 到 vectorbt 的安全研究链路示例。
- 风险提示生成器是否能帮助编辑统一合规口径。

### Disclaimer

本内容仅供教育与研究讨论，不构成投资建议、交易建议或收益承诺。文中项目、工具、数据、回测和示例可能存在偏差、延迟、错误或不适用于真实市场。任何投资或交易决策都应由读者自行判断并承担风险。

## Launch Publishing Checklist

- [ ] Homepage selected content slots are assigned.
- [ ] At least 10 blog drafts have slugs, titles, content types, and compliance notes.
- [ ] At least 20 forum seed topics are available from the seed package.
- [ ] 3 to 5 tool entries have type, status, CTA, and risk boundary.
- [ ] Weekly report front matter and content sections are ready to publish.
- [ ] All launch content includes education/research boundaries.
- [ ] No launch content provides personalized investment advice, return promises, or real trading instructions.
