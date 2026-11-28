<template>
  <SharedChangeSymbolDialog
    :model-value="modelValue"
    :initial-symbol="unit?.symbol || ''"
    :initial-symbol-name="unit?.symbol_name || ''"
    :initial-timeframe="unit?.timeframe || 'D1'"
    :on-save="handleSave"
    @update:model-value="$emit('update:modelValue', $event)"
    @saved="$emit('saved')"
  />
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { ChangeSymbolPayload } from '@bt-api/workspace-ui/core'
import { ChangeSymbolDialog as SharedChangeSymbolDialog } from '@bt-api/workspace-ui/research'
import { workspaceApi } from '@/api/workspace'
import { getErrorMessage } from '@/api/index'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import type { StrategyUnit } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unit: StrategyUnit | null
  selectedUnitIds: string[]
}>()

defineEmits<{
  'update:modelValue': [val: boolean]
  saved: []
}>()

async function handleSave(payload: ChangeSymbolPayload): Promise<void> {
  if (!payload.symbol) {
    ElMessage.warning(t('workspaceDialogs.csInputSymbol'))
    throw new Error(t('workspaceDialogs.csInputSymbol'))
  }
  try {
    const ids = payload.apply_scope === 'selected' ? props.selectedUnitIds : (props.unit ? [props.unit.id] : [])
    for (const id of ids) {
      await workspaceApi.updateUnit(props.workspaceId, id, {
        symbol: payload.symbol,
        symbol_name: payload.symbol_name,
        timeframe: payload.timeframe,
      })
    }
    ElMessage.success(t('workspaceDialogs.csSwitchedNUnits', { n: ids.length }))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.csSwitchFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
