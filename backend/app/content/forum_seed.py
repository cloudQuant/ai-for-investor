COMMUNITY_RULES = [
    {
        "key": "no_investment_advice",
        "title": "No personalized investment advice",
        "description": "Do not request or provide personalized investment advice, buy/sell/hold instructions, portfolio allocation, return promises, or real-funds trading directions.",
    },
    {
        "key": "no_spam",
        "title": "No spam or low-signal promotion",
        "description": "No spam, referral farming, repeated promotional links, undisclosed sponsorship, scraped reposts, or unrelated marketing content.",
    },
    {
        "key": "respectful_behavior",
        "title": "No abusive behavior",
        "description": "No abusive behavior, harassment, hate speech, doxxing, personal attacks, or hostile replies that prevent constructive technical discussion.",
    },
    {
        "key": "safe_tool_claims",
        "title": "No unsafe tool claims",
        "description": "Do not make unsafe tool claims such as guaranteed profitability, production-ready trading safety, broker compatibility, account automation, or risk-free execution without evidence and limitations.",
    },
]

DEFAULT_FORUM_CATEGORIES = [
    {
        "name": "Project Discussion",
        "slug": "project-discussion",
        "description": "Discuss open-source AI investing and quantitative research projects, repository signals, maintenance, licensing, and learning value.",
        "sort_order": 10,
    },
    {
        "name": "Strategy Research",
        "slug": "strategy-research",
        "description": "Discuss research-only strategy ideas, assumptions, evaluation design, risk controls, and reproducibility boundaries.",
        "sort_order": 20,
    },
    {
        "name": "Tools",
        "slug": "tools",
        "description": "Discuss platform tools, AI agents, notebooks, dashboards, workflows, and safe tool usage patterns.",
        "sort_order": 30,
    },
    {
        "name": "Data & Backtesting",
        "slug": "data-backtesting",
        "description": "Discuss data quality, backtesting design, transaction costs, bias controls, benchmark construction, and evaluation caveats.",
        "sort_order": 40,
    },
    {
        "name": "Beginner Q&A",
        "slug": "beginner-qna",
        "description": "Beginner-friendly questions about AI investing concepts, quant research vocabulary, project setup, and safe learning paths.",
        "sort_order": 50,
    },
    {
        "name": "Site Feedback",
        "slug": "site-feedback",
        "description": "Feedback about site UX, content organization, missing docs, issue reports, and community workflow improvements.",
        "sort_order": 60,
    },
]

