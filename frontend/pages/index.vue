<template>
  <div class="home-page">
    <section class="hero">
      <h1 class="hero-title">AI 交易与投资开源社区</h1>
      <p class="hero-subtitle">
        汇聚 AI 交易与投资领域的优质开源项目、实践教程和社区讨论
      </p>
      <div class="hero-actions">
        <NuxtLink to="/blog" class="btn btn-primary">浏览博客</NuxtLink>
        <NuxtLink to="/forum" class="btn btn-secondary">加入论坛</NuxtLink>
      </div>
    </section>

    <section class="features">
      <div class="feature-card">
        <h3 class="feature-title">开源项目精选</h3>
        <p class="feature-desc">发现并评估 AI 交易与投资领域的优质开源项目</p>
      </div>
      <div class="feature-card">
        <h3 class="feature-title">实践教程</h3>
        <p class="feature-desc">学习如何复现和研究开源项目，理解风险与局限</p>
      </div>
      <div class="feature-card">
        <h3 class="feature-title">社区讨论</h3>
        <p class="feature-desc">与其他研究者、开发者交流策略、工具和经验</p>
      </div>
      <div class="feature-card">
        <h3 class="feature-title">工具体验</h3>
        <p class="feature-desc">在线体验精选工具Demo，安全探索 AI 能力</p>
      </div>
    </section>

    <section class="disclaimer-section">
      <div class="disclaimer-box">
        <span class="disclaimer-icon">⚠️</span>
        <p class="disclaimer-text">
          <strong>风险提示：</strong>本网站内容仅供教育和研究目的，不构成任何形式的投资建议或荐股服务。
          投资有风险，入市需谨慎。过往表现不代表未来收益。
          <NuxtLink to="/legal/risk-disclaimer" class="disclaimer-link">查看完整金融风险免责声明</NuxtLink>
        </p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
useHead({
  title: 'AI For Investor - AI 交易与投资开源社区',
})
</script>

<style scoped>
.home-page {
  padding: var(--space-8) 0;
}

.hero {
  text-align: center;
  padding: var(--space-16) 0;
}

.hero-title {
  font-size: var(--font-size-3xl);
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: var(--space-4);
}

.hero-subtitle {
  font-size: var(--font-size-lg);
  color: var(--color-text-muted);
  max-width: 600px;
  margin: 0 auto var(--space-8);
}

.hero-actions {
  display: flex;
  gap: var(--space-4);
  justify-content: center;
}

.btn {
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-md);
  text-decoration: none;
  font-size: var(--font-size-md);
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.btn-primary:hover {
  background-color: var(--color-primary-hover);
}

.btn-secondary {
  background-color: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.btn-secondary:hover {
  border-color: var(--color-border-strong);
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: var(--space-6);
  padding: var(--space-12) 0;
}

.feature-card {
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
}

.feature-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.feature-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.disclaimer-section {
  padding: var(--space-8) 0;
}

.disclaimer-box {
  background-color: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
}

.disclaimer-icon {
  font-size: var(--font-size-xl);
}

.disclaimer-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  line-height: 1.7;
}

.disclaimer-link {
  display: inline-block;
  margin-left: var(--space-2);
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

@media (max-width: 640px) {
  .home-page {
    padding: var(--space-4) 0;
  }

  .hero {
    padding: var(--space-10) 0;
  }

  .hero-title {
    font-size: var(--font-size-2xl);
  }

  .hero-actions,
  .disclaimer-box {
    flex-direction: column;
  }

  .btn {
    width: 100%;
    text-align: center;
  }
}
</style>
