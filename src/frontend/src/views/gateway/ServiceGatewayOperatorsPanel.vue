<template>
  <section
    class="gateway-panel service-operator-panel"
    data-test="service-gateway-operators"
  >
    <header class="operator-panel-heading">
      <div>
        <div class="gateway-kicker">
          {{ t('gatewayStatus.operatorKicker') }}
        </div>
        <h2>{{ t('gatewayStatus.operatorTitle') }}</h2>
        <p>{{ t('gatewayStatus.operatorDesc') }}</p>
      </div>
      <el-button
        data-test="operator-refresh"
        :loading="loading"
        :disabled="loading || busyProfile !== null"
        @click="refresh"
      >
        {{ t('gatewayStatus.btnRefresh') }}
      </el-button>
    </header>

    <p class="operator-boundary-note">
      {{ t('gatewayStatus.operatorBoundaryNote') }}
    </p>

    <div
      v-if="loading && profiles.length === 0"
      class="operator-message"
      data-test="operator-loading"
    >
      {{ t('gatewayStatus.operatorLoading') }}
    </div>
    <div
      v-else-if="listErrorKey"
      class="operator-message operator-error"
      role="alert"
      data-test="operator-list-error"
    >
      {{ t(listErrorKey) }}
    </div>
    <div
      v-else-if="profiles.length === 0"
      class="operator-message"
      data-test="operator-empty"
    >
      {{ t('gatewayStatus.operatorEmpty') }}
    </div>

    <div
      v-else
      class="operator-list"
    >
      <article
        v-for="profile in profiles"
        :key="profile.profile_ref"
        class="operator-card"
        :data-test="`operator-card-${profile.profile_ref}`"
      >
        <div class="operator-card-heading">
          <div class="operator-identity">
            <strong>{{ profile.profile_ref }}</strong>
            <span>
              {{ roleLabel(profile.role) }}
              <template v-if="profile.account_ref"> · {{ profile.account_ref }}</template>
            </span>
          </div>
          <el-tag
            v-if="statuses[profile.profile_ref]"
            :type="statuses[profile.profile_ref]?.ready ? 'success' : 'info'"
            size="small"
          >
            {{ statuses[profile.profile_ref]?.state }}
          </el-tag>
        </div>

        <div
          v-if="statuses[profile.profile_ref]"
          class="operator-status-grid"
        >
          <span>{{ t('gatewayStatus.operatorReady') }}</span>
          <strong>{{ statuses[profile.profile_ref]?.ready ? t('gatewayStatus.operatorReadyYes') : t('gatewayStatus.operatorReadyNo') }}</strong>
          <span>{{ t('gatewayStatus.operatorOperation') }}</span>
          <strong>
            {{ statuses[profile.profile_ref]?.operation.name || '—' }}
            · {{ statuses[profile.profile_ref]?.operation.state }}
          </strong>
          <template v-if="statuses[profile.profile_ref]?.account_session">
            <span>{{ t('gatewayStatus.operatorSessionGeneration') }}</span>
            <strong>{{ statuses[profile.profile_ref]?.account_session?.session_generation || '—' }}</strong>
            <span>{{ t('gatewayStatus.operatorSessionFreshness') }}</span>
            <strong>{{ statuses[profile.profile_ref]?.account_session?.fresh_for_seconds }}s</strong>
          </template>
          <span>{{ t('gatewayStatus.operatorCleanup') }}</span>
          <strong>{{ statuses[profile.profile_ref]?.cleanup.unclaimed_provider_count ?? t('gatewayStatus.operatorUnknownValue') }}</strong>
        </div>
        <p
          v-if="statusErrorKeys[profile.profile_ref]"
          class="operator-error"
          role="alert"
          :data-test="`operator-status-error-${profile.profile_ref}`"
        >
          {{ t(statusErrorKeys[profile.profile_ref] || 'gatewayStatus.operatorUnavailable') }}
        </p>
        <p
          v-else-if="failureCode(statuses[profile.profile_ref])"
          class="operator-error"
        >
          {{ t('gatewayStatus.operatorFailureCode', { code: failureCode(statuses[profile.profile_ref]) }) }}
        </p>
        <p
          v-if="profile.auto_start"
          class="operator-auto-start"
        >
          {{ t('gatewayStatus.operatorServerAutoStart') }}
        </p>

        <div class="operator-actions">
          <el-button
            v-if="canStart(profile, statuses[profile.profile_ref])"
            data-test="operator-start"
            type="primary"
            :loading="busyProfile === profile.profile_ref"
            :disabled="loading || operationRunning(profile.profile_ref)"
            @click="act(profile, 'start')"
          >
            {{ t('gatewayStatus.operatorStart') }}
          </el-button>
          <el-button
            v-if="canRecover(profile, statuses[profile.profile_ref])"
            data-test="operator-recover"
            :loading="busyProfile === profile.profile_ref"
            :disabled="loading || operationRunning(profile.profile_ref)"
            @click="act(profile, 'recover')"
          >
            {{ t('gatewayStatus.operatorRecover') }}
          </el-button>
          <el-button
            v-if="canStop(profile, statuses[profile.profile_ref])"
            data-test="operator-stop"
            type="warning"
            :loading="busyProfile === profile.profile_ref"
            :disabled="loading || operationRunning(profile.profile_ref)"
            @click="act(profile, 'stop')"
          >
            {{ t('gatewayStatus.operatorStop') }}
          </el-button>
          <el-button
            v-if="canCleanup(profile, statuses[profile.profile_ref])"
            data-test="operator-cleanup"
            type="danger"
            plain
            :loading="busyProfile === profile.profile_ref"
            :disabled="loading || operationRunning(profile.profile_ref)"
            @click="act(profile, 'cleanup')"
          >
            {{ t('gatewayStatus.operatorCleanupAction') }}
          </el-button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  serviceGatewayOperatorApi,
  type ServiceGatewayOperatorAction,
  type ServiceGatewayOperatorProfile,
  type ServiceGatewayOperatorRole,
  type ServiceGatewayOperatorStatus,
} from '@/api/serviceGatewayOperator'

