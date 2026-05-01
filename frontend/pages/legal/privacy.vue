<template>
  <article class="legal-page">
    <header class="legal-hero">
      <p class="eyebrow">Privacy</p>
      <h1>隐私政策</h1>
      <p>本政策说明 AI For Investor 在 MVP 阶段如何处理账号、内容、工具任务和基础运行数据。</p>
    </header>

    <section class="legal-card">
      <h2>我们可能收集的信息</h2>
      <ul>
        <li>账号信息：邮箱、用户名、角色、邮箱验证状态。</li>
        <li>用户内容：论坛主题、回复、举报、偏好设置和工具任务参数。</li>
        <li>运行信息：请求 ID、访问时间、浏览器 user-agent、IP 地址和基础错误日志。</li>
      </ul>
    </section>

    <section class="legal-card">
      <h2>数据使用目的</h2>
      <p>我们使用数据用于账号认证、邮箱验证、社区安全、内容审核、工具任务归属、滥用防护、故障排查和产品改进。平台不会将用户数据用于提供个性化投资建议、交易建议或收益承诺。</p>
    </section>

    <section class="legal-card">
      <h2>敏感边界</h2>
      <p>平台不要求也不应接收券商账号、交易所 API Key、钱包私钥、银行卡、资金账户或其他真实交易凭证。请勿在论坛、工具参数或个人资料中提交这些信息。</p>
    </section>

    <section class="legal-card">
      <h2>共享与安全</h2>
      <p>除法律要求、平台安全和必要服务运维外，我们不会主动出售用户个人信息。我们会采用访问控制、审计日志、敏感信息过滤和受控工具执行边界来降低数据泄露风险。</p>
    </section>

    <section class="legal-card highlight">
      <h2>相关页面</h2>
      <div class="link-list">
        <NuxtLink to="/legal/terms">用户协议</NuxtLink>
        <NuxtLink to="/legal/risk-disclaimer">金融风险免责声明</NuxtLink>
      </div>
    </section>
  </article>
</template>

<script setup lang="ts">
useHead({
  title: '隐私政策 - AI For Investor',
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
