<template>
  <SharedAutoTradingConfigDialog
    ref="innerRef"
    :model-value="modelValue"
    :config="loadedConfig"
    :scope-options="scopeOptions"
    :min-sessions="1"
    :external-schedule="schedule"
    :loading="loading"
    :show-plan-notice="false"
    :default-session-name-prefix="t('workspaceDialogs.sessionTime')"
    :on-refresh="loadConfig"
    :on-save="handlePersist"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import type { AutoTradingConfig, AutoTradingSession } from '@bt-api/workspace-ui/core'
import { AutoTradingConfigDialog as SharedAutoTradingConfigDialog } from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { getErrorMessage } from '@/api/index'
import { workspaceApi } from '@/api/workspace'
import type { TradingAutoConfig, TradingAutoScheduleItem } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [payload: { config: TradingAutoConfig; schedule: TradingAutoScheduleItem[] }]
}>()

function createDefaultConfig(): TradingAutoConfig {
  return {
    enabled: false,
    buffer_minutes: 15,
    sessions: [
      { name: t('workspaceDialogs.daySession'), open: '09:00', close: '15:00' },
      { name: t('workspaceDialogs.nightSession'), open: '21:00', close: '23:00' },
    ],
    scope: 'all',
  }
}

const innerRef = ref<InstanceType<typeof SharedAutoTradingConfigDialog> | null>(null)
const loadedConfig = ref<TradingAutoConfig>(createDefaultConfig())
const schedule = ref<TradingAutoScheduleItem[]>([])
const loading = ref(false)

const scopeOptions = computed<Array<{ value: AutoTradingConfig['scope']; label: string }>>(() => [
  { value: 'all', label: t('workspaceDialogs.sessionScopeAll') },
  { value: 'live', label: t('workspaceDialogs.sessionScopeLive') },
  { value: 'simulation', label: t('workspaceDialogs.sessionScopePaper') },
])

const form = computed(() => innerRef.value?.form)
const scopeLabel = computed(() => innerRef.value?.scopeLabel ?? '')

function addSession(): void {
  innerRef.value?.addSession()
}

function removeSession(index: number): void {
  innerRef.value?.removeSession(index)
}

function normalizeSessions(): AutoTradingSession[] {
  return innerRef.value?.normalizeSessions() ?? []
}

function assignForm(config: TradingAutoConfig): void {
  loadedConfig.value = {
    ...config,
    sessions: config.sessions.map(session => ({ ...session })),
  }
  innerRef.value?.assignForm(config)
}

async function loadConfig(): Promise<void> {
  loading.value = true
  try {
    const [config, scheduleResponse] = await Promise.all([
      workspaceApi.getTradingAutoConfig(props.workspaceId),
      workspaceApi.getTradingAutoSchedule(props.workspaceId),
    ])
    assignForm(config)
    schedule.value = scheduleResponse
  } catch (error: unknown) {
    ElMessage.error(getErrorMessage(error, t('workspaceDialogs.loadAutoFailed')))
  } finally {
    loading.value = false
  }
}

async function handlePersist(payload: AutoTradingConfig): Promise<void> {
  loading.value = true
  try {
    const updatedConfig = await workspaceApi.updateTradingAutoConfig(props.workspaceId, {
      enabled: payload.enabled,
      buffer_minutes: payload.buffer_minutes,
      scope: payload.scope as TradingAutoConfig['scope'],
      sessions: payload.sessions,
    })
    const scheduleResponse = await workspaceApi.getTradingAutoSchedule(props.workspaceId)
    assignForm(updatedConfig)
    schedule.value = scheduleResponse
    emit('saved', {
      config: {
        ...updatedConfig,
        sessions: updatedConfig.sessions.map(s => ({ ...s })),
      },
      schedule: scheduleResponse.map(item => ({ ...item })),
    })
    ElMessage.success(`${t('workspaceDialogs.autoTradingTitle')} ${t('workspaceDialogs.save')}`)
  } catch (error: unknown) {
    const message = getErrorMessage(error, t('workspaceDialogs.saveAutoFailed'))
    ElMessage.error(message)
    throw new Error(message)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) {
      void loadConfig()
    }
  },
)

defineExpose({ form, scopeLabel, addSession, removeSession, normalizeSessions, assignForm, loadConfig })
</script>
