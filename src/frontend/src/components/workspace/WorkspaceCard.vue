<template>
  <SharedWorkspaceCard
    :workspace="summary"
    variant="catalog"
    :selected="selected"
    :can-edit="true"
    :can-delete="true"
    :status-label="statusLabel"
    :status-tag-type="statusTagType"
    :unit-count-text="t('workspace.unitCountInline', { n: workspace.unit_count })"
    :completed-count-text="t('workspace.completedInline', { n: workspace.completed_count })"
    :created-text="`${t('workspace.createdInline')}: ${formatTime(workspace.created_at)}`"
    :updated-text="`${t('workspace.updatedInline')}: ${formatTime(workspace.updated_at)}`"
    @click="emit('click')"
    @edit="emit('edit')"
    @delete="emit('delete')"
    @toggle-select="emit('toggle-select')"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  WorkspaceCard as SharedWorkspaceCard,
  type WorkspaceSummaryItem,
} from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import type { Workspace } from '@/types/workspace'
import type { TagType } from '@/constants/strategy'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  workspace: Workspace
  selected: boolean
}>()

const emit = defineEmits<{
  click: []
  edit: []
  delete: []
  'toggle-select': []
}>()

const summary = computed<WorkspaceSummaryItem>(() => ({
  id: props.workspace.id,
  name: props.workspace.name,
  description: props.workspace.description,
  workspace_type: props.workspace.workspace_type,
  status: props.workspace.status,
  total_units: props.workspace.unit_count,
  completed_count: props.workspace.completed_count,
  created_at: props.workspace.created_at,
  updated_at: props.workspace.updated_at,
}))

const statusTagType = computed<TagType>(() => {
  const map: Record<string, TagType> = { idle: 'info', running: 'warning', completed: 'success', error: 'danger' }
  return map[props.workspace.status] || 'info'
})

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    idle: t('workspace.statusIdle'),
    running: t('workspace.statusRunning'),
    completed: t('workspace.statusCompleted'),
    error: t('workspace.statusError'),
  }
  return map[props.workspace.status] || props.workspace.status
})

function formatTime(iso: string): string {
  if (!iso) return ''
  return new Date(iso).toLocaleString()
}
</script>
