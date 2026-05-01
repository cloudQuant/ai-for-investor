# Community Rules and Seed Discussion Plan Package

## Community Rules

1. **No personalized investment advice**  
   Do not request or provide personalized investment advice, buy/sell/hold instructions, portfolio allocation, return promises, or real-funds trading directions.

2. **No spam or low-signal promotion**  
   No spam, referral farming, repeated promotional links, undisclosed sponsorship, scraped reposts, or unrelated marketing content.

3. **No abusive behavior**  
   No abusive behavior, harassment, hate speech, doxxing, personal attacks, or hostile replies that prevent constructive technical discussion.

4. **No unsafe tool claims**  
   Do not make unsafe tool claims such as guaranteed profitability, production-ready trading safety, broker compatibility, account automation, or risk-free execution without evidence and limitations.

## Default Forum Categories

| Name | Slug | Purpose |
|---|---|---|
| Project Discussion | `project-discussion` | Open-source AI investing and quantitative research projects, repository signals, maintenance, licensing, and learning value. |
| Strategy Research | `strategy-research` | Research-only strategy ideas, assumptions, evaluation design, risk controls, and reproducibility boundaries. |
| Tools | `tools` | Platform tools, AI agents, notebooks, dashboards, workflows, and safe tool usage patterns. |
| Data & Backtesting | `data-backtesting` | Data quality, backtesting design, transaction costs, bias controls, benchmark construction, and evaluation caveats. |
| Beginner Q&A | `beginner-qna` | Beginner-friendly questions about AI investing concepts, quant research vocabulary, project setup, and safe learning paths. |
| Site Feedback | `site-feedback` | Site UX, content organization, missing docs, issue reports, and community workflow improvements. |

## Seed Discussion Topics

### Project Discussion

1. 你最近看到的 AI 投研开源项目，最值得验证的假设是什么？
2. 如何判断一个量化开源仓库是否仍然值得学习？
3. 项目解读文章应该优先覆盖哪些仓库信号？
4. 哪些 AI Agent 投研项目适合作为教学案例？

### Strategy Research

5. 一个策略研究帖至少应该说明哪些假设？
6. 如何把 LLM 生成的研究想法转成可检验假设？
7. 如何识别策略讨论中的收益承诺或投资建议风险？
8. 回测结果看起来很好时，第一步应该怀疑什么？

### Tools

9. 一个投研工具上线前需要哪些安全说明？
10. 你希望平台先支持哪类研究工具？
11. 如何设计一个不执行用户任意代码的 notebook 解读流程？
12. 工具输出如何避免被误解为交易信号？

### Data & Backtesting

13. 新手最容易忽略的数据质量问题有哪些？
14. 一个回测问题帖应该附哪些最小信息？
15. 如何解释训练集、验证集和测试集在金融时间序列中的差异？
16. 评价策略时你最看重哪些风险指标？

### Beginner Q&A

17. AI 投资研究入门应该先学哪些基础概念？
18. 看到一个开源量化项目，如何安全地第一次运行？
19. 如何提问才能让别人复现你的问题？
20. LLM 在投研学习中适合做什么、不适合做什么？

### Site Feedback

21. 论坛首页还缺少哪些信息帮助你找到高质量讨论？
22. 你希望每篇项目解读文章怎样关联讨论区？
23. 社区规则还有哪些需要更明确的边界？
24. 周报候选项目应该开放社区提名吗？

## Article-to-Thread Linking Guidance

Key article front matter can store `discussion_thread_id` so each article can link to its associated forum thread for follow-up questions, corrections, and community examples.

If no thread exists yet, show a prompt inviting verified users to create a related discussion thread.

## High-Quality Question Guidance

- **Strategy questions:** describe the research hypothesis, market universe, time range, data frequency, assumptions, costs, and risk metric being evaluated.
- **Tool questions:** include tool name, version, input data shape, expected output, actual output, error logs, and whether any API key or external service is involved.
- **Data/backtesting questions:** include data source, cleaning steps, benchmark, transaction cost assumptions, and known bias controls.
- **Boundary:** avoid asking for personalized buy/sell decisions; ask for methodology, reproducibility, risk checks, and educational explanations instead.
