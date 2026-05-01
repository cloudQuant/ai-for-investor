<template>
  <article class="legal-page">
    <header class="legal-hero">
      <p class="eyebrow">Legal</p>
      <h1>用户协议</h1>
      <p>使用 AI For Investor 前，请阅读并理解本协议。本平台仅面向教育、研究和社区交流场景。</p>
    </header>

    <section class="legal-card">
      <h2>服务定位</h2>
      <p>AI For Investor 提供 AI 交易与投资领域的开源项目展示、文章内容、社区讨论和受控工具 Demo。平台内容仅供教育和研究目的，不构成投资建议、交易建议、荐股服务、收益承诺或任何形式的金融产品销售。</p>
    </section>

    <section class="legal-card">
      <h2>MVP 使用边界</h2>
      <ul>
        <li>平台不提供真实交易 API、券商账户或交易所账户绑定。</li>
        <li>平台不托管用户资金，不处理入金、出金、下单或清算。</li>
        <li>平台不允许任意用户代码执行，不支持自动化实盘交易。</li>
        <li>工具输出只能作为学习和研究参考，不能作为实际投资决策依据。</li>
      </ul>
    </section>

    <section class="legal-card">
      <h2>用户责任</h2>
      <p>你应自行判断内容适用性并承担使用风险。若你基于平台内容或工具结果作出投资、交易、开发或运营决策，由你自行负责。</p>
    </section>

    <section class="legal-card">
      <h2>内容与社区行为</h2>
      <p>用户发布内容应遵守法律法规和社区规则，不得发布误导性收益承诺、虚假宣传、账户凭证、隐私信息、恶意代码或诱导真实交易的信息。</p>
      <NuxtLink to="/forum/rules" class="legal-link">查看社区规则</NuxtLink>
    </section>

    <section class="legal-card highlight">
      <h2>相关页面</h2>
      <div class="link-list">
        <NuxtLink to="/legal/privacy">隐私政策</NuxtLink>
        <NuxtLink to="/legal/risk-disclaimer">金融风险免责声明</NuxtLink>
      </div>
    </section>
  </article>
</template>

<script setup lang="ts">
useHead({
  title: '用户协议 - AI For Investor',
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
  color: var(--color-primary);
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

.legal-link,
.link-list a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
}

.highlight {
  border-color: var(--color-primary);
}

.link-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
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
