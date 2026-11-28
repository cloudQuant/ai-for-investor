<template>
  <SharedUnitRuntimeLogsDialog
    :model-value="modelValue"
    mode="files"
    :title="t('workspaceDialogs.urdTitle')"
    :unit-header="unitHeader"
    :allow-open-directory="true"
    :files-labels="filesLabels"
    :load-runtime-info="handleLoadRuntimeInfo"
    :load-runtime-file="handleLoadRuntimeFile"
    :on-open-directory="handleOpenDirectory"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { UnitRuntimeFilesData } from '@bt-api/workspace-ui/core'
import { UnitRuntimeLogsDialog as SharedUnitRuntimeLogsDialog } from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { workspaceApi } from '@/api/workspace'
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
}>()

const unitHeader = computed(() => {
  if (!props.unit) return null
  return {
    id: props.unit.id,
    name: props.unit.strategy_name || props.unit.strategy_id || props.unit.id,
    subtitle: `${props.unit.symbol} / ${props.unit.timeframe}`,
    statusText: props.unit.trading_snapshot?.instance_status || props.unit.run_status,
    instanceId: props.unit.trading_instance_id,
    noInstanceText: t('workspaceDialogs.urdNoInstance'),
  }
})

const filesLabels = computed(() => ({
  strategyUnit: t('workspaceDialogs.urdStrategyUnit'),
  instanceStatus: t('workspaceDialogs.urdInstanceStatus'),
  logDir: t('workspaceDialogs.urdLogDir'),
  runtimeDir: t('workspaceDialogs.urdRuntimeDir'),
  selectFile: t('workspaceDialogs.urdSelectFile'),
  allLines: t('workspaceDialogs.urdAll'),
  lines200: t('workspaceDialogs.urdLines200'),
  lines500: t('workspaceDialogs.urdLines500'),
  lines1000: t('workspaceDialogs.urdLines1000'),
  refresh: t('workspaceDialogs.urdRefresh'),
  openUnit: t('workspaceDialogs.urdOpenUnit'),
  noFileSelected: t('workspaceDialogs.urdNoFileSelected'),
  selectFilePrompt: t('workspaceDialogs.urdSelectFilePrompt'),
}))

async function handleLoadRuntimeInfo(): Promise<UnitRuntimeFilesData> {
  if (!props.unit) return { files: [] }
  try {
    return await workspaceApi.getUnitRuntimeInfo(props.workspaceId, props.unit.id)
  } catch (error: unknown) {
    throw new Error(getErrorMessage(error, t('workspaceDialogs.urdLoadInfoFailed')))
  }
}

async function handleLoadRuntimeFile(relativePath: string, tailLines: number | null): Promise<string> {
  if (!props.unit) return ''
  try {
    return await workspaceApi.getUnitRuntimeFile(props.workspaceId, props.unit.id, relativePath, tailLines)
  } catch (error: unknown) {
    throw new Error(getErrorMessage(error, t('workspaceDialogs.urdReadFileFailed')))
  }
}

async function handleOpenDirectory(): Promise<void> {
  if (!props.unit) return
  try {
    const result = await workspaceApi.openUnitRuntimeDir(props.workspaceId, props.unit.id)
    ElMessage.success(result.message || t('workspaceDialogs.urdDirOpened'))
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, t('workspaceDialogs.urdOpenDirFailed')))
  }
}
</script>
