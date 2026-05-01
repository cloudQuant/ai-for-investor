export default defineNuxtConfig({
  devtools: { enabled: true },

  app: {
    head: {
      title: 'AI For Investor',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: 'AI交易与投资开源项目精选、实践教程、工具体验与社区讨论平台' },
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'alternate', type: 'application/rss+xml', title: 'AI For Investor Blog RSS', href: '/api/v1/blog/rss.xml' },
      ],
    },
  },

  runtimeConfig: {
    public: {
      apiBase: process.env.API_BASE || '/api/v1',
      uiTheme: process.env.UI_THEME || 'fintech-trust-light',
      siteUrl: process.env.NUXT_PUBLIC_SITE_URL || 'http://localhost:3000',
    },
  },

  modules: ['@pinia/nuxt'],

  css: [
    '~/assets/styles/tokens/base.css',
  ],

  vite: {
    css: {
      preprocessorOptions: {},
    },
  },

  typescript: {
    strict: true,
    typeCheck: false,
  },

  compatibilityDate: '2024-01-01',
})
