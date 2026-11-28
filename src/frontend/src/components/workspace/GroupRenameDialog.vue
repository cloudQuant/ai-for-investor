<template>
  <SharedGroupRenameDialog
    :model-value="modelValue"
    :unit-names="unitIds"
    :modes="['custom', 'strategy', 'symbol', 'symbol_name', 'category', 'replace']"
    :title="t('workspaceDialogs.rnGroupTitle')"
    :show-chips="false"
    :on-save="handleSave"
    @update:model-value="emit('update:modelValue', $event)"
    @saved="emit('saved')"
  />
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { GroupRenameDialog as SharedGroupRenameDialog, type RenamePayload } from '@bt-api/workspace-ui/core'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { useWorkspaceStore } from '@/stores/workspace'
import { getErrorMessage } from '@/api/index'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unitIds: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const store = useWorkspaceStore()

type LocalRenameMode = 'custom' | 'strategy' | 'symbol' | 'symbol_name' | 'category' | 'replace'

async function handleSave(payload: RenamePayload): Promise<void> {
  if (!props.unitIds.length) return
  try {
    await store.renameGroup(props.workspaceId, {
      unit_ids: [...props.unitIds],
      mode: payload.mode as LocalRenameMode,
      value: payload.value,
      search: payload.search,
      replace: payload.replace,
    })
    ElMessage.success(t('workspaceDialogs.rnGroupRenamed'))
  } catch (e: unknown) {
    const message = getErrorMessage(e, t('workspaceDialogs.rnRenameFailed'))
    ElMessage.error(message)
    throw new Error(message)
  }
}
</script>
