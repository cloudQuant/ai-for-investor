import { expect, test, type Route } from '@playwright/test'

import type { MarketDataQueryRequest } from '@/api/marketData'

import { prepareStaticPreviewPage } from '../support/static-preview'

function json(route: Route, payload: unknown): Promise<void> {
  return route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })
}

function stockBundle() {
  const unconfigured = (familyId: string) => ({
    family_id: familyId,
    family_contract_version: 'market-data-family-v1',
    asset_type: 'stock',
    status: 'unconfigured',
    dataset_code: `market.${familyId.replace('.', '_')}`,
    data_kind: 'reference_series',
    frequency_semantics: 'calendar_grid',
    frequencies: ['1d'],
    field_profile_id: `${familyId.replace('.', '-')}-v1`,
    required_fields: ['close'],
    optional_fields: [],
    dimension_fields: [],
    coverage_model: 'calendar_grid',
    source_policy_id: null,
    reason_code: 'DATA_FAMILY_UNCONFIGURED',
  })

  return {
    version: 'market-data-family-bundle-v1',
    requested_asset_type: 'stock',
    families: [
      {
        family_id: 'stock.realtime',
        family_contract_version: 'market-data-family-v1',
        asset_type: 'stock',
        status: 'ready',
        dataset_code: 'market.bars',
        data_kind: 'bars',
        frequency_semantics: 'calendar_grid',
        frequencies: ['1d', '1w', '1mo'],
        field_profile_id: 'stock-realtime-v1',
        required_fields: ['close'],
        optional_fields: ['open', 'high', 'low', 'volume'],
        dimension_fields: [],
        coverage_model: 'calendar_grid',
        source_policy_id: 'market-default-v1',
        reason_code: null,
      },
      unconfigured('stock.valuation'),
      unconfigured('stock.liquidity'),
    ],
  }
}

function stockCapabilities() {
  // The page only derives the automatic local-only lifecycle read from an
  // explicit legacy route census. A bare feature-flag document is rejected as
  // CAPABILITY_CENSUS_INVALID, which leaves the page waiting for an explicit
  // OpenData query instead of exercising this legacy bootstrap contract.
  const rollout = (capabilityId: string, enabled: boolean) => ({
    capability_id: capabilityId,
    scope: 'rollout' as const,
    route_id: null,
    declared: true,
    installed: true,
    verified: true,
    authorized: true,
    effective: enabled,
    reason_code: enabled ? null : 'ROLLOUT_DISABLED',
  })
  return {
    version: 'market-data-capabilities-v1',
    query_v2_enabled: true,
    online_fetch_enabled: true,
    research_cache_fill_enabled: false,
    research_backtest_bridge_enabled: false,
    capability_states: [
      rollout('market-data.query-v2', true),
      rollout('market-data.online-fetch', true),
      rollout('market-data.research-cache-fill', false),
      rollout('market-data.research-backtest-bridge', false),
      {
        capability_id: 'market-data.route:akshare-stock-kline-legacy-v1',
        scope: 'route' as const,
        route_id: 'akshare-stock-kline-legacy-v1',
        declared: true,
        installed: true,
        verified: true,
        authorized: true,
        effective: true,
        reason_code: null,
      },
    ],
  }
}

function stockContract() {
  return {
    version: 'market-data-v2',
    request: {
      identity: { canonical_id: 'instrument:stock:CN-SZSE:000001' },
      dataset_code: 'market.bars',
      data_kind: 'bars',
      frequency: '1d',
      required_fields: ['close'],
      adjustment: 'qfq',
      price_basis: 'close',
      currency: 'CNY',
      unit: 'share',
      source_policy_id: 'market-default-v1',
      family_id: 'stock.realtime',
      family_contract_version: 'market-data-family-v1',
      mode: 'local_first',
    },
  }
}

