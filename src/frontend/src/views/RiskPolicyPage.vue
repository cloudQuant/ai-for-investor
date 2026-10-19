<template>
  <section class="risk-policy-page">
    <header class="page-header">
      <div>
        <p class="page-kicker">
          {{ t('riskPolicies.kicker') }}
        </p>
        <h1>{{ t('riskPolicies.title') }}</h1>
        <p>{{ t('riskPolicies.subtitle') }}</p>
      </div>
      <el-button
        :loading="refreshing"
        :disabled="!rows.length || refreshing"
        @click="refreshAll"
      >
        {{ t('riskPolicies.refresh') }}
      </el-button>
    </header>

    <section
      class="publication-boundary"
      role="note"
    >
      <strong>{{ t('riskPolicies.publicationBoundaryTitle') }}</strong>
      <p>{{ t('riskPolicies.publicationBoundary') }}</p>
      <p>{{ t('riskPolicies.consumerBoundary') }}</p>
    </section>

    <section
      class="activation-summary"
      role="status"
      aria-live="polite"
      :data-state="summaryState"
    >
      <strong>{{ summaryTitle }}</strong>
      <p>{{ summaryDescription }}</p>
      <small>{{ t('riskPolicies.trackedOnly') }}</small>
    </section>

    <div class="policy-tools">
      <el-card class="tool-card">
        <template #header>
          <strong>{{ t('riskPolicies.lookupTitle') }}</strong>
        </template>
        <form
          class="policy-tracker-form"
          @submit.prevent="trackPolicy"
        >
          <label>
            <span>{{ t('riskPolicies.accountRef') }}</span>
            <el-input
              v-model="lookup.accountRef"
              autocomplete="off"
              :placeholder="t('riskPolicies.accountRefPlaceholder')"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.policyRef') }}</span>
            <el-input
              v-model="lookup.policyRef"
              autocomplete="off"
              :placeholder="t('riskPolicies.policyRefPlaceholder')"
            />
          </label>
          <el-button
            native-type="submit"
            type="primary"
            :loading="addingPolicy"
          >
            {{ t('riskPolicies.trackPolicy') }}
          </el-button>
        </form>
        <p
          v-if="lookupError"
          class="form-error"
          role="alert"
        >
          {{ lookupError }}
        </p>
      </el-card>

      <el-card class="tool-card">
        <template #header>
          <strong>{{ t('riskPolicies.draftTitle') }}</strong>
        </template>
        <form
          class="policy-draft-form"
          @submit.prevent="createDraft"
        >
          <label>
            <span>{{ t('riskPolicies.accountRef') }}</span>
            <el-input
              v-model="draft.accountRef"
              autocomplete="off"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.policyRef') }}</span>
            <el-input
              v-model="draft.policyRef"
              autocomplete="off"
              :placeholder="t('riskPolicies.policyRefPlaceholder')"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.maxIncreaseNotional') }}</span>
            <el-input
              v-model="draft.maxIncreaseNotional"
              inputmode="decimal"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.maxIncreaseCount') }}</span>
            <el-input-number
              v-model="draft.maxIncreaseCount"
              :min="0"
              :max="1000000"
              :step="1"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.permitTtlSeconds') }}</span>
            <el-input-number
              v-model="draft.permitTtlSeconds"
              :min="1"
              :max="86400"
              :step="1"
            />
          </label>
          <label>
            <span>{{ t('riskPolicies.notionalUnit') }}</span>
            <el-input
              v-model="draft.notionalUnit"
              autocomplete="off"
              :placeholder="t('riskPolicies.notionalUnitPlaceholder')"
            />
          </label>
          <el-checkbox v-model="draft.requireStrategyAllocation">
            {{ t('riskPolicies.requireStrategyAllocation') }}
          </el-checkbox>
          <el-button
            native-type="submit"
            type="primary"
            :loading="creatingDraft"
          >
            {{ t('riskPolicies.createDraft') }}
          </el-button>
        </form>
        <p
          v-if="draftError"
          class="form-error"
          role="alert"
        >
          {{ draftError }}
        </p>
      </el-card>
    </div>

    <p class="authorization-note">
      {{ t('riskPolicies.authorizationNote') }}
    </p>

    <el-empty
      v-if="!rows.length"
      :description="t('riskPolicies.empty')"
    />

    <div
      v-else
      class="policy-list"
    >
      <article
        v-for="row in rows"
        :key="row.key"
        class="policy-card"
        :data-policy-state="statusKind(row)"
      >
        <header class="policy-card-header">
          <div>
            <h2>{{ row.accountRef }}</h2>
            <p>{{ t('riskPolicies.policyRef') }}: {{ row.policyRef }}</p>
          </div>
          <el-tag :type="statusTagType(row)">
            {{ statusLabel(row) }}
          </el-tag>
        </header>

        <p
          v-if="row.loadError"
          class="form-error"
          role="alert"
        >
          {{ row.loadError }}
        </p>
        <p
          v-if="row.actionError"
          class="form-error"
          role="alert"
        >
          {{ row.actionError }}
        </p>

        <dl
          v-if="row.policy"
          class="policy-version-grid"
        >
          <div>
            <dt>{{ t('riskPolicies.policyVersion') }}</dt>
            <dd>{{ row.policy.policy_version }}</dd>
          </div>
          <div>
            <dt>{{ t('riskPolicies.confirmedVersion') }}</dt>
            <dd>{{ row.policy.owner_confirmed_version || t('riskPolicies.noConfirmedVersion') }}</dd>
          </div>
          <div>
            <dt>{{ t('riskPolicies.maxIncreaseNotional') }}</dt>
            <dd>{{ row.policy.risk_policy.max_increase_notional }}</dd>
          </div>
          <div>
            <dt>{{ t('riskPolicies.confirmationDocument') }}</dt>
            <dd>{{ row.policy.owner_document_available ? t('riskPolicies.available') : t('riskPolicies.confirmationUnavailable') }}</dd>
          </div>
        </dl>

        <div class="policy-actions">
          <el-button
            :loading="row.loading"
            @click="refreshRow(row)"
          >
            {{ t('riskPolicies.refresh') }}
          </el-button>
          <el-button
            v-if="row.policy?.state === 'draft'"
            :loading="row.actionLoading"
            @click="approvePolicy(row)"
          >
            {{ t('riskPolicies.checkerApprove') }}
          </el-button>
          <el-button
            v-if="row.policy?.state === 'approved'"
            :loading="row.actionLoading"
            type="primary"
            @click="publishPolicy(row)"
          >
            {{ t('riskPolicies.makerPublish') }}
          </el-button>
          <el-button @click="removePolicy(row)">
            {{ t('riskPolicies.remove') }}
          </el-button>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getErrorMessage } from '@/api'
