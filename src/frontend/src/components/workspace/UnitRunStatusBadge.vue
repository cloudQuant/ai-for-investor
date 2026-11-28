<template>
  <SharedUnitRunStatusBadge
    :unit="badgeTarget"
    :status-text="statusLabel(unit)"
    :dot-class-override="statusDotClass(unit)"
    :mode-text="unit.trading_mode === 'live' ? t('workspaceComp.badgeLive') : t('workspaceComp.badgeSim')"
    :mode-tone="unit.trading_mode === 'live' ? 'danger' : 'info'"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { UnitRunStatusBadge as SharedUnitRunStatusBadge, type UnitRunBadgeTarget } from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import type { StrategyUnit } from '@/types/workspace'
import { statusDotClass, statusLabel } from '@/composables/useUnitTableRendering'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  unit: StrategyUnit
}>()

const badgeTarget = computed<UnitRunBadgeTarget>(() => ({
  state: props.unit.run_status,
  mode: props.unit.trading_mode,
  lock_trading: props.unit.lock_trading,
  lock_running: props.unit.lock_running,
}))
</script>