function stockQueryResponse(mode: 'local_only' | 'local_first') {
  return {
    query_id: `stock-local-first-${mode}`,
    canonical_id: 'instrument:stock:CN-SZSE:000001',
    dataset_code: 'market.bars',
    asset_type: 'stock',
    instrument_metadata_version: 'stock-v1',
    data_kind: 'bars',
    frequency: '1d',
    source_policy_id: 'market-default-v1',
    family_id: 'stock.realtime',
    family_contract_version: 'market-data-family-v1',
    knowledge_cutoff: '2026-09-11T00:00:00Z',
    identity_knowledge_cutoff: '2026-09-11T00:00:00Z',
    observations: [
      {
        revision_id: mode === 'local_only' ? 'local-revision-1' : 'provider-revision-2',
        source_snapshot_id: mode === 'local_only' ? 'local-snapshot-1' : 'provider-snapshot-2',
        event_at: '2026-09-10T00:00:00Z',
        available_at: '2026-09-10T15:00:00Z',
        committed_at: '2026-09-10T15:00:01Z',
        revision_number: mode === 'local_only' ? 1 : 2,
        quality: 'pass',
        fields: { open: 12.1, high: 12.4, low: 12, close: 12.34, volume: 1000 },
      },
    ],
    next_cursor: null,
    coverage: {
      status: 'complete',
      expected_event_count: 1,
      accepted_event_count: 1,
      missing_event_count: 0,
      coverage_ratio: 1,
      gaps: [],
      rejection_counts: {},
      calendar_reason: null,
    },
    fetches: mode === 'local_first'
      ? [{
        route_id: 'fixture-stock-realtime-v1',
        provider_id: 'fixture-provider',
        source_snapshot_id: 'provider-snapshot-2',
        observation_revision_ids: ['provider-revision-2'],
        passing_observation_count: 1,
        failed_observation_count: 0,
      }]
      : [],
    warnings: [],
    refresh_status: null,
    historical_status: null,
  }
}

test('market page keeps lifecycle reads local-only and reserves local-first for the explicit query action', async ({ page }) => {
  await prepareStaticPreviewPage(page)

  const queryBodies: MarketDataQueryRequest[] = []
  const unexpectedDataRequests: string[] = []

  await page.route('**/api/v1/data/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path.endsWith('/market-data/capabilities')) {
      return json(route, stockCapabilities())
    }
    if (path.endsWith('/market-instruments/query-bundle')) return json(route, stockBundle())
    if (path.endsWith('/market-instruments/query-contract')) return json(route, stockContract())
    if (path.endsWith('/queries') && request.method() === 'POST') {
      const body = request.postDataJSON() as MarketDataQueryRequest
      queryBodies.push(body)
      if (body.mode === 'local_only' || body.mode === 'local_first') {
        return json(route, stockQueryResponse(body.mode))
      }
      unexpectedDataRequests.push(`${request.method()} ${path} mode=${String(body.mode)}`)
      return json(route, { detail: 'unexpected query mode' })
    }
    if (path.endsWith('/market-instruments/options') && request.method() === 'GET') {
      return json(route, { total: 0, items: [] })
    }
    if (path.endsWith('/trust/coverage') && request.method() === 'GET') {
      return json(route, { total: 0, refreshed: false, items: [] })
    }
    if (path.endsWith('/tables') && request.method() === 'GET') return json(route, { total: 0, items: [] })

    unexpectedDataRequests.push(`${request.method()} ${path}`)
    return json(route, { total: 0, items: [] })
  })

  await page.goto('/data/market')

  const status = page.locator('[data-test="market-data-platform-status"]')
  const realtimeFamilyCard = page.locator('[data-test="market-data-family-stock.realtime"]')
  await expect(status).toContainText('仅本地读取')
  await page.getByRole('button', { name: '数据来源详情 · 数据种类与仓库覆盖' }).click()
  await expect(realtimeFamilyCard).toBeVisible()
  await expect(realtimeFamilyCard).toContainText('日线/周线/月线 K线兼容数据（仅声明字段）')
  await expect(realtimeFamilyCard).toContainText('bars · calendar_grid')
  await expect(realtimeFamilyCard).not.toContainText('实时行情')

  await expect.poll(() => queryBodies.length).toBe(1)
  const expectedContract = {
    identity: { canonical_id: 'instrument:stock:CN-SZSE:000001' },
    dataset_code: 'market.bars',
    data_kind: 'bars',
    frequency: '1d',
    required_fields: ['close'],
    adjustment: 'qfq',
    price_basis: 'close',
    currency: 'CNY',
    unit: 'share',
    source_policy_id: 'market-default-v1',
    family_id: 'stock.realtime',
    family_contract_version: 'market-data-family-v1',
    purpose: 'display',
    consistency: 'display',
  }
  expect(queryBodies[0]).toEqual(expect.objectContaining({
    ...expectedContract,
    mode: 'local_only',
  }))

  await page.locator('[data-test="market-instrument-query"]').click()
  await expect.poll(() => queryBodies.length).toBe(2)
  await expect(status).toContainText('已获取并入库')
  await expect(status).toContainText('fixture-provider')

  expect(queryBodies[1]).toEqual(expect.objectContaining({
    ...expectedContract,
    mode: 'local_first',
  }))
  expect(queryBodies[1].start).toBe(queryBodies[0].start)
  expect(queryBodies[1].end).toBe(queryBodies[0].end)
  expect(queryBodies.map((body) => body.mode)).toEqual(['local_only', 'local_first'])
  expect(unexpectedDataRequests).toEqual([])
})
