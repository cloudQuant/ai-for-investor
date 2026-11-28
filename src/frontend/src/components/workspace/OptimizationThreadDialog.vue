<template>
  <SharedOptimizationThreadDialog
    :model-value="modelValue"
    :config="initialConfig"
    :on-save="handleSave"
    @update:model-value="$emit('update:modelValue', $event)"
    @saved="$emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { OptimizationThreadConfig } from '@bt-api/workspace-ui/core'
import { OptimizationThreadDialog as SharedOptimizationThreadDialog } from '@bt-api/workspace-ui/research'
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
}>()

defineEmits<{
  'update:modelValue': [val: boolean]
  saved: []
}>()

const initialConfig = computed<Partial<OptimizationThreadConfig>>(() => {
  const oc = (props.unit?.optimization_config || {}) as Record<string, unknown>
  return {
    n_workers: typeof oc.n_workers === 'number' ? oc.n_workers : 4,
    mode: oc.mode === 'random' ? 'random' : 'grid',
    timeout: typeof oc.timeout === 'number' ? oc.timeout : 0,
  }
})

async function handleSave(config: OptimizationThreadConfig): Promise<void> {
  if (!props.unit) return
  try {
    const existingConfig = props.unit.optimization_config || {}
    await workspaceApi.updateUnit(props.workspaceId, props.unit.id, {
      optimization_config: {
        ...existingConfig,
        n_workers: config.n_workers,
        mode: config.mode,
        timeout: config.timeout,
      },
    })
    ElMessage.success(t('workspaceDialogs.otdSaved'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.otdSaveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
