import { computed, reactive, ref, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { Router } from 'vue-router'
import { strategyApi } from '@/api/strategy'
import { stripStrategyMeta } from '@/constants/strategy'
import type { ParamSpec, Strategy, StrategyTemplate } from '@/types'
import type { useStrategyStore } from '@/stores/strategy'

export function useStrategyPageDialogs({ t, router, strategyStore, activeTab }: {
  t: (key: string) => string
  router: Router
  strategyStore: ReturnType<typeof useStrategyStore>
  activeTab: Ref<string>
}) {

  const dialogVisible = ref(false)

  const viewDialogVisible = ref(false)

  const detailVisible = ref(false)

  const isEdit = ref(false)

  const saving = ref(false)

  const editingId = ref('')

  const currentStrategy = ref<Strategy | null>(null)

  const detailTemplate = ref<StrategyTemplate | null>(null)

  const detailTab = ref('readme')

  const readmeContent = ref('')

  const readmeLoading = ref(false)

  const form = reactive({
    name: '',
    description: '',
    code: '',
    category: 'custom',
  })

  const paramTableData = computed(() => {
    if (!detailTemplate.value) return []
    return Object.entries(detailTemplate.value.params).map(([name, spec]: [string, ParamSpec]) => ({
      name,
      default: spec.default ?? '-',
      type: spec.type ?? '-',
      description: spec.description ?? name,
    }))
  })

  // ---- Methods ----
  async function openTemplateDetail(t: StrategyTemplate) {
    detailTemplate.value = t
    detailTab.value = 'readme'
    detailVisible.value = true
    readmeContent.value = ''
    readmeLoading.value = true
    try {
      const res = await strategyApi.getTemplateReadme(t.id)
      readmeContent.value = res.content ?? ''
    } catch {
      readmeContent.value = ''
    } finally {
      readmeLoading.value = false
    }
  }

  function goBacktest(t: StrategyTemplate) {
    detailVisible.value = false
    router.push({ path: '/backtest/legacy', query: { strategy: t.id } })
  }

  function showCreateDialog() {
    isEdit.value = false
    editingId.value = ''
    Object.assign(form, { name: '', description: '', code: '', category: 'custom' })
    dialogVisible.value = true
  }

  function editStrategy(strategy: Strategy) {
    isEdit.value = true
    editingId.value = strategy.id
    Object.assign(form, {
      name: strategy.name,
      description: strategy.description || '',
      code: strategy.code,
      category: strategy.category,
    })
    dialogVisible.value = true
  }

  function viewStrategy(strategy: Strategy) {
    currentStrategy.value = strategy
    viewDialogVisible.value = true
  }

  function useTemplate(template: StrategyTemplate) {
    detailVisible.value = false
    isEdit.value = false
    editingId.value = ''
    Object.assign(form, {
      name: template.name + ` (${t('strategy.typeCopy')})`,
      description: stripStrategyMeta(template.description),
      code: template.code,
      category: template.category,
    })
    activeTab.value = 'my'
    dialogVisible.value = true
  }

  function updateStrategyForm(nextForm: typeof form) {
    Object.assign(form, nextForm)
  }

  async function saveStrategy() {
    if (!form.name || !form.code) {
      ElMessage.warning(t('strategy.warnNameOrCodeEmpty'))
      return
    }
    saving.value = true
    try {
      if (isEdit.value) {
        await strategyStore.updateStrategy(editingId.value, form)
        ElMessage.success(t('strategy.updated'))
      } else {
        await strategyStore.createStrategy(form)
        ElMessage.success(t('strategy.created'))
      }
      dialogVisible.value = false
    } finally {
      saving.value = false
    }
  }

  async function deleteStrategy(id: string) {
    await ElMessageBox.confirm(t('strategy.confirmDeleteText'), t('strategy.confirmDeleteTitle'), { type: 'warning' })
    await strategyStore.deleteStrategy(id)
    ElMessage.success(t('strategy.deleted'))
  }

  return {
    form,
    dialogVisible,
    viewDialogVisible,
    detailVisible,
    isEdit,
    saving,
    editingId,
    currentStrategy,
    detailTemplate,
    detailTab,
    readmeContent,
    readmeLoading,
    paramTableData,
    openTemplateDetail,
    goBacktest,
    showCreateDialog,
    editStrategy,
    viewStrategy,
    useTemplate,
    updateStrategyForm,
    saveStrategy,
    deleteStrategy,
  }
}
