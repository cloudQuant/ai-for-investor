<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { serviceGatewayApi, type ServiceGatewayHealth } from '@/api/serviceGateway'

const { t } = useI18n()
const accountRef = ref('')
const loading = ref(false)
const error = ref('')
const health = ref<ServiceGatewayHealth | null>(null)

async function readHealth() {
  const selector = accountRef.value.trim()
  if (!selector || loading.value) return

  loading.value = true
  error.value = ''
  health.value = null
  try {
    health.value = await serviceGatewayApi.readAccountHealth(selector)
  } catch {
    // Render a closed local message; API or provider diagnostics are not UI data.
    error.value = t('gatewayHealth.readFailed')
  } finally {
    loading.value = false
  }
}

function statusLabel(value: string): string {
  const key = `gatewayHealth.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}
</script>

<template>
  <main class="service-gateway-health" aria-labelledby="service-gateway-health-title">
    <header class="service-gateway-health__header">
      <div>
        <h1 id="service-gateway-health-title">{{ t('gatewayHealth.title') }}</h1>
        <p>{{ t('gatewayHealth.description') }}</p>
      </div>
    </header>

    <form class="service-gateway-health__selector" @submit.prevent="readHealth">
      <label for="service-gateway-account-ref">{{ t('gatewayHealth.accountRef') }}</label>
      <div class="service-gateway-health__controls">
        <input
          id="service-gateway-account-ref"
          v-model="accountRef"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :placeholder="t('gatewayHealth.accountRefPlaceholder')"
        >
        <button type="submit" :disabled="loading || !accountRef.trim()">
          {{ loading ? t('common.loading') : t('gatewayHealth.readHealth') }}
        </button>
      </div>
    </form>

    <p class="service-gateway-health__note">{{ t('gatewayHealth.noCredentialNote') }}</p>
    <p v-if="error" class="service-gateway-health__error" role="alert">{{ error }}</p>

    <section v-if="health" class="service-gateway-health__facts" aria-live="polite">
      <h2>{{ health.account_ref }}</h2>
      <dl>
        <div>
          <dt>{{ t('gatewayHealth.serviceConnection') }}</dt>
          <dd data-testid="service-connection-status" :data-status="health.service_connection.rpc_status">
            {{ statusLabel(health.service_connection.rpc_status) }}
          </dd>
        </div>
        <div>
          <dt>{{ t('gatewayHealth.gatewaySession') }}</dt>
          <dd data-testid="gateway-session-status" :data-status="health.gateway_session.status">
            {{ statusLabel(health.gateway_session.status) }}
          </dd>
          <small v-if="health.gateway_session.session_generation">
            {{ t('gatewayHealth.generation') }}: {{ health.gateway_session.session_generation }}
          </small>
        </div>
        <div>
          <dt>{{ t('gatewayHealth.accountObservation') }}</dt>
          <dd data-testid="account-observation-status" :data-status="health.account_observation.status">
            {{ statusLabel(health.account_observation.status) }}
          </dd>
          <small>{{ t('gatewayHealth.quality') }}: {{ health.account_observation.quality }}</small>
          <small v-if="health.account_observation.cursor !== null">
            {{ t('gatewayHealth.cursor') }}: {{ health.account_observation.cursor }}
          </small>
        </div>
        <div>
          <dt>{{ t('gatewayHealth.marketFeed') }}</dt>
          <dd data-testid="market-feed-status" :data-status="health.market_data_feed.status">
            {{ statusLabel(health.market_data_feed.status) }}
          </dd>
        </div>
      </dl>
    </section>
  </main>
</template>

<style scoped>
.service-gateway-health {
  display: grid;
  gap: 1.25rem;
  max-width: 70rem;
  margin: 0 auto;
  padding: 1.5rem;
}

.service-gateway-health__header h1,
.service-gateway-health__facts h2 {
  margin: 0;
}

.service-gateway-health__header p,
.service-gateway-health__note {
  color: var(--el-text-color-secondary, #606266);
}

.service-gateway-health__selector {
  display: grid;
  gap: 0.5rem;
}

.service-gateway-health__controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.service-gateway-health__controls input {
  flex: 1 1 20rem;
  min-height: 2.5rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 0.375rem;
}

.service-gateway-health__controls button {
  min-height: 2.5rem;
  padding: 0.5rem 1rem;
}

.service-gateway-health__facts dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: 1rem;
  margin: 1rem 0 0;
}

.service-gateway-health__facts dl > div {
  display: grid;
  gap: 0.4rem;
  padding: 1rem;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 0.5rem;
}

.service-gateway-health__facts dt {
  color: var(--el-text-color-secondary, #606266);
}

.service-gateway-health__facts dd {
  margin: 0;
  font-weight: 600;
}

.service-gateway-health__facts small {
  overflow-wrap: anywhere;
}

.service-gateway-health__error {
  color: var(--el-color-danger, #f56c6c);
}
</style>
