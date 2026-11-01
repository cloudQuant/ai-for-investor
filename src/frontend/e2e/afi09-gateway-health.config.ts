import { resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const port = Number(process.env.AFI09_E2E_FRONTEND_PORT ?? 3189)
const baseURL = `http://127.0.0.1:${port}`
const apiTarget = process.env.AFI09_E2E_API_TARGET
const envDir = process.env.AFI09_E2E_ENV_DIR
if (!apiTarget || !envDir) {
  throw new Error('AFI09 synthetic API target and isolated Vite env directory are required')
}

export default defineConfig({
  testDir: './tests',
  testMatch: 'afi09-gateway-health.spec.ts',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  outputDir: resolve(process.cwd(), 'e2e-results/afi09-gateway-health'),
  reporter: [['list']],
  use: {
    baseURL,
    browserName: 'chromium',
    channel: 'chrome',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'afi09-chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    cwd: process.cwd(),
    command: `node node_modules/vite/bin/vite.js --config e2e/afi09-gateway-health.vite.config.ts --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      AFI09_E2E_ENV_DIR: envDir,
      VITE_API_TARGET: apiTarget,
    },
  },
})
