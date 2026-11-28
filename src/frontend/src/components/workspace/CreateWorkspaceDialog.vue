<template>
  <SharedCreateWorkspaceDialog
    :model-value="modelValue"
    :workspace="mappedWorkspace"
    :workspace-type="targetWorkspaceType"
    :title="dialogTitle"
    :max-name-length="200"
    :max-desc-length="500"
    :on-save="handleSave"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  CreateWorkspaceDialog as SharedCreateWorkspaceDialog,
  type CreateWorkspacePayload,
  type WorkspaceSummaryItem,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { useWorkspaceStore } from '@/stores/workspace'
import type { Workspace, WorkspaceType } from '@/types/workspace'

const props = defineProps<{
  modelValue: boolean
  workspace?: Workspace | null
  workspaceType?: WorkspaceType
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const { t } = useI18n()
useWorkspaceUiBridge()

const store = useWorkspaceStore()

const isEdit = computed(() => Boolean(props.workspace))
const targetWorkspaceType = computed<WorkspaceType>(() =>
  props.workspace?.workspace_type ?? props.workspaceType ?? 'research',
)
const dialogTitle = computed(() => {
  const label = targetWorkspaceType.value === 'trading'
    ? t('workspace.tradingWorkspaceLabel')
    : t('workspace.workspaceLabelType')
  return isEdit.value ? `${t('workspace.editPrefix')}${label}` : `${t('workspace.newPrefix')}${label}`
})

const mappedWorkspace = computed<WorkspaceSummaryItem | null>(() => {
  if (!props.workspace) return null
  return {
    id: props.workspace.id,
    name: props.workspace.name,
    description: props.workspace.description,
    workspace_type: props.workspace.workspace_type,
    total_units: props.workspace.unit_count,
  }
})

async function handleSave(payload: CreateWorkspacePayload): Promise<void> {
  try {
    if (isEdit.value && props.workspace) {
      await store.updateWorkspace(props.workspace.id, {
        name: payload.name,
        description: payload.description || undefined,
      })
      ElMessage.success(t('workspace.saveSuccess'))
    } else {
      await store.createWorkspace({
        name: payload.name,
        description: payload.description || undefined,
        workspace_type: targetWorkspaceType.value,
      })
      ElMessage.success(t('workspace.createSuccess'))
    }
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspace.saveError'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
