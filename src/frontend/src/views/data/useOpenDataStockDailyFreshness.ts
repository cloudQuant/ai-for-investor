/**
 * Domain freshness read state for the OpenData stock_daily freshness card.
 *
 * Extracted verbatim from `useDataPage` to keep the page composable within the
 * large-file ratchet; the request-epoch, abort-controller and fail-closed rules
 * are unchanged. A transport or protocol failure stays `opendata_unavailable`
 * and never falls back to the local coverage matrix or the legacy source (AC08).
 */

import { computed, ref, type ComputedRef } from 'vue'

import { marketDataApi } from '@/api/marketData'
import {
  deriveOpenDataFreshnessAvailability,
  emptyOpenDataStockDailyFreshnessDisplay,
  type OpenDataAvailabilityState,
  type OpenDataStockDailyFreshnessDisplayState,
} from '@/api/openDataCoverage'

export function useOpenDataStockDailyFreshness(
  canReadOpenDataStockDailyFreshness: ComputedRef<boolean>,
) {
  const openDataStockDailyFreshnessDisplay = ref<OpenDataStockDailyFreshnessDisplayState>(
    emptyOpenDataStockDailyFreshnessDisplay(),
  )
  let openDataStockDailyFreshnessRequestEpoch = 0
  let activeOpenDataStockDailyFreshnessAbortController: AbortController | null = null

  // The freshness card's real OpenData availability state. A failed or disabled
  // read surfaces as `opendata_unavailable`; an unmeasured (missing) report
  // surfaces as `UNKNOWN`, never a date. Only a measured report is `PROVEN`,
  // and a forward `coverage_state` lets SOURCE_LIMITED / NOT_SUPPORTED render
  // distinctly instead of collapsing into a healthy value.
  const openDataStockDailyFreshnessAvailability = computed<OpenDataAvailabilityState | null>(
    () => deriveOpenDataFreshnessAvailability({
      displayStatus: openDataStockDailyFreshnessDisplay.value.status,
      response: openDataStockDailyFreshnessDisplay.value.response,
    }),
  )

  function invalidateOpenDataStockDailyFreshnessRequest(): void {
    openDataStockDailyFreshnessRequestEpoch += 1
    const controller = activeOpenDataStockDailyFreshnessAbortController
    activeOpenDataStockDailyFreshnessAbortController = null
    if (controller && !controller.signal.aborted) controller.abort()
    openDataStockDailyFreshnessDisplay.value = emptyOpenDataStockDailyFreshnessDisplay()
  }

  function refreshOpenDataStockDailyFreshness(): void {
    if (!canReadOpenDataStockDailyFreshness.value) return

    const previousController = activeOpenDataStockDailyFreshnessAbortController
    activeOpenDataStockDailyFreshnessAbortController = null
    if (previousController && !previousController.signal.aborted) previousController.abort()

    const controller = new AbortController()
    const requestId = ++openDataStockDailyFreshnessRequestEpoch
    activeOpenDataStockDailyFreshnessAbortController = controller
    openDataStockDailyFreshnessDisplay.value = { status: 'loading', response: null }

    void marketDataApi.getOpenDataStockDailyFreshness({ signal: controller.signal })
      .then((response) => {
        if (
          requestId !== openDataStockDailyFreshnessRequestEpoch
          || activeOpenDataStockDailyFreshnessAbortController !== controller
          || controller.signal.aborted
          || !canReadOpenDataStockDailyFreshness.value
        ) return
        openDataStockDailyFreshnessDisplay.value = { status: 'ready', response }
      })
      .catch(() => {
        if (
          requestId !== openDataStockDailyFreshnessRequestEpoch
          || activeOpenDataStockDailyFreshnessAbortController !== controller
          || controller.signal.aborted
          || !canReadOpenDataStockDailyFreshness.value
        ) return
        // Transport and protocol errors are not represented as `missing` and
        // never fall back to the local coverage matrix.
        openDataStockDailyFreshnessDisplay.value = { status: 'unavailable', response: null }
      })
      .finally(() => {
        if (activeOpenDataStockDailyFreshnessAbortController === controller) {
          activeOpenDataStockDailyFreshnessAbortController = null
        }
      })
  }

  return {
    openDataStockDailyFreshnessDisplay,
    openDataStockDailyFreshnessAvailability,
    invalidateOpenDataStockDailyFreshnessRequest,
    refreshOpenDataStockDailyFreshness,
  }
}
