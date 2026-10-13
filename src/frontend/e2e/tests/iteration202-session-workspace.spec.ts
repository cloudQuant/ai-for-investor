import { expect, test, type Page, type Request, type Route } from '@playwright/test'

const TOKEN_A = 'iteration202-fixture-token-a'
const TOKEN_B = 'iteration202-fixture-token-b'

type Deferred = {
  promise: Promise<void>
  resolve: () => void
}

type ApiHandler = (request: Request, route: Route) => Promise<void>
type XhrResponseBarrierOptions = {
  token: string
  paths: string[]
  status: number
  marker: string
}
type RuntimeDiagnostic = { source: string; message: string }

const runtimeDiagnosticsByPage = new WeakMap<Page, RuntimeDiagnostic[]>()

function getFixtureAppOrigin(): URL {
  const configuredBaseURL = test.info().project.use.baseURL
  if (typeof configuredBaseURL !== 'string' || configuredBaseURL.trim() === '') {
    throw new Error('The current Playwright project must configure an absolute HTTP(S) baseURL.')
  }

  let appOrigin: URL
  try {
    appOrigin = new URL(configuredBaseURL)
  } catch {
    throw new Error('The current Playwright project baseURL must be an absolute HTTP(S) URL.')
  }

  const hostname = appOrigin.hostname.replace(/^\[|\]$/g, '')
  const isLoopbackHost = ['127.0.0.1', 'localhost', '::1'].includes(hostname)
  if (!['http:', 'https:'].includes(appOrigin.protocol) || !isLoopbackHost) {
    throw new Error('The fixture API may only run against an HTTP(S) loopback baseURL.')
  }

  return new URL(appOrigin.origin)
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

function deferred(): Deferred {
  let resolve!: () => void
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

async function installXhrResponseProcessingBarrier(
  page: Page,
  options: XhrResponseBarrierOptions,
): Promise<void> {
  await page.addInitScript((barrier) => {
    const authorizationByRequest = new WeakMap<XMLHttpRequest, string>()
    const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader
    XMLHttpRequest.prototype.setRequestHeader = function (name: string, value: string) {
      if (name.toLowerCase() === 'authorization') {
        authorizationByRequest.set(this, value)
      }
      return originalSetRequestHeader.call(this, name, value)
    }

    let handlerPrototype: object | null = XMLHttpRequest.prototype
    while (
      handlerPrototype
      && !Object.prototype.hasOwnProperty.call(handlerPrototype, 'onloadend')
    ) {
      handlerPrototype = Object.getPrototypeOf(handlerPrototype)
    }

    if (!handlerPrototype) {
      throw new Error('XMLHttpRequest loadend handler descriptor is unavailable.')
    }
    const descriptor = Object.getOwnPropertyDescriptor(handlerPrototype, 'onloadend')
    if (!descriptor?.get || !descriptor.set) {
      throw new Error('XMLHttpRequest loadend handler is not instrumentable.')
    }

    Object.defineProperty(handlerPrototype, 'onloadend', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get() {
        return descriptor.get?.call(this)
      },
      set(handler: unknown) {
        if (typeof handler !== 'function') {
          descriptor.set?.call(this, handler)
          return
        }

        const xhr = this as XMLHttpRequest
        descriptor.set?.call(xhr, function (event: ProgressEvent<EventTarget>) {
          Reflect.apply(handler, xhr, [event])
          const responsePath = xhr.responseURL ? new URL(xhr.responseURL).pathname : ''
          if (
            authorizationByRequest.get(xhr) === `Bearer ${barrier.token}`
            && barrier.paths.includes(responsePath)
            && xhr.status === barrier.status
          ) {
            // Queue a task after Axios settles the XHR. The browser drains the
            // promise chain (response interceptors and store continuation)
            // before this marker runs, so tests can fence processing without
            // an arbitrary delay.
            const channel = new MessageChannel()
            channel.port1.onmessage = () => {
              channel.port1.close()
              channel.port2.close()
              const currentCount = Number(Reflect.get(window, barrier.marker) || 0)
              Reflect.set(window, barrier.marker, currentCount + 1)
            }
            channel.port2.postMessage(null)
          }
        })
      },
    })
    Reflect.set(window, barrier.marker, 0)
  }, options)
}

async function xhrResponseProcessedCount(page: Page, marker: string): Promise<number> {
  return page.evaluate((key) => Number(Reflect.get(window, key) || 0), marker)
}

function fixtureUser(username: string) {
  return {
    id: `fixture-${username}`,
    username,
    email: `${username}@example.test`,
    is_active: true,
    is_admin: false,
    created_at: '2026-10-12T00:00:00Z',
  }
}

function fixtureWorkspace(id: string, name: string) {
  return {
    id,
    user_id: 'fixture-user',
    name,
    description: `Synthetic browser fixture ${id}`,
    workspace_type: 'research',
    settings: {},
    trading_config: {},
    unit_count: 1,
    completed_count: 0,
    status: 'idle',
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:00:00Z',
  }
}

function fixtureUnit(id: string, workspaceId: string, name: string) {
  return {
    id,
    workspace_id: workspaceId,
    group_name: 'Fixture group',
    strategy_id: 'fixture-strategy',
    strategy_name: name,
    symbol: '000001.SZ',
    symbol_name: 'Fixture symbol',
    timeframe: '1d',
    timeframe_n: 1,
    category: 'fixture',
    sort_order: 0,
    data_config: {},
    unit_settings: {},
    params: {},
    optimization_config: {},
    trading_mode: 'paper',
    gateway_config: {},
    lock_trading: false,
    lock_running: false,
    trading_instance_id: null,
    trading_snapshot: {},
    run_status: 'idle',
    run_count: 0,
    last_run_time: null,
    last_task_id: null,
    last_optimization_task_id: null,
    bar_count: null,
    metrics_snapshot: {},
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:00:00Z',
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installFixtureApi(page: Page, handler: ApiHandler): Promise<void> {
  const appOrigin = getFixtureAppOrigin()
  collectRuntimeDiagnostics(page)
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())

    if (url.origin !== appOrigin.origin) {
      await route.abort()
      return
    }

    if (url.pathname.startsWith('/api/')) {
      await handler(request, route)
      return
    }

    await route.continue()
  })

  // The fixture pages make no websocket calls. Closing local sockets prevents
  // Vite HMR messages from reloading the application during a controlled race.
  const webSocketOrigin = new URL(appOrigin)
  webSocketOrigin.protocol = appOrigin.protocol === 'https:' ? 'wss:' : 'ws:'
  await page.routeWebSocket(`${webSocketOrigin.origin}/**`, (socket) => {
    socket.close()
  })
}

