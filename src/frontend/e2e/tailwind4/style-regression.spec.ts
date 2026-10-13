import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

const EVIDENCE_DIR = '/tmp/iteration202-tailwind4-compat'
type RuntimeDiagnostic = { source: string; message: string }

const runtimeDiagnosticsByPage = new WeakMap<Page, RuntimeDiagnostic[]>()

const USER = {
  id: 'tailwind-style-user',
  username: 'Style Preview',
  email: 'style-preview@example.com',
  is_active: true,
  is_admin: true,
  created_at: '2026-07-12T00:00:00Z',
}

function collectRuntimeDiagnostics(page: Page): void {
  const diagnostics: RuntimeDiagnostic[] = []
  runtimeDiagnosticsByPage.set(page, diagnostics)

  page.on('pageerror', error => {
    diagnostics.push({ source: 'pageerror', message: error.stack ?? error.message })
  })
  page.on('console', message => {
    const text = message.text()
    const type = message.type()
    const isProductError = type === 'error'
      && (
        text.startsWith('[Global Error Handler]')
        || text.startsWith('[Unhandled Promise Rejection]')
      )
    const isUnresolvedComponent = (type === 'warning' || type === 'error')
      && text.includes('Failed to resolve component:')

    if (isProductError || isUnresolvedComponent) {
      diagnostics.push({ source: `console.${type}`, message: text })
    }
  })
}

function assertNoRuntimeDiagnostics(page: Page, testName: string): void {
  const diagnostics = runtimeDiagnosticsByPage.get(page)
  if (!diagnostics) {
    expect(diagnostics, `${testName} did not install browser runtime diagnostics collection`).toBeDefined()
    return
  }
  const summary = diagnostics.map(({ source, message }) => `${source}: ${message}`).join('\n')
  expect(diagnostics, `${testName} emitted browser runtime diagnostics:\n${summary}`).toEqual([])
}

mkdirSync(resolve(EVIDENCE_DIR, 'screenshots'), { recursive: true })

async function fulfillJson(route: Route, value: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(value),
  })
}

async function prepareControlledPage(page: Page, authenticated: boolean): Promise<void> {
  collectRuntimeDiagnostics(page)
  page.on('requestfailed', request => {
    console.error('[style-regression request failed]', request.url(), request.failure()?.errorText)
  })
  await page.addInitScript((isAuthenticated) => {
    window.localStorage.setItem('locale', 'zh-CN')
    if (isAuthenticated) {
      window.sessionStorage.setItem('auth', JSON.stringify({
        token: 'tailwind-style-preview-token',
        refreshToken: null,
      }))
    } else {
      window.sessionStorage.removeItem('auth')
    }
  }, authenticated)

  await page.route('**/*', async (route) => {
    const requestUrl = new URL(route.request().url())
    if (requestUrl.origin !== 'http://127.0.0.1:4187') {
      await route.abort()
      return
    }
    if (requestUrl.pathname.startsWith('/api/v1/')) {
      if (requestUrl.pathname.endsWith('/auth/login')) {
        await fulfillJson(route, { access_token: 'tailwind-style-preview-token', token_type: 'bearer' })
        return
      }
      if (requestUrl.pathname.endsWith('/auth/me')) {
        await fulfillJson(route, USER)
        return
      }
      if (requestUrl.pathname.includes('/workspace/')) {
        await fulfillJson(route, { total: 0, items: [], skip: 0, limit: 50 })
        return
      }
      if (requestUrl.pathname.endsWith('/me/ai/available-models')) {
        await fulfillJson(route, { providers: [], models: [], preferences: { provider: null, model: null } })
        return
      }
      if (requestUrl.pathname.endsWith('/me/ai/usage')) {
        await fulfillJson(route, {
          summary: { total_calls: 0, failed_calls: 0, total_tokens: 0, estimated_cost_usd: 0 },
          by_day: [],
          by_service: [],
          by_model: [],
        })
        return
      }
      await fulfillJson(route, { total: 0, items: [], skip: 0, limit: 50 })
      return
    }
    if (requestUrl.pathname === '/ws' || requestUrl.pathname.startsWith('/ws/')) {
      await route.abort()
      return
    }
    await route.continue()
  })
}

test.afterEach(async ({ page }, testInfo) => {
  assertNoRuntimeDiagnostics(page, testInfo.title)
})

