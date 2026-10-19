import { expect, test } from '@playwright/test'

test('Gateway health page reads an authorized service projection only on submit', async ({ page }) => {
  const token = process.env.AFI09_E2E_ACCESS_TOKEN
  const accountRef = process.env.AFI09_E2E_ACCOUNT_REF ?? 'acct-a'
  const credentialRef = process.env.AFI09_E2E_CREDENTIAL_REF
  const syntheticSecret = process.env.AFI09_E2E_SYNTHETIC_SECRET

  expect(token).toBeTruthy()
  expect(credentialRef).toBeTruthy()
  expect(syntheticSecret).toBeTruthy()

  const healthRequests: string[] = []
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/api/v1/service-gateway/')) {
      healthRequests.push(request.url())
    }
  })

  await page.addInitScript(({ accessToken }) => {
    window.sessionStorage.setItem(
      'auth',
      JSON.stringify({ token: accessToken, refreshToken: null }),
    )
    window.localStorage.setItem('locale', 'en-US')
  }, { accessToken: token! })
  await page.route('**/api/v1/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'afi-user-a',
        username: 'afi-user-a',
        email: 'afi-user-a@example.test',
        is_active: true,
        is_admin: false,
        created_at: '2026-10-17T00:00:00Z',
      }),
    })
  })

  await page.goto('/trading/gateway-health')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator('#service-gateway-account-ref')).toBeVisible()
  expect(healthRequests).toEqual([])

  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `/api/v1/service-gateway/accounts/${accountRef}/health`,
  )
  await page.locator('#service-gateway-account-ref').fill(accountRef)
  await page.locator('.service-gateway-health__selector button[type="submit"]').click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  expect(healthRequests).toHaveLength(1)

  const projection = await response.json() as {
    account_ref: string
    service_connection: { rpc_status: string }
    gateway_session: { status: string; session_generation: string | null }
    account_observation: { status: string; quality: string; same_session_generation: boolean | null }
    market_data_feed: { status: string }
  }
  expect(projection).toMatchObject({
    account_ref: accountRef,
    service_connection: { rpc_status: 'reachable' },
    gateway_session: { status: 'ready' },
    account_observation: {
      status: 'observed',
      quality: 'fresh',
      same_session_generation: true,
    },
    market_data_feed: { status: 'unobserved' },
  })

  await expect(page.getByTestId('service-connection-status')).toHaveAttribute('data-status', 'reachable')
  await expect(page.getByTestId('gateway-session-status')).toHaveAttribute('data-status', 'ready')
  await expect(page.getByTestId('account-observation-status')).toHaveAttribute('data-status', 'observed')
  await expect(page.getByTestId('market-feed-status')).toHaveAttribute('data-status', 'unobserved')
  const userVisible = await page.locator('body').innerText()
  expect(userVisible).not.toContain(credentialRef!)
  expect(userVisible).not.toContain(syntheticSecret!)
  expect(JSON.stringify(projection)).not.toContain(credentialRef!)
  expect(JSON.stringify(projection)).not.toContain(syntheticSecret!)

  const apiTarget = process.env.AFI09_E2E_API_TARGET
  if (!apiTarget) throw new Error('AFI09_E2E_API_TARGET is required')
  const wsUrl = new URL(
    `/api/v1/service-gateway/ws/accounts/${encodeURIComponent(accountRef)}/health`,
    apiTarget,
  )
  wsUrl.protocol = wsUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  const socketResult = await page.evaluate(async ({ url, accessToken }) => {
    return await new Promise<{ protocol: string; messages: unknown[] }>((resolve, reject) => {
      const socket = new WebSocket(url, ['access-token', accessToken])
      const messages: unknown[] = []
      const timeout = window.setTimeout(() => {
        socket.close()
        reject(new Error('Gateway health WebSocket timed out'))
      }, 10_000)
      socket.onmessage = (event) => {
        messages.push(JSON.parse(String(event.data)))
        if (messages.length === 1) socket.send('refresh')
        if (messages.length === 2) socket.send('close')
      }
      socket.onerror = () => {
        window.clearTimeout(timeout)
        reject(new Error('Gateway health WebSocket was rejected'))
      }
      socket.onclose = () => {
        window.clearTimeout(timeout)
        resolve({ protocol: socket.protocol, messages })
      }
    })
  }, { url: wsUrl.toString(), accessToken: token! })
  expect(socketResult.protocol).toBe('access-token')
  expect(socketResult.messages).toHaveLength(2)
  for (const message of socketResult.messages) {
    const envelope = message as {
      type: string
      data: typeof projection
    }
    expect(envelope.type).toBe('gateway_health')
    expect(envelope.data).toMatchObject({
      account_ref: accountRef,
      service_connection: { rpc_status: 'reachable' },
      gateway_session: {
        status: 'ready',
        session_generation: projection.gateway_session.session_generation,
      },
      account_observation: {
        status: 'observed',
        quality: 'fresh',
        same_session_generation: true,
      },
      market_data_feed: { status: 'unobserved' },
    })
    expect(Object.keys(envelope.data).sort()).toEqual([
      'account_observation',
      'account_ref',
      'authority',
      'gateway_session',
      'market_data_feed',
      'service_connection',
    ])
    expect(JSON.stringify(message)).not.toContain(credentialRef!)
    expect(JSON.stringify(message)).not.toContain(syntheticSecret!)
  }
})