import {
  riskPolicyApi,
  type AccountRiskPolicyDraft,
  type AccountRiskPolicyView,
} from '@/api/riskPolicy'

type StatusKind = 'draft' | 'approved' | 'awaiting' | 'confirmed' | 'mismatch' | 'unavailable' | 'loading'

interface PolicyRow {
  key: string
  accountRef: string
  policyRef: string
  policy: AccountRiskPolicyView | null
  loading: boolean
  actionLoading: boolean
  loadError: string
  actionError: string
}

const { t } = useI18n()
const rows = ref<PolicyRow[]>([])
const refreshing = ref(false)
const addingPolicy = ref(false)
const creatingDraft = ref(false)
const lookupError = ref('')
const draftError = ref('')
const lookup = reactive({ accountRef: '', policyRef: '' })
const draft = reactive({
  accountRef: '',
  policyRef: '',
  maxIncreaseNotional: '0',
  maxIncreaseCount: 1,
  permitTtlSeconds: 60,
  requireStrategyAllocation: true,
  notionalUnit: '',
})

const loadedRows = computed(() => rows.value.filter((row) => row.policy !== null))
const confirmedCount = computed(() => loadedRows.value.filter((row) => statusKind(row) === 'confirmed').length)
const publishedPendingCount = computed(() => loadedRows.value.filter((row) => statusKind(row) === 'awaiting').length)
const hasReadErrors = computed(() => rows.value.some((row) => Boolean(row.loadError)))
const summaryState = computed(() => {
  if (confirmedCount.value > 0 && (publishedPendingCount.value > 0 || hasReadErrors.value)) return 'partial'
  if (confirmedCount.value > 0 && confirmedCount.value === rows.value.length) return 'all-tracked-confirmed'
  if (confirmedCount.value > 0) return 'partial'
  if (publishedPendingCount.value > 0) return 'awaiting'
  if (hasReadErrors.value) return 'check-required'
  if (loadedRows.value.length > 0) return 'not-confirmed'
  return 'empty'
})
const summaryTitle = computed(() => t(`riskPolicies.summaryTitle.${summaryState.value}`))
const summaryDescription = computed(() => t(`riskPolicies.summary.${summaryState.value}`))

