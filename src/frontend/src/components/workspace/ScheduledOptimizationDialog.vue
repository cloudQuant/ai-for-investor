<template>
  <SharedScheduledOptimizationDialog
    :model-value="modelValue"
    :config="initialConfig"
    :selected-count="store.selectedUnitIds.length"
    :on-save="handleSave"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { ScheduledOptimizationConfig } from '@bt-api/workspace-ui/core'
import { ScheduledOptimizationDialog as SharedScheduledOptimizationDialog } from '@bt-api/workspace-ui/research'
import { getErrorMessage } from '@/api/index'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { useWorkspaceStore } from '@/stores/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [value: Record<string, unknown>]
}>()

const store = useWorkspaceStore()

const initialConfig = computed<Partial<ScheduledOptimizationConfig>>(() => {
  const tradingConfig = (store.currentWorkspace?.trading_config || {}) as Record<string, unknown>
  const cfg = (tradingConfig.scheduled_optimization || {}) as Record<string, unknown>
  return {
    enabled: Boolean(cfg.enabled),
    frequency: cfg.frequency === 'weekly' ? 'weekly' : 'daily',
    execution_time: String(cfg.execution_time || '20:30'),
    unit_scope: cfg.unit_scope === 'selected' ? 'selected' : 'all',
    only_when_idle: cfg.only_when_idle !== false,
  }
})

async function handleSave(config: ScheduledOptimizationConfig): Promise<void> {
  try {
    const tradingConfig: Record<string, unknown> = {
      ...((store.currentWorkspace?.trading_config || {}) as Record<string, unknown>),
      scheduled_optimization: { ...config },
    }
    await store.updateWorkspace(props.workspaceId, { trading_config: tradingConfig })
    emit('saved', tradingConfig)
    ElMessage.success(t('workspaceDialogs.scheduledOptSaved'))
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.scheduledOptSaveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
