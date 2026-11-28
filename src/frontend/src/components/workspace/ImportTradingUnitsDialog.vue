<template>
  <SharedImportUnitsDialog
    :model-value="modelValue"
    :workspace-id="workspaceId"
    :is-custom-workspace="true"
    :raw-json-mode="true"
    :all-workspaces="workspaceSummaries"
    :source-workspace-label="t('workspaceDialogs.researchWorkspace')"
    :load-source-units="loadSourceUnits"
    :on-import="handleImport"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  ImportUnitsDialog as SharedImportUnitsDialog,
  type ImportUnitsSubmitPayload,
  type WorkspaceSummaryItem,
  type WorkspaceUnitRecord,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { workspaceApi } from '@/api/workspace'
import type { StrategyUnit, Workspace } from '@/types/workspace'
import { normalizeTransferUnits } from './tradingUnitTransfer'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  imported: [count: number]
}>()

const researchWorkspaces = ref<Workspace[]>([])
const researchUnitsCache = ref<StrategyUnit[]>([])

const workspaceSummaries = computed<WorkspaceSummaryItem[]>(() =>
  researchWorkspaces.value.map(ws => ({
    id: ws.id,
    name: ws.name,
    description: ws.description,
    workspace_type: 'research',
    total_units: ws.unit_count,
  })),
)

async function loadResearchWorkspaces(): Promise<void> {
  try {
    const response = await workspaceApi.list(0, 200, 'research')
    researchWorkspaces.value = response.items
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, t('workspaceDialogs.loadResearchFailed')))
  }
}

async function loadSourceUnits(sourceWsId: string): Promise<WorkspaceUnitRecord[]> {
  try {
    const response = await workspaceApi.listUnits(sourceWsId)
    researchUnitsCache.value = response.items
    return response.items.map(u => ({
      unit: u.id,
      display_name: u.strategy_name || u.strategy_id || u.id,
      group_name: u.group_name || '',
      linked_group: '',
      sort_order: u.sort_order ?? 0,
      notes: '',
      pinned: false,
      lock_trading: false,
      lock_running: false,
      state: u.run_status || 'idle',
      symbols: u.symbol ? [u.symbol] : [],
      exchanges: [],
    }))
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.loadUnitsFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

async function handleImport(payload: ImportUnitsSubmitPayload): Promise<void> {
  try {
    const rawUnits = payload.mode === 'workspace'
      ? researchUnitsCache.value.filter(unit => (payload.units ?? []).includes(unit.id))
      : (payload.raw_items ?? [])
    const normalized = normalizeTransferUnits(rawUnits, {
      includeTradingFields: true,
      defaultTradingMode: 'paper',
    })
    if (!normalized.length) {
      throw new Error(
        payload.mode === 'workspace'
          ? t('workspaceDialogs.pleaseSelectImportUnits')
          : t('workspaceDialogs.importEmpty'),
      )
    }
    await workspaceApi.batchCreateUnits(props.workspaceId, normalized)
    ElMessage.success(`${t('workspaceDialogs.importSuccess')} ${normalized.length} ${t('workspaceDialogs.nUnits')}`)
    emit('imported', normalized.length)
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.importFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) {
      void loadResearchWorkspaces()
    }
  },
)
</script>