function rowKey(accountRef: string, policyRef: string): string {
  return `${accountRef}\u0000${policyRef}`
}

function statusKind(row: PolicyRow): StatusKind {
  const policy = row.policy
  if (row.loading && !policy) return 'loading'
  if (!policy || row.loadError) return 'unavailable'
  if (policy.state === 'draft') return 'draft'
  if (policy.state === 'approved') return 'approved'
  if (
    policy.state === 'published'
    && policy.owner_confirmed === true
    && policy.owner_confirmed_version === policy.policy_version
    && policy.owner_document_available === true
  ) return 'confirmed'
  if (
    policy.state === 'published'
    && policy.owner_confirmed === false
    && policy.owner_confirmed_version === null
    && policy.owner_document_available === false
  ) return 'awaiting'
  return 'mismatch'
}

function statusLabel(row: PolicyRow): string {
  const labels: Record<StatusKind, string> = {
    draft: 'riskPolicies.stateDraft',
    approved: 'riskPolicies.stateApproved',
    awaiting: 'riskPolicies.stateAwaiting',
    confirmed: 'riskPolicies.stateConfirmed',
    mismatch: 'riskPolicies.stateMismatch',
    unavailable: 'riskPolicies.stateUnavailable',
    loading: 'riskPolicies.stateLoading',
  }
  return t(labels[statusKind(row)])
}

function statusTagType(row: PolicyRow): 'success' | 'warning' | 'danger' | 'info' {
  const kind = statusKind(row)
  if (kind === 'confirmed') return 'success'
  if (kind === 'mismatch' || kind === 'unavailable') return 'danger'
  if (kind === 'awaiting' || kind === 'approved') return 'warning'
  return 'info'
}

function requestError(reason: unknown, fallbackKey: string): string {
  const status = (reason as { response?: { status?: unknown } } | null)?.response?.status
  if (status === 403) return t('riskPolicies.permissionDenied')
  return getErrorMessage(reason, t(fallbackKey))
}

function ensureRow(accountRef: string, policyRef: string): PolicyRow {
  const key = rowKey(accountRef, policyRef)
  const existing = rows.value.find((row) => row.key === key)
  if (existing) return existing
  const row = reactive<PolicyRow>({
    key,
    accountRef,
    policyRef,
    policy: null,
    loading: false,
    actionLoading: false,
    loadError: '',
    actionError: '',
  })
  rows.value.push(row)
  return row
}

async function refreshRow(row: PolicyRow): Promise<void> {
  row.loading = true
  row.loadError = ''
  row.actionError = ''
  try {
    row.policy = await riskPolicyApi.read(row.accountRef, row.policyRef)
  } catch (reason) {
    row.policy = null
    row.loadError = requestError(reason, 'riskPolicies.policyReadFailed')
  } finally {
    row.loading = false
  }
}

async function trackPolicy(): Promise<void> {
  const accountRef = lookup.accountRef.trim()
  const policyRef = lookup.policyRef.trim()
  if (!accountRef || !policyRef) {
    lookupError.value = t('riskPolicies.invalidReference')
    return
  }
  lookupError.value = ''
  addingPolicy.value = true
  try {
    const row = ensureRow(accountRef, policyRef)
    await refreshRow(row)
    lookup.accountRef = ''
    lookup.policyRef = ''
  } finally {
    addingPolicy.value = false
  }
}

