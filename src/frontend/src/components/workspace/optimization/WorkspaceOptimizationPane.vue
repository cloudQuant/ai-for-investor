<template>
  <el-tab-pane
    :label="t('workspaceDetail.tabOptimization')"
    name="optimization"
    closable
    lazy
  >
    <ErrorBoundary :fallback-title="t('commonUi.errorPageTitle')">
      <AsyncWorkspaceOptimizationTab
        :workspace-id="workspaceId"
        :active="active"
        :toolbar-in-header="false"
        :initial-unit-id="initialUnitId"
      />
    </ErrorBoundary>
  </el-tab-pane>
</template>

<script setup lang="ts">
import { defineComponent, h } from 'vue'
import { useI18n } from 'vue-i18n'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { createTimedAsyncComponent } from '@/components/workspace/optimization/createTimedAsyncComponent'

interface Props {
  workspaceId: string
  active: boolean
  initialUnitId: string
}

defineProps<Props>()

const { t } = useI18n()

const WorkspaceOptimizationLoading = defineComponent({
  name: 'WorkspaceOptimizationLoading',
  setup() {
    const { t: translate } = useI18n()
    return () => h(
      'div',
      {
        role: 'status',
        'aria-live': 'polite',
        class: 'workspace-optimization-loading',
        style: { display: 'grid', minHeight: '180px', placeItems: 'center' },
      },
      translate('common.loading'),
    )
  },
})

const AsyncWorkspaceOptimizationTab = createTimedAsyncComponent(
  () => import('@/components/workspace/WorkspaceOptimizationTab.vue'),
  WorkspaceOptimizationLoading,
  15_000,
)
</script>