SEED_DISCUSSION_TOPICS = [
    {"category_slug": "project-discussion", "title": "你最近看到的 AI 投研开源项目，最值得验证的假设是什么？", "prompt": "请附仓库链接、项目用途、数据依赖、许可证线索，以及为什么它适合研究而不是直接实盘。"},
    {"category_slug": "project-discussion", "title": "如何判断一个量化开源仓库是否仍然值得学习？", "prompt": "可以从 commit 活跃度、issue 质量、示例完整度、依赖安全和论文/文档引用角度讨论。"},
    {"category_slug": "project-discussion", "title": "项目解读文章应该优先覆盖哪些仓库信号？", "prompt": "讨论 stars/forks、维护频率、文档、测试、许可证、数据来源和可复现性之间的权重。"},
    {"category_slug": "project-discussion", "title": "哪些 AI Agent 投研项目适合作为教学案例？", "prompt": "请说明教学价值、失败风险、是否需要 API key，以及如何避免夸大能力。"},
    {"category_slug": "strategy-research", "title": "一个策略研究帖至少应该说明哪些假设？", "prompt": "请围绕标的范围、时间区间、数据频率、交易成本、再平衡方式和风险指标展开。"},
    {"category_slug": "strategy-research", "title": "如何把 LLM 生成的研究想法转成可检验假设？", "prompt": "讨论从自然语言想法到特征、基准、消融实验和失败标准的转换流程。"},
    {"category_slug": "strategy-research", "title": "如何识别策略讨论中的收益承诺或投资建议风险？", "prompt": "列出容易越界的表达，并给出研究/教育语境下的替代表述。"},
    {"category_slug": "strategy-research", "title": "回测结果看起来很好时，第一步应该怀疑什么？", "prompt": "讨论过拟合、数据泄漏、幸存者偏差、手续费、滑点、流动性和样本选择。"},
    {"category_slug": "tools", "title": "一个投研工具上线前需要哪些安全说明？", "prompt": "请覆盖输入限制、输出解释、权限范围、数据来源、错误处理和不构成投资建议声明。"},
    {"category_slug": "tools", "title": "你希望平台先支持哪类研究工具？", "prompt": "例如仓库评分、数据质量检查、回测配置审查、风险提示生成、周报候选池等。"},
    {"category_slug": "tools", "title": "如何设计一个不执行用户任意代码的 notebook 解读流程？", "prompt": "讨论静态解析、元数据抽取、依赖扫描、沙箱边界和用户提示。"},
    {"category_slug": "tools", "title": "工具输出如何避免被误解为交易信号？", "prompt": "讨论 UI 文案、风险标签、置信度、解释字段和明确禁止的动作建议。"},
    {"category_slug": "data-backtesting", "title": "新手最容易忽略的数据质量问题有哪些？", "prompt": "讨论复权、停牌、退市、时区、缺失值、延迟数据和供应商差异。"},
    {"category_slug": "data-backtesting", "title": "一个回测问题帖应该附哪些最小信息？", "prompt": "请列出数据区间、频率、交易规则、成本假设、基准、代码片段和异常现象。"},
    {"category_slug": "data-backtesting", "title": "如何解释训练集、验证集和测试集在金融时间序列中的差异？", "prompt": "讨论 walk-forward、时间泄漏、调参污染和 regime shift。"},
    {"category_slug": "data-backtesting", "title": "评价策略时你最看重哪些风险指标？", "prompt": "讨论回撤、波动、换手、暴露、尾部风险、容量和稳定性，而不是只看收益率。"},
    {"category_slug": "beginner-qna", "title": "AI 投资研究入门应该先学哪些基础概念？", "prompt": "欢迎整理统计、Python、金融市场、回测、机器学习和风险管理的学习路径。"},
    {"category_slug": "beginner-qna", "title": "看到一个开源量化项目，如何安全地第一次运行？", "prompt": "讨论只读环境、虚拟环境、依赖审查、API key 管理和避免连接真实账户。"},
    {"category_slug": "beginner-qna", "title": "如何提问才能让别人复现你的问题？", "prompt": "请包括环境、版本、最小复现、期望结果、实际结果、错误日志和已尝试方法。"},
    {"category_slug": "beginner-qna", "title": "LLM 在投研学习中适合做什么、不适合做什么？", "prompt": "讨论解释概念、生成检查清单、辅助读代码，以及不应直接相信其交易建议。"},
    {"category_slug": "site-feedback", "title": "论坛首页还缺少哪些信息帮助你找到高质量讨论？", "prompt": "欢迎反馈分类、排序、搜索、标签、置顶规则、空状态和新手引导。"},
    {"category_slug": "site-feedback", "title": "你希望每篇项目解读文章怎样关联讨论区？", "prompt": "讨论文章底部讨论链接、关联主题、精选回复、后续问题和版本更新。"},
    {"category_slug": "site-feedback", "title": "社区规则还有哪些需要更明确的边界？", "prompt": "例如投资建议、工具声明、广告、争议项目、外部链接和举报处理。"},
    {"category_slug": "site-feedback", "title": "周报候选项目应该开放社区提名吗？", "prompt": "讨论提名模板、反垃圾门槛、项目评分维度和编辑复核流程。"},
]

ARTICLE_THREAD_LINKING_GUIDANCE = {
    "front_matter_field": "discussion_thread_id",
    "usage": "Key article front matter can store a discussion_thread_id so each article can link to its associated forum thread for follow-up questions, corrections, and community examples.",
    "fallback": "If no thread exists yet, show a prompt inviting verified users to create a related discussion thread.",
}

COMMUNITY_QUESTION_GUIDANCE = [
    "For strategy questions, describe the research hypothesis, market universe, time range, data frequency, assumptions, costs, and risk metric you are evaluating.",
    "For tool questions, include the tool name, version, input data shape, expected output, actual output, error logs, and whether any API key or external service is involved.",
    "For data and backtesting questions, include data source, cleaning steps, benchmark, transaction cost assumptions, and known bias controls.",
    "Avoid asking for personalized buy/sell decisions; ask for methodology, reproducibility, risk checks, and educational explanations instead.",
]
