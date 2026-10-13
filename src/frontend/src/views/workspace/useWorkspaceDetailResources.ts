import { computed, watch, type ComputedRef } from 'vue'
import type { useWorkspaceStore } from '@/stores/workspace'

type WorkspaceStore = ReturnType<typeof useWorkspaceStore>

export function useWorkspaceDetailResources(
  workspaceId: ComputedRef<string>,
  store: WorkspaceStore,
  onWorkspaceChange: () => void,
) {
  const currentWorkspace = computed(() =>
    store.activeWorkspaceId === workspaceId.value
    && store.currentWorkspace?.id === workspaceId.value
      ? store.currentWorkspace
      : null,
  )
  const currentUnits = computed(() =>
    store.activeWorkspaceId === workspaceId.value ? store.units : [],
  )

  watch(workspaceId, async (id) => {
    if (!id) {
      return
    }
    store.activateWorkspace(id)
    onWorkspaceChange()
    await Promise.all([
      store.fetchWorkspace(id),
      store.fetchUnits(id),
    ])
  }, { immediate: true })

  return { currentWorkspace, currentUnits }
}
