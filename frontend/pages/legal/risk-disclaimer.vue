<template>
  <article class="legal-page">
    <header class="legal-hero warning">
      <p class="eyebrow">Risk Disclosure</p>
      <h1>金融风险免责声明</h1>
      <p>AI For Investor 的所有内容、项目和工具仅供教育与研究目的，不提供投资建议。</p>
    </header>

    <section class="legal-card critical">
      <h2>非投资建议</h2>
      <p>本平台不提供投资建议、交易建议、荐股服务、资产管理服务、收益承诺或金融产品销售。任何文章、评分、项目介绍、论坛讨论和工具输出都不应被视为买入、卖出、持有或配置任何资产的建议。</p>
    </section>

    <section class="legal-card">
      <h2>投资与交易风险</h2>
      <p>金融市场存在本金损失风险。模型、回测、开源项目、历史数据、演示工具和社区观点都可能存在错误、滞后、偏差或不适用于真实市场环境。过往表现不代表未来收益。</p>
    </section>

    <section class="legal-card">
      <h2>平台执行边界</h2>
      <ul>
        <li>平台不接入真实交易 API，不连接券商或交易所账户。</li>
        <li>平台不托管用户资金，不执行入金、出金、下单、撤单或清算。</li>
        <li>平台工具在受控边界内运行，不允许任意用户代码执行。</li>
        <li>高风险实盘交易、券商连接和自动下单能力不属于 MVP 范围。</li>
      </ul>
    </section>

    <section class="legal-card">
      <h2>用户自行判断</h2>
      <p>你应结合自身知识、风险承受能力和独立研究作出判断，并在必要时咨询合格专业人士。因使用平台内容、工具或社区信息产生的任何损失，由用户自行承担。</p>
    </section>

    <section class="legal-card highlight">
      <h2>相关页面</h2>
      <div class="link-list">
        <NuxtLink to="/legal/terms">用户协议</NuxtLink>
        <NuxtLink to="/legal/privacy">隐私政策</NuxtLink>
      </div>
    </section>
  </article>
</template>

<script setup lang="ts">
useHead({
  title: '金融风险免责声明 - AI For Investor',
})
</script>

<style scoped>
.legal-page {
  max-width: 880px;
  margin: 0 auto;
  padding: var(--space-4) 0;
}

.legal-hero {
  margin-bottom: var(--space-8);
}

.eyebrow {
  color: var(--color-warning);
  font-size: var(--font-size-sm);
  font-weight: 700;
  margin-bottom: var(--space-2);
}

.legal-hero h1 {
  font-size: var(--font-size-3xl);
  margin-bottom: var(--space-3);
}

.legal-hero p,
.legal-card p,
.legal-card li {
  color: var(--color-text-muted);
}

.legal-card {
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
  margin-bottom: var(--space-4);
}

.legal-card h2 {
  margin-bottom: var(--space-3);
}

.legal-card ul {
  padding-left: var(--space-6);
}

.critical {
  border-color: var(--color-warning);
}

.highlight {
  border-color: var(--color-primary);
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
}

.link-list a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
}

@media (max-width: 640px) {
  .legal-hero h1 {
    font-size: var(--font-size-2xl);
  }

  .legal-card {
    padding: var(--space-4);
  }
}
</style>
