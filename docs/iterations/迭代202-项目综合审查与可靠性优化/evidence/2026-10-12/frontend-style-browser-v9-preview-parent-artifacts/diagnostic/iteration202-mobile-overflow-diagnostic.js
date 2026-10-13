const { chromium } = require('@playwright/test')

const BASE = 'http://127.0.0.1:4187'
const USER = {
  id: 'tailwind-style-user',
  username: 'Style Preview',
  email: 'style-preview@example.com',
  is_active: true,
  is_admin: true,
  created_at: '2026-07-12T00:00:00Z',
}

async function routes(page) {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.startsWith('/api/v1/')) {
      let body = { total: 0, items: [], skip: 0, limit: 50 }
      if (url.pathname.endsWith('/auth/me')) body = USER
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })
      return
    }
    if (url.origin !== BASE) {
      await route.abort()
      return
    }
    await route.continue()
  })
}

async function read(page, label) {
  return page.evaluate(label => {
    const popper = document.querySelector('.el-dropdown__popper')
    const rect = popper?.getBoundingClientRect()
    return {
      label,
      innerWidth: window.innerWidth,
      clientWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      popper: popper
        ? {
            className: popper.className,
            left: rect?.left,
            right: rect?.right,
            width: rect?.width,
            display: getComputedStyle(popper).display,
          }
        : null,
    }
  }, label)
}

async function selectTheme(page) {
  await page.locator('.theme-icon').click()
  await page.getByText('黑曜', { exact: true }).click()
}

async function diagnosePage(page, label) {
  const samples = [await read(page, label + ' pre-theme')]
  await selectTheme(page)
  samples.push(await read(page, label + ' after-theme-selection'))
  await page.setViewportSize({ width: 390, height: 844 })

  for (let index = 0; index < 12; index += 1) {
    if (index > 0) {
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => resolve())))
    }
    samples.push(await read(page, label + ' resize sample ' + index))
  }

  await page.waitForTimeout(450)
  samples.push(await read(page, label + ' after 450ms'))
  await page.screenshot({
    path: '/tmp/iter202-mobile-diag-' + label + '.png',
    fullPage: true,
  })
  return samples
}

;(async () => {
  const browser = await chromium.launch({ headless: true })
  console.log('browser=' + browser.version())

  const login = await browser.newPage({ viewport: { width: 1280, height: 720 } })
  await login.addInitScript(() => localStorage.setItem('locale', 'zh-CN'))
  await routes(login)
  await login.goto(BASE + '/login')
  await login.getByRole('form', { name: '登录' }).waitFor()
  await login.getByLabel('用户名').fill('preview-user')
  await login.getByLabel('密码').fill('preview-password')
  const loginSamples = await diagnosePage(login, 'login')

  const workspace = await browser.newPage({ viewport: { width: 1280, height: 720 } })
  await workspace.addInitScript(() => {
    localStorage.setItem('locale', 'zh-CN')
    sessionStorage.setItem('auth', JSON.stringify({
      token: 'tailwind-style-preview-token',
      refreshToken: null,
    }))
  })
  await routes(workspace)
  await workspace.goto(BASE + '/research/workspaces')
  await workspace.locator('[data-test="workspace-hero"]').waitFor()
  const workspaceSamples = await diagnosePage(workspace, 'workspace')

  console.log(JSON.stringify({ login: loginSamples, workspace: workspaceSamples }, null, 2))
  await browser.close()
})().catch(error => {
  console.error(error)
  process.exitCode = 1
})