async function installSession(page: Page, token: string): Promise<void> {
  await page.addInitScript((initialToken) => {
    sessionStorage.setItem('auth', JSON.stringify({ token: initialToken, refreshToken: null }))
    Reflect.set(window, '__iteration202AuthExpiredEvents', 0)
    window.addEventListener('auth:expired', () => {
      const count = Number(Reflect.get(window, '__iteration202AuthExpiredEvents') || 0)
      Reflect.set(window, '__iteration202AuthExpiredEvents', count + 1)
    })
  }, token)
}

async function tokenInSessionStorage(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const raw = sessionStorage.getItem('auth')
    if (!raw) return null
    const payload = JSON.parse(raw) as { token?: unknown }
    return typeof payload.token === 'string' ? payload.token : null
  })
}

async function expiredEventCount(page: Page): Promise<number> {
  return page.evaluate(() => Number(Reflect.get(window, '__iteration202AuthExpiredEvents') || 0))
}

async function navigateInSpa(page: Page, path: string): Promise<void> {
  await page.evaluate(async (target) => {
    const root = document.querySelector('#app') as (HTMLElement & {
      __vue_app__?: {
        config?: { globalProperties?: Record<string, unknown> }
      }
    }) | null
    const router = root?.__vue_app__?.config?.globalProperties?.$router as {
      push?: (path: string) => Promise<unknown>
    } | undefined
    if (!router?.push) {
      throw new Error('Vue Router is not available on the mounted application.')
    }
    await router.push(target)
  }, path)
}