async function createDraft(): Promise<void> {
  const accountRef = draft.accountRef.trim()
  const policyRef = draft.policyRef.trim()
  const decimalPattern = /^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$/
  if (
    !accountRef
    || !/^[A-Za-z0-9][A-Za-z0-9._:-]*-v[1-9][0-9]*$/.test(policyRef)
    || !decimalPattern.test(draft.maxIncreaseNotional)
    || !Number.isInteger(draft.maxIncreaseCount)
    || draft.maxIncreaseCount < 0
    || !Number.isFinite(draft.permitTtlSeconds)
    || draft.permitTtlSeconds <= 0
    || draft.permitTtlSeconds > 86400
  ) {
    draftError.value = t('riskPolicies.invalidDraft')
    return
  }
  const body: AccountRiskPolicyDraft = {
    policy_ref: policyRef,
    max_increase_notional: draft.maxIncreaseNotional,
    max_increase_count: draft.maxIncreaseCount,
    permit_ttl_seconds: draft.permitTtlSeconds,
    require_strategy_allocation: draft.requireStrategyAllocation,
    notional_unit: draft.notionalUnit.trim() || null,
  }
  draftError.value = ''
  creatingDraft.value = true
  try {
    await riskPolicyApi.draft(accountRef, body)
    const row = ensureRow(accountRef, policyRef)
    await refreshRow(row)
  } catch (reason) {
    draftError.value = requestError(reason, 'riskPolicies.draftFailed')
  } finally {
    creatingDraft.value = false
  }
}

async function runPolicyAction(row: PolicyRow, action: 'approve' | 'publish'): Promise<void> {
  row.actionLoading = true
  row.actionError = ''
  try {
    if (action === 'approve') {
      await riskPolicyApi.approve(row.accountRef, row.policyRef)
    } else {
      await riskPolicyApi.publish(row.accountRef, row.policyRef)
    }
    await refreshRow(row)
  } catch (reason) {
    row.actionError = requestError(reason, 'riskPolicies.actionFailed')
  } finally {
    row.actionLoading = false
  }
}

function approvePolicy(row: PolicyRow): Promise<void> {
  return runPolicyAction(row, 'approve')
}

function publishPolicy(row: PolicyRow): Promise<void> {
  return runPolicyAction(row, 'publish')
}

function removePolicy(row: PolicyRow): void {
  rows.value = rows.value.filter((candidate) => candidate.key !== row.key)
}

async function refreshAll(): Promise<void> {
  refreshing.value = true
  try {
    await Promise.all(rows.value.map((row) => refreshRow(row)))
  } finally {
    refreshing.value = false
  }
}
</script>

<style scoped>
.risk-policy-page { display: grid; gap: 18px; }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.page-header h1 { margin: 0; }
.page-header p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.page-kicker { font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.publication-boundary, .activation-summary { padding: 16px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-fill-color-lighter); }
.publication-boundary p, .activation-summary p { margin: 6px 0; }
.activation-summary[data-state="partial"], .activation-summary[data-state="awaiting"], .activation-summary[data-state="not-confirmed"], .activation-summary[data-state="check-required"] { border-color: var(--el-color-warning); }
.policy-tools { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 16px; }
.policy-tracker-form, .policy-draft-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); align-items: end; gap: 12px; }
.policy-tracker-form label, .policy-draft-form label { display: grid; gap: 6px; }
.policy-draft-form label span, .policy-tracker-form label span { font-size: 13px; color: var(--el-text-color-regular); }
.authorization-note { margin: 0; color: var(--el-text-color-secondary); }
.policy-list { display: grid; gap: 12px; }
.policy-card { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color); }
.policy-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.policy-card-header h2 { margin: 0; font-size: 17px; }
.policy-card-header p { margin: 5px 0 0; color: var(--el-text-color-secondary); }
.policy-version-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 0; }
.policy-version-grid div { min-width: 0; }
.policy-version-grid dt { color: var(--el-text-color-secondary); font-size: 12px; }
.policy-version-grid dd { margin: 4px 0 0; overflow-wrap: anywhere; }
.policy-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.form-error { margin: 10px 0 0; color: var(--el-color-danger); }
@media (max-width: 640px) { .page-header { display: grid; } }
</style>