const { t } = useI18n()
const profiles = ref<ServiceGatewayOperatorProfile[]>([])
const statuses = ref<Record<string, ServiceGatewayOperatorStatus | undefined>>({})
const statusErrorKeys = ref<Record<string, string | undefined>>({})
const listErrorKey = ref('')
const loading = ref(false)
const busyProfile = ref<string | null>(null)

const knownOperations = new Set(['status', 'start', 'stop', 'recover', 'cleanup'])

function isProfile(value: unknown): value is ServiceGatewayOperatorProfile {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<ServiceGatewayOperatorProfile>
  const operations = candidate.operations
  return typeof candidate.profile_ref === 'string'
    && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(candidate.profile_ref)
    && (candidate.role === 'account_session_worker' || candidate.role === 'market_hub')
    && (candidate.role === 'account_session_worker'
      ? typeof candidate.account_ref === 'string'
      : candidate.account_ref === null)
    && Array.isArray(operations)
    && operations.every((operation) => typeof operation === 'string' && knownOperations.has(operation))
    && new Set(operations).size === operations.length
    && (['status', 'start', 'stop'] as const).every((operation) => operations.includes(operation))
    && (candidate.role !== 'market_hub' || !operations.includes('recover'))
    && typeof candidate.auto_start === 'boolean'
}

function isStatusForProfile(
  status: ServiceGatewayOperatorStatus,
  profile: ServiceGatewayOperatorProfile,
): boolean {
  return status.profile_ref === profile.profile_ref
    && status.role === profile.role
    && status.account_ref === profile.account_ref
}

function getOperatorErrorKey(error: unknown): string {
  if (!error || typeof error !== 'object' || !('response' in error)) {
    return 'gatewayStatus.operatorUnavailable'
  }
  const response = (error as { response?: { status?: number; data?: { detail?: { code?: unknown } } } }).response
  const code = response?.data?.detail?.code
  if (code === 'OPERATOR_NOT_CONFIGURED') return 'gatewayStatus.operatorNotConfigured'
  if (code === 'OWNER_NOT_AUTHORIZED' || code === 'OPERATION_NOT_GRANTED' || response?.status === 401 || response?.status === 403) {
    return 'gatewayStatus.operatorForbidden'
  }
  return 'gatewayStatus.operatorUnavailable'
}

async function refresh() {
  if (loading.value || busyProfile.value !== null) return
  loading.value = true
  listErrorKey.value = ''
  try {
    const result = await serviceGatewayOperatorApi.list()
    if (!result || !Array.isArray(result.operators) || !result.operators.every(isProfile)) {
      throw new Error('INVALID_OPERATOR_LIST')
    }
    profiles.value = result.operators
    statuses.value = {}
    statusErrorKeys.value = {}
    await Promise.all(profiles.value.map(async (profile) => {
      try {
        const status = await serviceGatewayOperatorApi.status(profile.profile_ref)
        if (!isStatusForProfile(status, profile)) throw new Error('OPERATOR_STATUS_BINDING_MISMATCH')
        statuses.value[profile.profile_ref] = status
      } catch (error) {
        statusErrorKeys.value[profile.profile_ref] = getOperatorErrorKey(error)
      }
    }))
  } catch (error) {
    profiles.value = []
    statuses.value = {}
    statusErrorKeys.value = {}
    listErrorKey.value = getOperatorErrorKey(error)
  } finally {
    loading.value = false
  }
}