async function readAuthAppState(page: Page): Promise<{
  token: string | null
  identityStatus: string | null
  username: string | null
  currentRoute: string | null
}> {
  return page.evaluate(() => {
    const root = document.querySelector('#app') as (HTMLElement & {
      __vue_app__?: {
        config?: { globalProperties?: Record<string, unknown> }
      }
    }) | null
    const globals = root?.__vue_app__?.config?.globalProperties
    const pinia = globals?.$pinia as { _s?: Map<string, Record<string, unknown>> } | undefined
    const authStore = pinia?._s?.get('auth')
    const router = globals?.$router as {
      currentRoute?: { value?: { fullPath?: string } }
    } | undefined
    const user = authStore?.user as { username?: unknown } | null | undefined
    return {
      token: typeof authStore?.token === 'string' ? authStore.token : null,
      identityStatus: typeof authStore?.identityStatus === 'string' ? authStore.identityStatus : null,
      username: typeof user?.username === 'string' ? user.username : null,
      currentRoute: typeof router?.currentRoute?.value?.fullPath === 'string'
        ? router.currentRoute.value.fullPath
        : null,
    }
  })
}

async function readWorkspaceAppState(page: Page): Promise<{
  workspaces: unknown[]
  currentWorkspaceId: string | null
  units: unknown[]
  selectedUnitIds: string[]
  activeWorkspaceId: string | null
  loading: boolean | null
}> {
  return page.evaluate(() => {
    const root = document.querySelector('#app') as (HTMLElement & {
      __vue_app__?: {
        config?: { globalProperties?: Record<string, unknown> }
      }
    }) | null
    const globals = root?.__vue_app__?.config?.globalProperties
    const pinia = globals?.$pinia as { _s?: Map<string, Record<string, unknown>> } | undefined
    const store = pinia?._s?.get('workspace')
    const currentWorkspace = store?.currentWorkspace as { id?: unknown } | null | undefined
    return {
      workspaces: Array.isArray(store?.workspaces) ? store.workspaces : [],
      currentWorkspaceId: typeof currentWorkspace?.id === 'string' ? currentWorkspace.id : null,
      units: Array.isArray(store?.units) ? store.units : [],
      selectedUnitIds: Array.isArray(store?.selectedUnitIds) ? store.selectedUnitIds as string[] : [],
      activeWorkspaceId: typeof store?.activeWorkspaceId === 'string' ? store.activeWorkspaceId : null,
      loading: typeof store?.loading === 'boolean' ? store.loading : null,
    }
  })
}

async function logOutFromHeader(page: Page): Promise<void> {
  await page.locator('.user-dropdown-trigger').click()
  await page.locator('.el-dropdown-menu__item').last().click()
  await expect(page.getByTestId('login-submit')).toBeVisible()
}

async function loginAsB(page: Page): Promise<void> {
  await page.locator('input[autocomplete="username"]').fill('user-b')
  await page.locator('input[autocomplete="current-password"]').fill('fixture-password')
  await page.getByTestId('login-submit').click()
  await expect(page.locator('.user-dropdown-trigger')).toContainText('user-b')
}

async function fulfillDefaultFixture(request: Request, route: Route): Promise<void> {
  const pathname = new URL(request.url()).pathname
  const method = request.method()

  if (pathname === '/api/v1/auth/me') {
    const username = request.headers().authorization?.endsWith(TOKEN_B) ? 'user-b' : 'user-a'
    await fulfillJson(route, fixtureUser(username))
    return
  }

  if (pathname === '/api/v1/auth/login' && method === 'POST') {
    const payload = request.postDataJSON() as { username?: string }
    await fulfillJson(route, {
      access_token: payload.username === 'user-b' ? TOKEN_B : TOKEN_A,
      token_type: 'bearer',
      expires_in: 3600,
    })
    return
  }

  if (pathname === '/api/v1/workspace/' && method === 'GET') {
    const workspace = request.headers().authorization?.endsWith(TOKEN_B)
      ? fixtureWorkspace('workspace-b', 'Workspace B fixture')
      : fixtureWorkspace('workspace-a', 'Workspace A fixture')
    await fulfillJson(route, { total: 1, items: [workspace] })
    return
  }

  if (pathname === '/api/v1/backtests/' && method === 'GET') {
    await fulfillJson(route, { total: 0, items: [] })
    return
  }

  if (pathname === '/api/v1/strategy/' && method === 'GET') {
    await fulfillJson(route, { total: 0, items: [] })
    return
  }

  if (pathname === '/api/v1/strategy/templates' && method === 'GET') {
    await fulfillJson(route, { total: 0, templates: [] })
    return
  }

  const detailMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)$/)
  if (detailMatch && method === 'GET') {
    const id = decodeURIComponent(detailMatch[1])
    await fulfillJson(route, fixtureWorkspace(id, `Workspace ${id.toUpperCase()} fixture`))
    return
  }

  const unitsMatch = pathname.match(/^\/api\/v1\/workspace\/([^/]+)\/units$/)
  if (unitsMatch && method === 'GET') {
    const id = decodeURIComponent(unitsMatch[1])
    const unit = fixtureUnit(`unit-${id}`, id, `Unit ${id.toUpperCase()} fixture`)
    await fulfillJson(route, { total: 1, items: [unit] })
    return
  }

  if (pathname.endsWith('/status') || pathname.endsWith('/trading/auto-schedule')) {
    await fulfillJson(route, [])
    return
  }

  if (pathname.endsWith('/trading/auto-config')) {
    await fulfillJson(route, { enabled: false })
    return
  }

  if (method === 'POST' && pathname.endsWith('/run')) {
    const body = request.postDataJSON() as { unit_ids?: string[] }
    await fulfillJson(route, {
      results: (body.unit_ids ?? []).map(unit_id => ({ unit_id, status: 'completed' })),
    })
    return
  }

  await fulfillJson(route, {})
}

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === 'passed' && !page.isClosed()) {
    await page.screenshot({ path: testInfo.outputPath('final.png'), fullPage: true })
  }
  assertNoRuntimeDiagnostics(page, testInfo.title)
})

