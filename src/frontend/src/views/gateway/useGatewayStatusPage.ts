/** Read-only Gateway health data and polling for the operations page. */

import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/api'
import { liveTradingApi } from '@/api/liveTrading'
import type { GatewayHealthInfo } from '@/api/liveTrading'
import {
  connLabel,
  connTagType,
  formatHeartbeatAge,
  formatNumber,
  formatUptime,
  getHeartbeatAge,
  heartbeatClass,
  stateLabel,
  stateTagType,
} from '../gatewayStatusHelpers'

export function useGatewayStatusPage() {
  const { t } = useI18n()

  const loading = ref(false)
  const gateways = ref<GatewayHealthInfo[]>([])
  const loadError = ref('')
  const viewMode = ref<'card' | 'table'>('card')
  const gatewaySearch = ref('')
  const stateFilter = ref('all')
  const healthFilter = ref('all')
  const nowMs = ref(Date.now())
  const lastHealthFetchMs = ref(Date.now())
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null

  const baseGateways = computed(() => gateways.value.filter((g) => !g.gateway_key.startsWith('direct:')))
  const visibleGateways = computed(() => {
    const keyword = gatewaySearch.value.trim().toLowerCase()
    return baseGateways.value.filter((gateway) => {
      if (stateFilter.value !== 'all' && gateway.state !== stateFilter.value) return false
      if (healthFilter.value === 'healthy' && !gateway.is_healthy) return false
      if (healthFilter.value === 'unhealthy' && gateway.is_healthy) return false
      if (!keyword) return true
      return [
        gateway.gateway_key,
        gateway.strategy_name,
        gateway.exchange,
        gateway.asset_type,
        gateway.account_id,
        gateway.state,
        gateway.market_connection,
        gateway.trade_connection,
        ...gateway.instances,
        ...(gateway.recent_errors || []).map((item) => `${item.source} ${item.message}`),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword))
    })
  })
  const healthyCount = computed(() => visibleGateways.value.filter((g) => g.is_healthy).length)
  const totalSymbolCount = computed(() => visibleGateways.value.reduce((sum, item) => sum + item.symbol_count, 0))
  const totalOrderCount = computed(() => visibleGateways.value.reduce((sum, item) => sum + item.order_count, 0))
  const staleHeartbeatCount = computed(() =>
    visibleGateways.value.filter((gateway) => {
      const age = getHeartbeatAge(gateway, nowMs.value, lastHealthFetchMs.value)
      return age != null && age >= 30
    }).length,
  )

  async function fetchHealth() {
    loading.value = true
    try {
      const res = await liveTradingApi.listGatewayHealth()
      gateways.value = res.gateways
      nowMs.value = Date.now()
      lastHealthFetchMs.value = nowMs.value
      loadError.value = ''
    } catch (error) {
      loadError.value = getErrorMessage(error, t('gatewayStatus.msgLoadFailed'))
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void fetchHealth()
    heartbeatTimer = setInterval(() => {
      nowMs.value = Date.now()
    }, 1_000)
    pollTimer = setInterval(fetchHealth, 10_000)
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
    if (heartbeatTimer) clearInterval(heartbeatTimer)
  })

  return {
    connLabel,
    connTagType,
    fetchHealth,
    formatHeartbeatAge,
    formatNumber,
    formatUptime,
    gatewaySearch,
    gateways,
    getHeartbeatAge,
    healthFilter,
    healthyCount,
    heartbeatClass,
    lastHealthFetchMs,
    loadError,
    loading,
    nowMs,
    stateFilter,
    stateLabel,
    stateTagType,
    t,
    totalOrderCount,
    totalSymbolCount,
    viewMode,
    visibleGateways,
    staleHeartbeatCount,
  }
}
