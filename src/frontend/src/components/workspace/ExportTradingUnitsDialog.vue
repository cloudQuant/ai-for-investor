<template>
  <SharedExportUnitsDialog
    :model-value="modelValue"
    workspace-id=""
    :workspace-summary="null"
    :units="mappedUnits"
    :all-workspaces="workspaceSummaries"
    :modes="['workspace', 'json']"
    default-mode="workspace"
    :allow-create-new-workspace="false"
    :accept-all-workspace-targets="true"
    :target-workspace-label="t('workspaceDialogs.researchWorkspace')"
    :on-export-to-workspace="handleExportToWorkspace"
    :on-export-file="handleExportFile"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  ExportUnitsDialog as SharedExportUnitsDialog,
  type ExportToWorkspacePayload,
  type WorkspaceSummaryItem,
  type WorkspaceUnitRecord,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { workspaceApi } from '@/api/workspace'
import type { StrategyUnit, Workspace } from '@/types/workspace'
import { buildTransferUnitPayload, downloadTransferUnits } from './tradingUnitTransfer'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  units: StrategyUnit[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  exported: [count: number]
}>()

const researchWorkspaces = ref<Workspace[]>([])

const workspaceSummaries = computed<WorkspaceSummaryItem[]>(() =>
  researchWorkspaces.value.map(ws => ({
    id: ws.id,
    name: ws.name,
    description: ws.description,
    workspace_type: 'research',
    total_units: ws.unit_count,
  })),
)

const mappedUnits = computed<WorkspaceUnitRecord[]>(() =>
  props.units.map(u => ({
    unit: u.id,
    display_name: u.strategy_name || u.strategy_id || u.id,
    group_name: u.group_name || '',
    linked_group: '',
    sort_order: u.sort_order ?? 0,
    notes: '',
    pinned: false,
    lock_trading: Boolean(u.lock_trading),
    lock_running: Boolean(u.lock_running),
    state: u.run_status || 'idle',
    symbols: u.symbol ? [u.symbol] : [],
    exchanges: [],
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

async function handleExportToWorkspace(payload: ExportToWorkspacePayload): Promise<void> {
  if (!props.units.length) {
    ElMessage.warning(t('tradingUnits.selectUnitForExport'))
    throw new Error(t('tradingUnits.selectUnitForExport'))
  }
  if (!payload.target_workspace_id) {
    throw new Error(t('workspaceDialogs.researchWorkspace'))
  }
  try {
    const transferPayload = props.units.map(unit => buildTransferUnitPayload(unit, { includeTradingFields: false }))
    await workspaceApi.batchCreateUnits(payload.target_workspace_id, transferPayload)
    ElMessage.success(`${t('workspaceDialogs.exported')} ${transferPayload.length} ${t('workspaceDialogs.nUnits')} -> ${t('workspaceDialogs.researchWorkspace')}`)
    emit('exported', transferPayload.length)
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.exportFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

async function handleExportFile(): Promise<void> {
  if (!props.units.length) {
    ElMessage.warning(t('tradingUnits.selectUnitForExport'))
    throw new Error(t('tradingUnits.selectUnitForExport'))
  }
  try {
    const transferPayload = props.units.map(unit => buildTransferUnitPayload(unit, { includeTradingFields: true }))
    downloadTransferUnits(transferPayload, 'trading_units')
    ElMessage.success(`${t('workspaceDialogs.exported')} ${transferPayload.length} ${t('workspaceDialogs.nUnits')}`)
    emit('exported', transferPayload.length)
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.exportFailed'))
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