test('AC-D09: retains credentials through 503 and network failures, then confirms identity on retry', async ({ page }) => {
  await installSession(page, TOKEN_A)
  let meCalls = 0
  const workspaceRequests: string[] = []

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    if (pathname === '/api/v1/auth/me') {
      meCalls += 1
      if (meCalls <= 4) {
        await fulfillJson(route, { detail: 'synthetic temporary service failure' }, 503)
      } else if (meCalls <= 8) {
        await route.abort('failed')
      } else {
        await fulfillJson(route, fixtureUser('user-a'))
      }
      return
    }
    if (pathname.startsWith('/api/v1/workspace/')) {
      workspaceRequests.push(request.headers().authorization ?? '')
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces')
  await expect(page.getByTestId('identity-retry-panel')).toBeVisible({ timeout: 60_000 })
  expect(meCalls).toBe(4)
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_A)
  expect(workspaceRequests).toEqual([])
  await expect(page.getByTestId('login-submit')).toHaveCount(0)

  await page.getByTestId('identity-retry').click()
  await expect.poll(() => meCalls).toBe(8)
  await expect(page.getByTestId('identity-retry-panel')).toBeVisible({ timeout: 60_000 })
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_A)
  await expect(page.getByTestId('login-submit')).toHaveCount(0)

  await page.getByTestId('identity-retry').click()
  await expect.poll(() => meCalls).toBe(9)
  await expect.poll(async () => (await readAuthAppState(page)).currentRoute)
    .toBe('/research/workspaces')
  await expect(page.locator('.user-dropdown-trigger')).toContainText('user-a')
  await expect(page).toHaveURL(/\/research\/workspaces$/)
  expect(meCalls).toBe(9)
  expect(workspaceRequests).toEqual([`Bearer ${TOKEN_A}`])
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_A)
})

test('AC-D09: a real startup 401 clears the expired identity and returns to the login form', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const protectedRequests: string[] = []

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    if (pathname === '/api/v1/auth/me') {
      await fulfillJson(route, { detail: 'synthetic expired token' }, 401)
      return
    }
    if (pathname.startsWith('/api/v1/workspace/')) {
      protectedRequests.push(pathname)
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces')
  await expect(page.getByTestId('login-submit')).toBeVisible()
  await expect(page.getByTestId('identity-retry-panel')).toHaveCount(0)
  expect(await tokenInSessionStorage(page)).toBeNull()
  expect(await expiredEventCount(page)).toBe(1)
  expect(protectedRequests).toEqual([])
})