async function selectTheme(page: Page, themeLabel: string): Promise<void> {
  const themeLabelLocator = page.getByText(themeLabel, { exact: true })
  const themeMenu = page.locator('.el-dropdown__popper').filter({ has: themeLabelLocator })

  await page.locator('.theme-icon').click()
  await expect(themeMenu).toBeVisible()
  await themeLabelLocator.click()
  await expect(themeMenu).toBeHidden()
}

async function saveScreenshot(page: Page, projectName: string, name: string): Promise<void> {
  await page.screenshot({
    path: resolve(EVIDENCE_DIR, 'screenshots', `${projectName}-${name}`),
    fullPage: true,
  })
}

async function expectVisiblePrefixIcons(container: Locator, count: number): Promise<void> {
  const icons = container.locator('.el-input__prefix svg')
  await expect(icons).toHaveCount(count)

  for (let index = 0; index < count; index += 1) {
    const icon = icons.nth(index)
    await expect(icon).toBeVisible()
    const pathData = await icon.locator('path').first().getAttribute('d')
    expect(pathData?.trim()).toBeTruthy()
  }
}

async function readResponsiveSassStyles(page: Page) {
  return page.evaluate(() => {
    const container = document.createElement('div')
    container.className = 'page-container'
    container.style.cssText = 'position:fixed;left:-10000px;top:0;width:200px;height:1px'

    const form = document.createElement('div')
    form.className = 'form-row'
    form.style.cssText = 'position:fixed;left:-10000px;top:0;width:200px;height:1px'

    const chart = document.createElement('div')
    chart.className = 'chart-container'
    chart.style.cssText = 'position:fixed;left:-10000px;top:0;width:200px'

    const mobileNav = document.createElement('div')
    mobileNav.className = 'mobile-nav'
    mobileNav.style.cssText = 'position:fixed;left:-10000px;top:0;width:200px;height:1px'

    document.body.append(container, form, chart, mobileNav)
    const values = {
      pagePadding: getComputedStyle(container).padding,
      formDirection: getComputedStyle(form).flexDirection,
      formGap: getComputedStyle(form).gap,
      chartHeight: getComputedStyle(chart).height,
      mobileNavDisplay: getComputedStyle(mobileNav).display,
      desktopSidebarDisplay: getComputedStyle(document.querySelector('.app-sidebar-desktop')!).display,
    }
    container.remove()
    form.remove()
    chart.remove()
    mobileNav.remove()
    return values
  })
}

async function readWorkspaceStyles(page: Page) {
  return page.locator('[data-test="workspace-hero"]').evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      borderColor: style.borderTopColor,
      borderWidth: style.borderTopWidth,
      borderRadius: style.borderTopLeftRadius,
      boxShadow: style.boxShadow,
      backgroundColor: style.backgroundColor,
    }
  })
}

test('login form keeps light and dark visual states on desktop and mobile', async ({ page }) => {
  await prepareControlledPage(page, false)
  await page.goto('/login')
  const loginForm = page.getByRole('form', { name: '登录' })
  await expect(loginForm).toBeVisible()
  await expectVisiblePrefixIcons(loginForm, 2)

  const loginCard = page.locator('.auth-form-card')
  const lightCardStyle = await loginCard.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      borderWidth: style.borderTopWidth,
      borderColor: style.borderTopColor,
      borderRadius: style.borderTopLeftRadius,
      boxShadow: style.boxShadow,
      backgroundColor: style.backgroundColor,
    }
  })
  expect(lightCardStyle.borderWidth).toBe('1px')
  expect(lightCardStyle.borderRadius).toBe('8px')
  expect(lightCardStyle.boxShadow).not.toBe('none')
  await page.getByLabel('用户名').fill('preview-user')
  await page.getByLabel('密码').fill('preview-password')
  await saveScreenshot(page, test.info().project.name, 'login-light-desktop.png')

  await selectTheme(page, '黑曜')
  await expect(page.locator('html')).toHaveClass(/dark/)
  const darkCardStyle = await loginCard.evaluate((element) => {
    const style = getComputedStyle(element)
    return { backgroundColor: style.backgroundColor, borderColor: style.borderTopColor }
  })
  expect(darkCardStyle.backgroundColor).not.toBe(lightCardStyle.backgroundColor)
  expect(darkCardStyle.borderColor).not.toBe(lightCardStyle.borderColor)
  await saveScreenshot(page, test.info().project.name, 'login-dark-desktop.png')

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(loginForm).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await saveScreenshot(page, test.info().project.name, 'login-dark-mobile.png')
})

