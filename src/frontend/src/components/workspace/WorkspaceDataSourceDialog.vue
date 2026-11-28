<template>
  <SharedWorkspaceDataSourceDialog
    ref="innerRef"
    :model-value="modelValue"
    :config="workspace?.settings?.data_source ?? null"
    :on-save="handlePersist"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { WorkspaceDataSourceConfig as SharedDataSourceConfig } from '@bt-api/workspace-ui/core'
import { WorkspaceDataSourceDialog as SharedWorkspaceDataSourceDialog } from '@bt-api/workspace-ui/research'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { useWorkspaceStore } from '@/stores/workspace'
import { getErrorMessage } from '@/api/index'
import type { Workspace } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  workspace: Workspace | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const store = useWorkspaceStore()
const innerRef = ref<InstanceType<typeof SharedWorkspaceDataSourceDialog> | null>(null)

const form = computed(() => innerRef.value?.form)
const saving = computed(() => Boolean(innerRef.value?.saving))

function initForm(): void {
  innerRef.value?.initForm()
}

async function handleSave(): Promise<void> {
  await innerRef.value?.handleSave()
}

async function handlePersist(payload: SharedDataSourceConfig): Promise<void> {
  try {
    await store.updateWorkspace(props.workspaceId, {
      settings: {
        data_source: JSON.parse(JSON.stringify(payload)),
      },
    })
    ElMessage.success(t('workspaceDialogs.wsDataSourceSaved'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.dataSourceSaveFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}

defineExpose({ form, saving, initForm, handleSave })
</script>