test('AC-D10: a late A 401 cannot log out B, while B own 401 still expires B', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const aResponseProcessedMarker = '__iteration202AWorkspace401Processed'
  await installXhrResponseProcessingBarrier(page, {
    token: TOKEN_A,
    paths: ['/api/v1/workspace/'],
    status: 401,
    marker: aResponseProcessedMarker,
  })
  const aListStarted = deferred()
  const aListReleased = deferred()
  let bListCalls = 0

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    const authorization = request.headers().authorization ?? ''

    if (pathname === '/api/v1/workspace/' && authorization === `Bearer ${TOKEN_A}`) {
      aListStarted.resolve()
      await aListReleased.promise
      await fulfillJson(route, { detail: 'late A unauthorized' }, 401)
      return
    }
    if (pathname === '/api/v1/workspace/' && authorization === `Bearer ${TOKEN_B}`) {
      bListCalls += 1
      if (bListCalls === 2) {
        await fulfillJson(route, { detail: 'current B unauthorized' }, 401)
      } else {
        await fulfillDefaultFixture(request, route)
      }
      return
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces')
  await aListStarted.promise
  await logOutFromHeader(page)
  await loginAsB(page)
  await navigateInSpa(page, '/research/workspaces')
  await expect(page.getByText('Workspace B fixture')).toBeVisible()

  aListReleased.resolve()
  await expect.poll(() => xhrResponseProcessedCount(page, aResponseProcessedMarker)).toBe(1)
  await expect(page.locator('.user-dropdown-trigger')).toContainText('user-b')
  await expect(page.getByText('Workspace B fixture')).toBeVisible()
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_B)
  expect(await expiredEventCount(page)).toBe(0)

  await navigateInSpa(page, '/')
  await navigateInSpa(page, '/research/workspaces')
  await expect(page.getByTestId('login-submit')).toBeVisible()
  expect(await tokenInSessionStorage(page)).toBeNull()
  expect(await expiredEventCount(page)).toBe(1)
})

test('AC-D10: a delayed A retry keeps A authorization and cannot replace B workspace state', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const aRetryResponseProcessedMarker = '__iteration202ARetryResponseProcessed'
  await installXhrResponseProcessingBarrier(page, {
    token: TOKEN_A,
    paths: ['/api/v1/workspace/'],
    status: 200,
    marker: aRetryResponseProcessedMarker,
  })
  const aRetryStarted = deferred()
  const aRetryReleased = deferred()
  let aListCalls = 0

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    const authorization = request.headers().authorization ?? ''

    if (pathname === '/api/v1/workspace/' && authorization === `Bearer ${TOKEN_A}`) {
      aListCalls += 1
      if (aListCalls === 1) {
        await fulfillJson(route, { detail: 'synthetic retry fixture' }, 503)
      } else {
        aRetryStarted.resolve()
        await aRetryReleased.promise
        await fulfillDefaultFixture(request, route)
      }
      return
    }

    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces')
  await aRetryStarted.promise
  await logOutFromHeader(page)
  await loginAsB(page)
  await navigateInSpa(page, '/research/workspaces')
  await expect(page.getByText('Workspace B fixture')).toBeVisible()
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_B)

  aRetryReleased.resolve()
  await expect.poll(() => xhrResponseProcessedCount(page, aRetryResponseProcessedMarker)).toBe(1)
  await expect(page.getByText('Workspace B fixture')).toBeVisible()
  await expect(page.locator('.user-dropdown-trigger')).toContainText('user-b')
  await expect(page.getByText('Workspace A fixture')).toHaveCount(0)
  expect(await tokenInSessionStorage(page)).toBe(TOKEN_B)
  expect(await expiredEventCount(page)).toBe(0)
})

