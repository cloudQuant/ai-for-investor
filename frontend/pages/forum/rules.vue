<template>
  <div class="rules-page">
    <header class="rules-hero">
      <NuxtLink to="/forum" class="back-link">返回论坛</NuxtLink>
      <h1>社区规则与高质量提问指南</h1>
      <p>论坛用于 AI 投资与量化研究的教育讨论，不提供投资建议、交易指令或收益承诺。</p>
    </header>

    <section class="rules-section">
      <h2>社区规则</h2>
      <div class="rule-grid">
        <article class="rule-card">
          <h3>禁止个性化投资建议</h3>
          <p>不要请求或提供买入、卖出、持有、仓位配置、收益预测、实盘交易路径等个性化建议。</p>
        </article>
        <article class="rule-card">
          <h3>禁止垃圾信息</h3>
          <p>不要发布重复推广、返佣链接、无披露赞助、无关广告、低质量搬运或与主题无关的营销内容。</p>
        </article>
        <article class="rule-card">
          <h3>禁止攻击与骚扰</h3>
          <p>保持技术讨论友善，禁止辱骂、骚扰、人身攻击、仇恨言论、公开隐私和恶意挑衅。</p>
        </article>
        <article class="rule-card">
          <h3>禁止不安全工具声明</h3>
          <p>不要宣称工具可以保证盈利、无风险实盘、自动连接真实账户或绕过必要验证。</p>
        </article>
      </div>
    </section>

    <section class="rules-section">
      <h2>默认讨论分类</h2>
      <div class="category-grid">
        <div class="category-card">项目讨论</div>
        <div class="category-card">策略研究</div>
        <div class="category-card">工具</div>
        <div class="category-card">数据与回测</div>
        <div class="category-card">新手问答</div>
        <div class="category-card">站点反馈</div>
      </div>
    </section>

    <section class="rules-section">
      <h2>如何提出高质量策略问题</h2>
      <ul class="guidance-list">
        <li>说明研究假设、市场范围、时间区间、数据频率和样本选择。</li>
        <li>描述交易成本、滑点、再平衡方式、基准和风险指标。</li>
        <li>明确你想验证的方法问题，而不是请求别人给出买卖决策。</li>
        <li>附上最小复现、异常现象、已尝试方案和你认为可能的原因。</li>
      </ul>
    </section>

    <section class="rules-section">
      <h2>如何提出高质量工具问题</h2>
      <ul class="guidance-list">
        <li>提供工具名称、版本、运行环境、输入数据形态和期望输出。</li>
        <li>粘贴关键错误信息、最小复现步骤和已尝试排查路径。</li>
        <li>说明是否涉及 API Key、外部服务、模型下载或敏感权限。</li>
        <li>把工具输出视为研究辅助材料，不把它当作交易信号或收益保证。</li>
      </ul>
    </section>

    <section class="rules-section">
      <h2>文章与讨论串关联</h2>
      <p>关键文章可以关联一个讨论主题，用于收集补充问题、复现反馈、错误更正和后续案例。若文章暂未关联讨论串，欢迎认证用户根据文章主题发起高质量讨论。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
useHead({
  title: '社区规则 - AI For Investor',
})
</script>

<style scoped>
.rules-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-4) 0;
}

.rules-hero {
  margin-bottom: var(--space-8);
}

.back-link {
  display: inline-block;
  margin-bottom: var(--space-4);
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

.rules-hero h1 {
  font-size: var(--font-size-2xl);
  margin-bottom: var(--space-3);
}

.rules-hero p {
  color: var(--color-text-muted);
}

.rules-section {
  margin-bottom: var(--space-8);
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.rules-section h2 {
  margin-bottom: var(--space-4);
  font-size: var(--font-size-lg);
}

.rule-grid,
.category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-4);
}

.rule-card,
.category-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-bg);
}

.rule-card h3 {
  margin-bottom: var(--space-2);
  font-size: var(--font-size-md);
}

.rule-card p,
.rules-section p,
.guidance-list {
  color: var(--color-text-muted);
}

.category-card {
  font-weight: 600;
  color: var(--color-text);
}

.guidance-list {
  padding-left: var(--space-6);
}

.guidance-list li {
  margin-bottom: var(--space-2);
}
</style>