test('register form renders all four input prefix icons', async ({ page }) => {
  await prepareControlledPage(page, false)
  await page.goto('/register')
  const registerForm = page.locator('form.auth-form')
  await expect(registerForm).toBeVisible()
  await expectVisiblePrefixIcons(registerForm, 4)
})

test('workspace layout, create form, utility compatibility and dark theme remain usable', async ({ page }) => {
  await prepareControlledPage(page, true)
  await page.goto('/research/workspaces')
  const workspaceHero = page.locator('[data-test="workspace-hero"]')
  await expect(workspaceHero).toBeVisible()

  const lightStyles = await readWorkspaceStyles(page)
  expect(lightStyles.borderWidth).toBe('1px')
  expect(lightStyles.boxShadow).not.toBe('none')
  await saveScreenshot(page, test.info().project.name, 'workspace-light-desktop.png')

  await page.locator('.workspace-hero-actions').getByRole('button').first().click()
  const createDialog = page.getByRole('dialog')
  await expect(createDialog).toBeVisible()
  await expect(createDialog.locator('input').first()).toBeVisible()
  await expect(createDialog.locator('textarea').first()).toBeVisible()
  await createDialog.getByRole('button', { name: '取消' }).click()

  const lightPlaceholder = await page.evaluate(() => {
    const input = document.createElement('input')
    input.placeholder = 'Placeholder style check'
    document.body.append(input)
    const style = getComputedStyle(input, '::placeholder')
    const values = { color: style.color, opacity: style.opacity }
    input.remove()
    const declarations: Array<{ selector: string; color: string; opacity: string }> = []
    const visitRules = (rules: CSSRuleList) => {
      for (const rule of Array.from(rules)) {
        if ('selectorText' in rule && 'style' in rule) {
          const styleRule = rule as CSSStyleRule
          if (styleRule.selectorText.includes('input::placeholder')) {
            declarations.push({
              selector: styleRule.selectorText,
              color: styleRule.style.color,
              opacity: styleRule.style.opacity,
            })
          }
        }
        if ('cssRules' in rule) {
          visitRules((rule as CSSGroupingRule).cssRules)
        }
      }
    }
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        visitRules(sheet.cssRules)
      } catch {
        // Cross-origin stylesheets cannot be inspected; the app stylesheet is same-origin.
      }
    }
    return { ...values, declarations }
  })
  expect(lightPlaceholder.declarations).toContainEqual({
    selector: expect.stringContaining('input::placeholder'),
    color: 'rgb(156, 163, 175)',
    opacity: '1',
  })
  if (!test.info().project.name.startsWith('webkit')) {
    expect({ color: lightPlaceholder.color, opacity: lightPlaceholder.opacity }).toEqual({
      color: 'rgb(156, 163, 175)',
      opacity: '1',
    })
  }

  await selectTheme(page, '黑曜')
  await expect(page.locator('html')).toHaveClass(/dark/)
  const darkStyles = await readWorkspaceStyles(page)
  expect(darkStyles.borderWidth).toBe('1px')
  expect(darkStyles.boxShadow).not.toBe('none')
  expect(darkStyles.backgroundColor).not.toBe(lightStyles.backgroundColor)
  await saveScreenshot(page, test.info().project.name, 'workspace-dark-desktop.png')

  const utilityStyle = await page.evaluate(() => {
    const probe = document.createElement('div')
    probe.className = 'border rounded shadow-sm ring-2 ring-blue-200'
    probe.style.cssText = 'position:absolute;left:-10000px;top:0;width:16px;height:16px'
    document.body.append(probe)
    const style = getComputedStyle(probe)
    const values = {
      borderWidth: style.borderTopWidth,
      borderColor: style.borderTopColor,
      borderRadius: style.borderTopLeftRadius,
      shadow: style.getPropertyValue('--tw-shadow').trim(),
      ringShadow: style.getPropertyValue('--tw-ring-shadow').trim(),
    }
    probe.remove()

    const spacingProbe = document.createElement('div')
    spacingProbe.className = 'space-y-2'
    spacingProbe.style.cssText = 'position:absolute;left:-10000px;top:0;width:16px'
    const spacingChildren = Array.from({ length: 3 }, () => {
      const child = document.createElement('div')
      child.style.cssText = 'width:16px;height:10px'
      spacingProbe.append(child)
      return child
    })
    document.body.append(spacingProbe)
    const spacing = {
      firstGap: spacingChildren[1].getBoundingClientRect().top - spacingChildren[0].getBoundingClientRect().bottom,
      secondGap: spacingChildren[2].getBoundingClientRect().top - spacingChildren[1].getBoundingClientRect().bottom,
      firstMarginBlockEnd: getComputedStyle(spacingChildren[0]).marginBlockEnd,
    }
    spacingProbe.remove()

    const divideProbe = document.createElement('div')
    divideProbe.className = 'divide-y divide-slate-200'
    divideProbe.style.cssText = 'position:absolute;left:-10000px;top:0;width:16px'
    const divideRows = Array.from({ length: 3 }, () => {
      const row = document.createElement('div')
      row.style.cssText = 'width:16px;height:10px'
      divideProbe.append(row)
      return row
    })
    document.body.append(divideProbe)
    const divideColorProbe = document.createElement('div')
    divideColorProbe.style.borderColor = 'var(--color-slate-200)'
    document.body.append(divideColorProbe)
    const divide = {
      firstBottomWidth: getComputedStyle(divideRows[0]).borderBottomWidth,
      secondTopWidth: getComputedStyle(divideRows[1]).borderTopWidth,
      secondBottomWidth: getComputedStyle(divideRows[1]).borderBottomWidth,
      secondTopColor: getComputedStyle(divideRows[1]).borderTopColor,
      tokenColor: getComputedStyle(divideColorProbe).borderTopColor,
    }
    divideProbe.remove()
    divideColorProbe.remove()

    return { ...values, spacing, divide }
  })
  expect(utilityStyle.borderWidth).toBe('1px')
  expect(utilityStyle.borderColor).toBe('rgb(229, 231, 235)')
  expect(utilityStyle.borderRadius).toBe('4px')
  expect(utilityStyle.shadow).toContain('0 1px 2px')
  expect(utilityStyle.ringShadow).toContain('2px')
  expect(utilityStyle.spacing).toEqual({
    firstGap: 8,
    secondGap: 8,
    firstMarginBlockEnd: '0px',
  })
  expect(utilityStyle.divide).toMatchObject({
    firstBottomWidth: '0px',
    secondTopWidth: '1px',
    secondBottomWidth: '0px',
  })
  expect(utilityStyle.divide.secondTopColor).toBe(utilityStyle.divide.tokenColor)

  const desktopSassStyles = await readResponsiveSassStyles(page)
  expect(desktopSassStyles).toMatchObject({
    pagePadding: '20px',
    formDirection: 'row',
    formGap: '16px',
    chartHeight: '400px',
  })

  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  const mobileSassStyles = await readResponsiveSassStyles(page)
  expect(mobileSassStyles).toMatchObject({
    pagePadding: '12px',
    formDirection: 'column',
    formGap: '12px',
    chartHeight: '300px',
    mobileNavDisplay: 'flex',
    desktopSidebarDisplay: 'none',
  })
  await saveScreenshot(page, test.info().project.name, 'workspace-dark-mobile.png')

  await page.evaluate(() => {
    const probe = document.createElement('div')
    probe.id = 'tailwind-hover-shadow-probe'
    probe.className = 'hover:shadow-md'
    probe.style.cssText = 'position:fixed;left:8px;top:8px;width:40px;height:40px;z-index:2147483647'
    document.body.append(probe)
  })
  const hoverShadowProbe = page.locator('#tailwind-hover-shadow-probe')
  await hoverShadowProbe.hover()
  const hoverShadow = await hoverShadowProbe.evaluate((element) => getComputedStyle(element).getPropertyValue('--tw-shadow').trim())
  expect(hoverShadow).toContain('0 4px 6px')
  await hoverShadowProbe.evaluate((element) => element.remove())

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(workspaceHero).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await saveScreenshot(page, test.info().project.name, 'workspace-dark-mobile.png')
})