test('AC-D10: logout clears A workspace data before B opens the same workspace route', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const bDetailStarted = deferred()
  const bUnitsStarted = deferred()
  const releaseBDetail = deferred()
  const releaseBUnits = deferred()

  await installFixtureApi(page, async (request, route) => {
    const url = new URL(request.url())
    const pathname = url.pathname
    const authorization = request.headers().authorization ?? ''
    const isB = authorization === `Bearer ${TOKEN_B}`

    if (pathname === '/api/v1/auth/me') {
      await fulfillJson(route, fixtureUser(isB ? 'user-b' : 'user-a'))
      return
    }
    if (pathname === '/api/v1/auth/login' && request.method() === 'POST') {
      await fulfillJson(route, {
        access_token: TOKEN_B,
        token_type: 'bearer',
        expires_in: 3600,
      })
      return
    }

    if (pathname === '/api/v1/workspace/' && request.method() === 'GET') {
      await fulfillJson(route, {
        total: 1,
        items: [fixtureWorkspace('shared', `Workspace ${isB ? 'B' : 'A'} fixture`)],
      })
      return
    }

    const match = pathname.match(/^\/api\/v1\/workspace\/shared(?:\/(units))?$/)
    if (request.method() === 'GET' && match) {
      const resource = match[1] ? 'units' : 'detail'
      if (isB) {
        if (resource === 'detail') {
          bDetailStarted.resolve()
          await releaseBDetail.promise
        } else {
          bUnitsStarted.resolve()
          await releaseBUnits.promise
        }
      }

      if (resource === 'units') {
        await fulfillJson(route, {
          total: 1,
          items: [fixtureUnit('unit-shared', 'shared', `Unit ${isB ? 'B' : 'A'} fixture`)],
        })
      } else {
        await fulfillJson(route, fixtureWorkspace(
          'shared',
          `Workspace ${isB ? 'B' : 'A'} fixture`,
        ))
      }
      return
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces')
  await expect(page.locator('.workspace-card-name')).toHaveText('Workspace A fixture')
  await navigateInSpa(page, '/research/workspaces/shared')
  await expect(page).toHaveURL(/\/research\/workspaces\/shared$/)
  await expect(page.locator('#workspace-detail-title')).toHaveText('Workspace A fixture')
  const aRow = page.getByRole('row').filter({ hasText: 'Unit A fixture' })
  await expect(aRow).toBeVisible()
  await aRow.locator('.el-checkbox__inner').click()

  await logOutFromHeader(page)
  expect(await readWorkspaceAppState(page)).toMatchObject({
    workspaces: [],
    currentWorkspaceId: null,
    units: [],
    selectedUnitIds: [],
    activeWorkspaceId: null,
  })
  await loginAsB(page)
  await navigateInSpa(page, '/research/workspaces/shared')
  await Promise.all([bDetailStarted.promise, bUnitsStarted.promise])

  await expect(page.locator('body')).not.toContainText('Workspace A fixture')
  await expect(page.locator('body')).not.toContainText('Unit A fixture')
  expect(await readWorkspaceAppState(page)).toMatchObject({
    workspaces: [],
    currentWorkspaceId: null,
    units: [],
    selectedUnitIds: [],
    activeWorkspaceId: 'shared',
  })

  releaseBDetail.resolve()
  await expect(page.locator('#workspace-detail-title')).toHaveText('Workspace B fixture')
  releaseBUnits.resolve()
  await expect(page.getByRole('row').filter({ hasText: 'Unit B fixture' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Unit A fixture' })).toHaveCount(0)
})

test('AC-D11: late A detail and units cannot replace B during same-route workspace navigation', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const requests = new Map<string, Deferred>()
  const started = new Map<string, Deferred>()
  for (const workspaceId of ['a', 'b']) {
    requests.set(`${workspaceId}:detail`, deferred())
    requests.set(`${workspaceId}:units`, deferred())
    started.set(`${workspaceId}:detail`, deferred())
    started.set(`${workspaceId}:units`, deferred())
  }

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    const match = pathname.match(/^\/api\/v1\/workspace\/([ab])(?:\/(units))?$/)
    if (request.method() === 'GET' && match) {
      const workspaceId = match[1]
      const resource = match[2] ? 'units' : 'detail'
      const key = `${workspaceId}:${resource}`
      started.get(key)?.resolve()
      await requests.get(key)?.promise
      if (resource === 'units') {
        await fulfillJson(route, {
          total: 1,
          items: [fixtureUnit(`unit-${workspaceId}`, workspaceId, `Unit ${workspaceId.toUpperCase()} fixture`)],
        })
      } else {
        await fulfillJson(route, fixtureWorkspace(workspaceId, `Workspace ${workspaceId.toUpperCase()} fixture`))
      }
      return
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces/a')
  await Promise.all([
    started.get('a:detail')?.promise,
    started.get('a:units')?.promise,
  ])

  await navigateInSpa(page, '/research/workspaces/b')
  await Promise.all([
    started.get('b:detail')?.promise,
    started.get('b:units')?.promise,
  ])

  requests.get('a:detail')?.resolve()
  requests.get('a:units')?.resolve()
  await expect(page.locator('.workspace-detail-state')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('Workspace A fixture')
  await expect(page.locator('body')).not.toContainText('Unit A fixture')

  requests.get('b:detail')?.resolve()
  await expect(page.locator('#workspace-detail-title')).toHaveText('Workspace B fixture')
  await expect.poll(async () => (await readWorkspaceAppState(page)).loading).toBe(true)

  requests.get('b:units')?.resolve()
  const bRow = page.getByRole('row').filter({ hasText: 'Unit B fixture' })
  await expect(bRow).toBeVisible()
  await bRow.locator('.el-checkbox__inner').click()
  await expect(page.getByRole('row').filter({ hasText: 'Unit A fixture' })).toHaveCount(0)

  const runRequest = page.waitForRequest(request =>
    request.url().endsWith('/api/v1/workspace/b/run') && request.method() === 'POST',
  )
  await page.locator('.workspace-units-tab .el-button-group').first().locator('button').first().click()
  const run = await runRequest
  expect(run.postDataJSON()).toEqual({ unit_ids: ['unit-b'], parallel: false })

  expect(await readWorkspaceAppState(page)).toMatchObject({
    loading: false,
    activeWorkspaceId: 'b',
    selectedUnitIds: ['unit-b'],
  })
})

test('AC-D11: B detail and units remain active when they finish before late A responses', async ({ page }) => {
  await installSession(page, TOKEN_A)
  const aResponsesProcessedMarker = '__iteration202AWorkspaceResponsesProcessed'
  await installXhrResponseProcessingBarrier(page, {
    token: TOKEN_A,
    paths: ['/api/v1/workspace/a', '/api/v1/workspace/a/units'],
    status: 200,
    marker: aResponsesProcessedMarker,
  })

  const requests = new Map<string, Deferred>()
  const started = new Map<string, Deferred>()
  for (const workspaceId of ['a', 'b']) {
    requests.set(`${workspaceId}:detail`, deferred())
    requests.set(`${workspaceId}:units`, deferred())
    started.set(`${workspaceId}:detail`, deferred())
    started.set(`${workspaceId}:units`, deferred())
  }

  await installFixtureApi(page, async (request, route) => {
    const pathname = new URL(request.url()).pathname
    const match = pathname.match(/^\/api\/v1\/workspace\/([ab])(?:\/(units))?$/)
    if (request.method() === 'GET' && match) {
      const workspaceId = match[1]
      const resource = match[2] ? 'units' : 'detail'
      const key = `${workspaceId}:${resource}`
      started.get(key)?.resolve()
      await requests.get(key)?.promise
      if (resource === 'units') {
        await fulfillJson(route, {
          total: 1,
          items: [fixtureUnit(
            `unit-${workspaceId}`,
            workspaceId,
            `Unit ${workspaceId.toUpperCase()} fixture`,
          )],
        })
      } else {
        await fulfillJson(route, fixtureWorkspace(
          workspaceId,
          `Workspace ${workspaceId.toUpperCase()} fixture`,
        ))
      }
      return
    }
    await fulfillDefaultFixture(request, route)
  })

  await page.goto('/research/workspaces/a')
  await Promise.all([
    started.get('a:detail')?.promise,
    started.get('a:units')?.promise,
  ])

  await navigateInSpa(page, '/research/workspaces/b')
  await Promise.all([
    started.get('b:detail')?.promise,
    started.get('b:units')?.promise,
  ])

  requests.get('b:detail')?.resolve()
  requests.get('b:units')?.resolve()
  await expect(page.locator('#workspace-detail-title')).toHaveText('Workspace B fixture')
  const bRow = page.getByRole('row').filter({ hasText: 'Unit B fixture' })
  await expect(bRow).toBeVisible()
  await expect.poll(async () => (await readWorkspaceAppState(page)).loading).toBe(false)
  await bRow.locator('.el-checkbox__inner').click()
  await expect.poll(async () => (await readWorkspaceAppState(page)).selectedUnitIds)
    .toEqual(['unit-b'])

  requests.get('a:detail')?.resolve()
  requests.get('a:units')?.resolve()
  await expect.poll(() => xhrResponseProcessedCount(page, aResponsesProcessedMarker)).toBe(2)

  await expect(page.locator('#workspace-detail-title')).toHaveText('Workspace B fixture')
  await expect(bRow).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Unit A fixture' })).toHaveCount(0)
  expect(await readWorkspaceAppState(page)).toMatchObject({
    loading: false,
    currentWorkspaceId: 'b',
    activeWorkspaceId: 'b',
    selectedUnitIds: ['unit-b'],
  })

  const runRequest = page.waitForRequest(request =>
    request.url().endsWith('/api/v1/workspace/b/run') && request.method() === 'POST',
  )
  await page.locator('.workspace-units-tab .el-button-group').first().locator('button').first().click()
  const run = await runRequest
  expect(run.postDataJSON()).toEqual({ unit_ids: ['unit-b'], parallel: false })
})
