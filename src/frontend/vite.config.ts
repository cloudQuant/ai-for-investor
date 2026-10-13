/// <reference types="vitest/config" />
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
let authChunkModules: Set<string> | undefined
let shellChunkModules: Set<string> | undefined

const ELEMENT_PLUS_COMPONENT_ENTRY_PATHS: Readonly<Record<string, string>> = {
  ElButton: 'element-plus/es/components/button/index.mjs',
  ElConfigProvider: 'element-plus/es/components/config-provider/index.mjs',
  ElDropdown: 'element-plus/es/components/dropdown/index.mjs',
  ElDropdownItem: 'element-plus/es/components/dropdown/index.mjs',
  ElDropdownMenu: 'element-plus/es/components/dropdown/index.mjs',
  ElForm: 'element-plus/es/components/form/index.mjs',
  ElFormItem: 'element-plus/es/components/form/index.mjs',
  ElIcon: 'element-plus/es/components/icon/index.mjs',
  ElInput: 'element-plus/es/components/input/index.mjs',
  ElResult: 'element-plus/es/components/result/index.mjs',
}

function elementPlusResolvers() {
  return ElementPlusResolver().map((resolver) => {
    if (typeof resolver === 'function' || resolver.type !== 'component') return resolver

    return {
      ...resolver,
      async resolve(name: string) {
        const resolved = await resolver.resolve(name)
        const entryPath = ELEMENT_PLUS_COMPONENT_ENTRY_PATHS[name]
        if (
          entryPath &&
          resolved &&
          typeof resolved === 'object' &&
          'from' in resolved &&
          resolved.from === 'element-plus/es'
        ) {
          return { ...resolved, from: entryPath }
        }
        return resolved
      },
    }
  })
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
    {
      name: 'reset-auth-chunk-modules',
      buildStart() {
        authChunkModules = undefined
        shellChunkModules = undefined
      },
    },
    AutoImport({
      resolvers: [elementPlusResolvers()],
      dts: 'auto-imports.d.ts',
    }),
    Components({
      resolvers: [elementPlusResolvers()],
      dts: 'components.d.ts',
    }),
  ],
  test: {
    globals: true,
    environment: 'happy-dom',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    sequence: {
      setupFiles: 'list',
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
        onlyExplicitManualChunks: true,
        // Keep the complete static app-shell closure together. Route-specific
        // modules stay lazy so /login does not preload unrelated page UI.
        manualChunks(id: string, { getModuleIds, getModuleInfo }) {
          const normalizedId = id.replace(/\\/g, '/')
          const modulePath = (moduleId: string) =>
            moduleId.replace(/\\/g, '/').split('?')[0]
          const matchesSource = (moduleId: string, sourcePath: string) =>
            modulePath(moduleId).endsWith(sourcePath)
          if (normalizedId.includes('vite/preload-helper.js')) return 'application-vendor'
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

          if (!authChunkModules || !shellChunkModules) {
            const moduleIds = [...getModuleIds()]
            const shellRoots = moduleIds.filter((moduleId) => {
              const path = modulePath(moduleId)
              return (
                path.endsWith('/index.html') ||
                path.endsWith('/src/main.ts') ||
                moduleId.includes('vite/preload-helper.js') ||
                moduleId.includes('node_modules/vue-router/') ||
                matchesSource(moduleId, '/src/components/LanguageSwitcher.vue') ||
                matchesSource(moduleId, '/src/components/common/ThemeSwitcher.vue') ||
                matchesSource(moduleId, '/src/components/common/ErrorBoundary.vue')
              )
            })
            const authRoots = moduleIds.filter((moduleId) =>
              matchesSource(moduleId, '/src/views/LoginPage.vue') ||
              matchesSource(moduleId, '/src/components/auth/AuthFrame.vue'),
            )

            const collectStaticDependencies = (roots: string[]) => {
              const visited = new Set<string>()
              const pending = [...roots]
              while (pending.length > 0) {
                const current = pending.pop()
                if (!current || visited.has(current)) continue
                visited.add(current)
                const info = getModuleInfo(current)
                if (info) pending.push(...info.importedIds)
              }
              return visited
            }

            const shellModules = collectStaticDependencies(shellRoots)
            const authModules = collectStaticDependencies(authRoots)
            shellChunkModules = shellModules
            authChunkModules = new Set(
              [...authModules].filter(
                (moduleId) =>
                  !shellModules.has(moduleId) &&
                  !matchesSource(moduleId, '/src/views/LoginPage.vue'),
              ),
            )
          }
          if (
            modulePath(id).endsWith('/index.html') ||
            modulePath(id).endsWith('/src/main.ts')
          )
            return undefined
          if (shellChunkModules?.has(id)) return 'application-vendor'
          if (authChunkModules?.has(id)) return 'auth'
          return undefined
        },
      },
    },
  },
})
