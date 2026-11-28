<template>
  <SharedUnitSettingsDialog
    ref="innerRef"
    :model-value="modelValue"
    :unit="mappedUnit"
    :title="dialogTitle"
    schema-preset="backtest"
    :show-ref-notice="false"
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
  UnitSettingsDialog as SharedUnitSettingsDialog,
  type UnitSettingsConfig,
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
const innerRef = ref<InstanceType<typeof SharedUnitSettingsDialog> | null>(null)

const dialogTitle = computed(() =>
  `${props.workspaceType === 'trading' ? t('workspaceDialogs.strategyTrading') : t('workspaceDialogs.strategyResearch')}--${t('workspaceDialogs.unitSettingsTitle')}`,
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
    unit_settings: (props.unit.unit_settings || {}) as UnitSettingsConfig,
  }
})

const form = computed(() => innerRef.value?.form)

function initForm(): void {
  innerRef.value?.initForm()
}

async function handleSave(): Promise<void> {
  await innerRef.value?.handleSave()
}

async function handlePersist(_unitId: string, settings: UnitSettingsConfig): Promise<void> {
  if (!props.unit) return
  try {
    await store.updateUnit(props.workspaceId, props.unit.id, {
      unit_settings: { ...settings },
    })
    ElMessage.success(t('workspaceDialogs.unitSettingsSaved'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.saveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

defineExpose({ dialogTitle, form, initForm, handleSave })
</script>
