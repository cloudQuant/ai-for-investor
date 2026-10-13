import { resolve } from 'node:path'
import { defineConfig, devices } from '@playwright/test'

const PORT = 4177
const BASE_URL = `http://127.0.0.1:${PORT}`
const ARTIFACTS = resolve(process.cwd(), 'e2e-results/iteration202')

export default defineConfig({
  testDir: './tests',
  testMatch: 'iteration202-session-workspace.spec.ts',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  outputDir: ARTIFACTS,
  reporter: [
    ['list'],
    ['json', { outputFile: resolve(ARTIFACTS, 'results.json') }],
  ],
  use: {
    baseURL: BASE_URL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium-fixture',
      use: { ...devices['Desktop Chrome'] },
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
