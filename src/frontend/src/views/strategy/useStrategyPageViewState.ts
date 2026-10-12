import { computed, ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import type { useStrategyStore } from '@/stores/strategy'

export function useStrategyPageViewState({ route, strategyStore, t }: {
  route: Pick<RouteLocationNormalizedLoaded, 'path'>
  strategyStore: ReturnType<typeof useStrategyStore>
  t: (key: string) => string
}) {

  // ---- State ----
  const isInvestmentStrategyResearchRoute = computed(() =>
    String(route.path || '').startsWith('/investment/strategies')
  )

  const showAIResearchTab = computed(() => isInvestmentStrategyResearchRoute.value)

  const showStrategyManagementTabs = computed(() => !isInvestmentStrategyResearchRoute.value)

  const activeTab = ref(showAIResearchTab.value ? 'aiResearch' : 'gallery')

  const searchKeyword = ref('')

  const categoryFilter = ref('')

  // ---- Computed ----
  const strategies = computed(() => strategyStore.strategies)

  const templates = computed(() => strategyStore.templates)

  const loading = computed(() => strategyStore.loading)

  const filteredTemplates = computed(() => {
    let list = templates.value
    if (categoryFilter.value) {
      list = list.filter(t => t.category === categoryFilter.value)
    }
    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      list = list.filter(t =>
        t.name.toLowerCase().includes(kw) ||
        t.description.toLowerCase().includes(kw) ||
        t.id.toLowerCase().includes(kw)
      )
    }
    return list
  })

  const displayedTemplates = computed(() => filteredTemplates.value)

  const strategyCategoryCount = computed(() =>
    new Set(templates.value.map((template) => template.category || 'custom')).size
  )

  const strategyManagementStats = computed(() => [
    {
      key: 'templates',
      label: t('strategy.metricTemplates'),
      value: templates.value.length,
    },
    {
      key: 'owned',
      label: t('strategy.metricMyStrategies'),
      value: strategies.value.length,
    },
    {
      key: 'filtered',
      label: t('strategy.metricFiltered'),
      value: filteredTemplates.value.length,
    },
    {
      key: 'categories',
      label: t('strategy.metricCategories'),
      value: strategyCategoryCount.value,
    },
  ])

  return {
    isInvestmentStrategyResearchRoute,
    showAIResearchTab,
    showStrategyManagementTabs,
    activeTab,
    searchKeyword,
    categoryFilter,
    strategies,
    templates,
    loading,
    filteredTemplates,
    displayedTemplates,
    strategyCategoryCount,
    strategyManagementStats,
  }
}
