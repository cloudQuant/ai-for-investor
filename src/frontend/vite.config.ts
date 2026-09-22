/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'

const FRONTEND_DEV_PORT = 3000
const BACKEND_PROXY_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'
const ENABLE_BUILD_SOURCEMAP = process.env.VITE_BUILD_SOURCEMAP === 'true'
const BACKEND_PROXY = {
  '/api': {
    target: BACKEND_PROXY_TARGET,
    changeOrigin: true,
  },
  '/ws': {
    target: BACKEND_PROXY_TARGET.replace('http', 'ws'),
    ws: true,
  },
}

// Iteration 175 §2 — High_Coverage_Core modules and their >= 90% per-path
// thresholds. Listed inline so the source-of-truth lives next to the global
// thresholds. Mirrored in src/__tests__/coverage_core.md for human review.
const HIGH_COVERAGE_CORE_THRESHOLDS = {
  'src/stores/auth.ts':           { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/stores/theme.ts':          { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/stores/backtest.ts':       { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/stores/strategy.ts':       { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/stores/knowledgeBase.ts':  { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/api/index.ts':             { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/composables/useBacktestRuntime.ts': { lines: 90, functions: 90, branches: 90, statements: 90 },
  'src/utils/markdown-sanitizer.ts':       { lines: 90, functions: 90, branches: 90, statements: 90 },
}

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: 'auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'components.d.ts',
    }),
  ],
  test: {
    globals: true,
    environment: 'happy-dom',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    sequence: {
      setupFiles: 'first',
    },
    testTimeout: 10000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'json-summary', 'html'],
      include: ['src/**/*.{ts,vue}'],
      exclude: [
          'src/main.ts',
          'src/**/*.d.ts',
          'src/test/**',
          'src/i18n/**',
          'src/composables/useKeyboardShortcuts.ts',
        ],
      thresholds: {
        // Iteration 175 §2 — global ratchet 60 → 75
        // (174 set the floor at 60; 175 raises to 75. See PROGRESS.md §2.)
        lines: 75,
        statements: 75,
        functions: 75,
        branches: 75,
        ...HIGH_COVERAGE_CORE_THRESHOLDS,
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
      },
    },
  },
  optimizeDeps: {
    // Prebundling Monaco turns its stylesheet imports into absolute local
    // filesystem URLs in the dev server output. Those URLs resolve to the
    // SPA fallback instead of CSS, preventing the editor module from loading.
    exclude: ['monaco-editor'],
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: FRONTEND_DEV_PORT,
    strictPort: true,
    proxy: BACKEND_PROXY,
  },
  preview: {
    port: FRONTEND_DEV_PORT,
    strictPort: true,
    proxy: BACKEND_PROXY,
  },
  build: {
    outDir: 'dist',
    manifest: true,
    sourcemap: ENABLE_BUILD_SOURCEMAP,
    rollupOptions: {
      output: {
        // Keep the app-wide UI/framework modules and Vite's preload helper in
        // one shared chunk. This avoids loading a large lazy chunk just to reach
        // the helper and keeps /login within its all-assets request budget.
        manualChunks(id: string) {
          const normalizedId = id.replace(/\\/g, '/')
          if (normalizedId.includes('vite/preload-helper.js')) return 'application-vendor'
          if (
            id.includes('node_modules/element-plus/') ||
            id.includes('node_modules/@element-plus/') ||
            id.includes('node_modules/vue-router/') ||
            id.includes('node_modules/pinia/') ||
            normalizedId.includes('/src/components/LanguageSwitcher.vue') ||
            normalizedId.includes('/src/components/common/ThemeSwitcher.vue')
          )
            return 'application-vendor'
          // echarts ships zrender as runtime dep — keep them together.
          if (
            id.includes('node_modules/echarts/') ||
            id.includes('node_modules/echarts-gl/') ||
            id.includes('node_modules/vue-echarts/') ||
            id.includes('node_modules/zrender/')
          )
            return 'echarts'
          if (
            id.includes('node_modules/monaco-editor/') ||
            id.includes('node_modules/@monaco-editor/')
          )
            return 'monaco-editor'
          return undefined
        },
      },
    },
  },
})
