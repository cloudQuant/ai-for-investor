import { resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const PORT = 4187
const BASE_URL = `http://127.0.0.1:${PORT}`
const EVIDENCE_DIR = '/tmp/iteration202-tailwind4-compat'

export default defineConfig({
  testDir: './tailwind4',
  testMatch: 'style-regression.spec.ts',
  timeout: 60_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  outputDir: resolve(EVIDENCE_DIR, 'playwright-artifacts'),
  reporter: [
    ['list'],
    ['json', { outputFile: resolve(EVIDENCE_DIR, 'playwright-results.json') }],
  ],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 900 },
    trace: 'on',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium-style-regression',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox-style-regression',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit-style-regression',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  webServer: {
    cwd: process.cwd(),
    // Run npm run build first. This suite exercises dist via preview; missing
    // build output should fail instead of silently falling back to Vite dev.
    command: `node_modules/.bin/vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: 120_000,
    env: { VITE_API_TARGET: `http://127.0.0.1:${PORT + 1}` },
  },
})
