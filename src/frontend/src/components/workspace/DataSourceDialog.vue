<template>
  <SharedDataSourceDialog
    ref="innerRef"
    :model-value="modelValue"
    :unit="mappedUnit"
    :title="dialogTitle"
    :editable-timeframe="true"
    default-range-type="date"
    default-split-type="natural"
    :show-live-feed-section="false"
    :show-note="false"
    :on-save="handlePersist"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  DataSourceDialog as SharedDataSourceDialog,
  toPickerDate,
  type UnitDataConfig,
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
const innerRef = ref<InstanceType<typeof SharedDataSourceDialog> | null>(null)

const dialogTitle = computed(() =>
  `${props.workspaceType === 'trading' ? t('workspaceDialogs.strategyTrading') : t('workspaceDialogs.strategyResearch')}--${t('workspaceDialogs.dataSourceTitle')}`,
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
    timeframe: props.unit.timeframe || '1d',
    compression: props.unit.timeframe_n || 1,
    data_config: (props.unit.data_config || {}) as UnitDataConfig,
  }
})

const form = computed(() => innerRef.value?.form)

function initForm(): void {
  innerRef.value?.initForm()
}

async function handleSave(): Promise<void> {
  await innerRef.value?.handleSave()
}

async function handlePersist(
  _unitId: string,
  dataConfig: UnitDataConfig,
  meta?: { timeframe: string; timeframe_n: number },
): Promise<void> {
  if (!props.unit) return
  try {
    await store.updateUnit(props.workspaceId, props.unit.id, {
      timeframe: meta?.timeframe || props.unit.timeframe || '1d',
      timeframe_n: meta?.timeframe_n || props.unit.timeframe_n || 1,
      data_config: dataConfig,
    })
    ElMessage.success(t('workspaceDialogs.dataSourceSaved'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.dataSourceSaveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

defineExpose({ dialogTitle, form, initForm, handleSave, toPickerDate })
</script>
