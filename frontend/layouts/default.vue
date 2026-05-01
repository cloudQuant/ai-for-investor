<template>
  <div class="app-layout">
    <header class="header">
      <div class="header-content">
        <NuxtLink to="/" class="logo">AI For Investor</NuxtLink>
        <nav class="nav">
          <NuxtLink to="/blog" class="nav-link">博客</NuxtLink>
          <NuxtLink to="/forum" class="nav-link">论坛</NuxtLink>
          <NuxtLink to="/tools" class="nav-link">工具</NuxtLink>
          <NuxtLink to="/open-source" class="nav-link">开源项目</NuxtLink>
        </nav>
        <div class="header-actions">
          <ThemeSwitcher />
          <UserMenu />
        </div>
      </div>
    </header>
    <main class="main">
      <slot />
    </main>
    <footer class="footer">
      <div class="footer-content">
        <p class="disclaimer">免责声明：本网站内容仅供教育和研究目的，不构成投资建议。投资有风险，决策需谨慎。</p>
        <nav class="footer-links">
          <NuxtLink to="/legal/terms">用户协议</NuxtLink>
          <NuxtLink to="/legal/privacy">隐私政策</NuxtLink>
          <NuxtLink to="/legal/risk-disclaimer">金融风险免责声明</NuxtLink>
        </nav>
        <p class="copyright">© 2026 AI For Investor. All rights reserved.</p>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
const { initializeTheme } = useTheme()

onMounted(() => {
  initializeTheme()
})
</script>

<style>
@import '~/assets/styles/themes/fintech-trust-light.css';
@import '~/assets/styles/themes/terminal-agent-dark.css';
@import '~/assets/styles/themes/minimal-focus.css';
@import '~/assets/styles/themes/research-docs-light.css';

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background-color: var(--color-bg);
  color: var(--color-text);
  line-height: 1.6;
}

.app-layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background-color: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-content {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 var(--space-4);
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: var(--space-8);
}

.logo {
  font-size: var(--font-size-lg);
  font-weight: 700;
  color: var(--color-primary);
  text-decoration: none;
}

.nav {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}

.nav-link {
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: var(--font-size-sm);
  transition: color 0.2s;
}

.nav-link:hover {
  color: var(--color-text);
}

.header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.main {
  flex: 1;
  max-width: 1280px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-4);
  width: 100%;
}

.footer {
  background-color: var(--color-surface);
  border-top: 1px solid var(--color-border);
  padding: var(--space-8) var(--space-4);
}

.footer-content {
  max-width: 1280px;
  margin: 0 auto;
  text-align: center;
}

.disclaimer {
  color: var(--color-warning);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-4);
}

.footer-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.footer-links a {
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

.copyright {
  color: var(--color-text-subtle);
  font-size: var(--font-size-xs);
}

@media (max-width: 768px) {
  .header-content {
    flex-wrap: wrap;
    height: auto;
    gap: var(--space-3);
    padding-top: var(--space-3);
    padding-bottom: var(--space-3);
  }

  .logo {
    width: 100%;
  }

  .nav {
    order: 3;
    width: 100%;
    gap: var(--space-3);
  }

  .nav-link {
    padding: var(--space-2) 0;
  }

  .header-actions {
    margin-left: 0;
  }

  .main {
    padding: var(--space-5) var(--space-3);
  }

  .footer {
    padding: var(--space-6) var(--space-3);
  }
}
</style>
