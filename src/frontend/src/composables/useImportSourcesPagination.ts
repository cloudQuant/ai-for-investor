import { ref, type Ref } from 'vue'

import { getErrorMessage } from '@/api'
import { portfolioLedgerApi, type PortfolioLedgerImportSource } from '@/api/portfolioLedger'

/**
 * Manages paginated existing import sources state and reset-on-total-drift logic.
 */
export function useImportSourcesPagination(options: {
  selectedImportVersionId: Ref<string>
  sourceImportError: Ref<string>
  loadFailedMessage: () => string
}) {
  const existingImportsLoading = ref(false)
  const existingImportSources = ref<PortfolioLedgerImportSource[]>([])
  const existingImportSourcesPage = ref(1)
  const existingImportSourcesTotal = ref(0)
  const existingImportSourcesHasMore = ref(false)

  async function loadExistingImportSources(page = 1) {
    if (existingImportsLoading.value) return
    existingImportsLoading.value = true
    options.sourceImportError.value = ''
    try {
      const result = await portfolioLedgerApi.listImportSources(page, 100)
      if (page === 1) existingImportSources.value = result.items
      else existingImportSources.value = [...existingImportSources.value, ...result.items]
      existingImportSourcesPage.value = result.page
      existingImportSourcesTotal.value = result.total
      existingImportSourcesHasMore.value = result.has_more
      const currentSelected = options.selectedImportVersionId.value
      if (
        !currentSelected
        || !existingImportSources.value.some(item => item.import_version_id === currentSelected)
      ) {
        options.selectedImportVersionId.value = result.items.find(
          item => item.source_material_status === 'verified',
        )?.import_version_id ?? ''
      }
    } catch (error: unknown) {
      options.sourceImportError.value = getErrorMessage(error, options.loadFailedMessage())
    } finally {
      existingImportsLoading.value = false
    }
  }

  async function loadMoreImportedSources() {
    if (!existingImportSourcesHasMore.value || existingImportsLoading.value) return
    const nextPage = existingImportSourcesPage.value + 1
    existingImportsLoading.value = true
    try {
      const result = await portfolioLedgerApi.listImportSources(nextPage, 100)
      const nextCount = existingImportSources.value.length + result.items.length
      if (
        result.total !== existingImportSourcesTotal.value
        || (!result.has_more && result.total !== nextCount)
      ) {
        existingImportsLoading.value = false
        await loadExistingImportSources(1)
        return
      }
      existingImportSources.value = [...existingImportSources.value, ...result.items]
      existingImportSourcesPage.value = result.page
      existingImportSourcesTotal.value = result.total
      existingImportSourcesHasMore.value = result.has_more
    } catch (error: unknown) {
      options.sourceImportError.value = getErrorMessage(error, options.loadFailedMessage())
    } finally {
      existingImportsLoading.value = false
    }
  }

  return {
    existingImportsLoading,
    existingImportSources,
    existingImportSourcesPage,
    existingImportSourcesHasMore,
    loadExistingImportSources,
    loadMoreImportedSources,
  }
}
