<template>
  <SharedGroupLinkDialog
    :model-value="modelValue"
    :units="selectedUnitRecords"
    :existing-group-count="existingGroupCount"
    :initial-group-name="initialGroupName"
    :title="t('workspaceDialogs.glTitle')"
    :loading="loading"
    :on-save="handleSave"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  GroupLinkDialog as SharedGroupLinkDialog,
  type WorkspaceUnitRecord,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { useWorkspaceStore } from '@/stores/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unitIds: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [value: Record<string, unknown>]
}>()

const store = useWorkspaceStore()
const loading = computed(() => store.loading)

function readGroupLinks(): Record<string, string> {
  const tradingConfig = (store.currentWorkspace?.trading_config || {}) as Record<string, unknown>
  return (tradingConfig.group_links || {}) as Record<string, string>
}

const existingGroupCount = computed(() => new Set(Object.values(readGroupLinks()).filter(Boolean)).size)

const initialGroupName = computed(() => {
  const links = readGroupLinks()
  const values = props.unitIds.map(unitId => links[unitId]).filter(Boolean)
  return values.length && values.every(val => val === values[0]) ? values[0] : ''
})

const selectedUnitRecords = computed<WorkspaceUnitRecord[]>(() =>
  store.units
    .filter(unit => props.unitIds.includes(unit.id))
    .map(unit => ({
      unit: unit.id,
      display_name: unit.strategy_name || unit.strategy_id || unit.id,
      group_name: unit.group_name || '',
      linked_group: readGroupLinks()[unit.id] || '',
      sort_order: unit.sort_order ?? 0,
      notes: '',
      pinned: false,
      lock_trading: Boolean(unit.lock_trading),
      lock_running: Boolean(unit.lock_running),
      state: unit.run_status || 'idle',
      symbols: unit.symbol ? [unit.symbol] : [],
      exchanges: [],
    })),
)

async function handleSave(unitIds: string[], linkedGroup: string): Promise<void> {
  if (!unitIds.length) {
    ElMessage.warning(t('workspaceDialogs.glSelectFirst'))
    throw new Error(t('workspaceDialogs.glSelectFirst'))
  }
  const links = { ...readGroupLinks() }
  const trimmed = linkedGroup.trim()
  for (const unitId of unitIds) {
    if (trimmed) {
      links[unitId] = trimmed
    } else {
      delete links[unitId]
    }
  }
  const tradingConfig = {
    ...((store.currentWorkspace?.trading_config || {}) as Record<string, unknown>),
    group_links: links,
  }
  try {
    await store.updateWorkspace(props.workspaceId, { trading_config: tradingConfig })
    emit('saved', tradingConfig)
    ElMessage.success(trimmed ? t('workspaceDialogs.glSaved') : t('workspaceDialogs.glCleared'))
  } catch (error: unknown) {
    const message = getErrorMessage(
      error,
      trimmed ? t('workspaceDialogs.glSaveFailed') : t('workspaceDialogs.glClearFailed'),
    )
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