function roleLabel(role: ServiceGatewayOperatorRole): string {
  return role === 'market_hub'
    ? t('gatewayStatus.operatorMarketRole')
    : t('gatewayStatus.operatorAccountRole')
}

function operationRunning(profileRef: string): boolean {
  return statuses.value[profileRef]?.operation.state === 'running' || busyProfile.value === profileRef
}

function failureCode(status?: ServiceGatewayOperatorStatus): string | null {
  const code = status?.error_code || status?.operation.error_code || status?.cleanup.last_cleanup_code
  return typeof code === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(code) ? code : null
}

function canStart(profile: ServiceGatewayOperatorProfile, status?: ServiceGatewayOperatorStatus): boolean {
  return profile.operations.includes('start')
    && status !== undefined
    && ['new', 'closed', 'failed'].includes(status.state)
    && status.operation.state !== 'outcome_uncertain'
    && status.cleanup.unclaimed_provider_count === 0
}

function canStop(profile: ServiceGatewayOperatorProfile, status?: ServiceGatewayOperatorStatus): boolean {
  return profile.operations.includes('stop')
    && status !== undefined
    && !['new', 'closed'].includes(status.state)
}

function canRecover(profile: ServiceGatewayOperatorProfile, status?: ServiceGatewayOperatorStatus): boolean {
  return profile.operations.includes('recover')
    && profile.role === 'account_session_worker'
    && status?.state === 'running'
    && status.account_session?.ready !== true
}

function canCleanup(profile: ServiceGatewayOperatorProfile, status?: ServiceGatewayOperatorStatus): boolean {
  return profile.operations.includes('cleanup')
    && status !== undefined
    && typeof status.cleanup.unclaimed_provider_count === 'number'
    && status.cleanup.unclaimed_provider_count > 0
}

async function act(profile: ServiceGatewayOperatorProfile, action: ServiceGatewayOperatorAction) {
  if (!profile.operations.includes(action) || busyProfile.value !== null || loading.value) return
  busyProfile.value = profile.profile_ref
  statusErrorKeys.value[profile.profile_ref] = undefined
  try {
    const status = await serviceGatewayOperatorApi.act(profile.profile_ref, action)
    if (!isStatusForProfile(status, profile)) throw new Error('OPERATOR_STATUS_BINDING_MISMATCH')
    statuses.value[profile.profile_ref] = status
  } catch (error) {
    statusErrorKeys.value[profile.profile_ref] = getOperatorErrorKey(error)
    try {
      const latest = await serviceGatewayOperatorApi.status(profile.profile_ref)
      if (isStatusForProfile(latest, profile)) {
        statuses.value[profile.profile_ref] = latest
        if (failureCode(latest)) statusErrorKeys.value[profile.profile_ref] = undefined
      } else {
        delete statuses.value[profile.profile_ref]
      }
    } catch {
      delete statuses.value[profile.profile_ref]
    }
  } finally {
    busyProfile.value = null
  }
}

onMounted(() => {
  void refresh()
})
</script>

<style scoped>
.service-operator-panel {
  padding: 18px;
}

.operator-panel-heading,
.operator-card-heading,
.operator-actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.operator-panel-heading h2 {
  margin: 5px 0 7px;
  font-size: 18px;
}

.operator-panel-heading p,
.operator-boundary-note,
.operator-message {
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.operator-boundary-note {
  padding: 10px 12px;
  border: 1px solid var(--border-color-light);
  border-radius: 6px;
  background: var(--fill-color-lighter);
}

.operator-list {
  display: grid;
  gap: 12px;
}

.operator-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border-color-light);
  border-radius: 7px;
}

.operator-identity {
  display: grid;
  gap: 5px;
  overflow-wrap: anywhere;
}

.operator-identity span,
.operator-auto-start {
  color: var(--text-color-secondary);
  font-size: 12px;
}

.operator-status-grid {
  display: grid;
  grid-template-columns: minmax(140px, 0.4fr) minmax(0, 1fr);
  gap: 7px 12px;
}

.operator-status-grid span {
  color: var(--text-color-secondary);
}

.operator-status-grid strong {
  overflow-wrap: anywhere;
}

.operator-actions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.operator-error {
  color: var(--danger-color);
}

@media (max-width: 620px) {
  .operator-panel-heading,
  .operator-card-heading {
    display: grid;
  }

  .operator-status-grid {
    grid-template-columns: 1fr;
  }

  .operator-actions {
    justify-content: flex-start;
  }
}
</style>
