<template>
  <SharedUnitRenameDialog
    :model-value="modelValue"
    :unit="mappedUnit"
    :show-notes-and-pin="false"
    :modes="['custom', 'strategy', 'symbol', 'symbol_name', 'category', 'replace']"
    :original-label="unit ? `${unit.symbol}_${unit.timeframe}` : ''"
    :title="t('workspaceDialogs.rnUnitTitle')"
    :on-save="handleSave"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  UnitRenameDialog as SharedUnitRenameDialog,
  type UnitRenameSubmitPayload,
  type WorkspaceUnitRecord,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { useWorkspaceStore } from '@/stores/workspace'
import { getErrorMessage } from '@/api/index'
import type { StrategyUnit } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unit: StrategyUnit | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const store = useWorkspaceStore()

type LocalRenameMode = 'custom' | 'strategy' | 'symbol' | 'symbol_name' | 'category' | 'replace'

const mappedUnit = computed<WorkspaceUnitRecord | null>(() => {
  if (!props.unit) return null
  return {
    unit: props.unit.id,
    display_name: props.unit.strategy_name || props.unit.strategy_id || props.unit.id,
    group_name: props.unit.group_name || '',
    linked_group: '',
    sort_order: props.unit.sort_order ?? 0,
    notes: '',
    pinned: false,
    lock_trading: Boolean(props.unit.lock_trading),
    lock_running: Boolean(props.unit.lock_running),
    state: props.unit.run_status || 'idle',
    symbols: props.unit.symbol ? [props.unit.symbol] : [],
    exchanges: [],
    timeframe: props.unit.timeframe || null,
  }
})

async function handleSave(payload: UnitRenameSubmitPayload): Promise<void> {
  if (!props.unit) return
  try {
    await store.renameUnit(props.workspaceId, {
      unit_id: props.unit.id,
      mode: payload.mode as LocalRenameMode,
      value: payload.value,
      search: payload.search,
      replace: payload.replace,
    })
    ElMessage.success(t('workspaceDialogs.rnUnitRenamed'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.rnRenameFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
