<template>
  <SharedStrategyParamsDialog
    :model-value="modelValue"
    :unit="mappedUnit"
    :editable-params="true"
    :title="dialogTitle"
    :on-save-params="handleSaveParams"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  StrategyParamsDialog as SharedStrategyParamsDialog,
  type WorkspaceUnitRecord,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { useWorkspaceStore } from '@/stores/workspace'
import { getErrorMessage } from '@/api/index'
import type { StrategyUnit, WorkspaceType } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unit: StrategyUnit | null
  workspaceType?: WorkspaceType
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const store = useWorkspaceStore()

const dialogTitle = computed(() =>
  props.workspaceType === 'trading'
    ? t('workspaceDialogs.spdTitleTrading')
    : t('workspaceDialogs.spdTitleResearch'),
)

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
    strategy_params: props.unit.params || {},
  }
})

async function handleSaveParams(_unitId: string, paramsObj: Record<string, unknown>): Promise<void> {
  if (!props.unit) return
  try {
    await store.updateUnit(props.workspaceId, props.unit.id, { params: paramsObj })
    ElMessage.success(t('workspaceDialogs.spdSaved'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.spdSaveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
